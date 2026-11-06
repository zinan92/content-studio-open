from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse

from .store import StoreError, StudioStore, now_iso

logger = logging.getLogger(__name__)


PLATFORM_DOUYIN = "抖音"
PLATFORM_XHS = "小红书"
PLATFORM_X = "X"
PLATFORM_CHANNELS = "视频号"

STATUS_ACTIVE = "active"
STATUS_PENDING_PLATFORM = "pending_platform"
STATUS_ERROR = "error"

PENDING_NOTES = {
    PLATFORM_XHS: "小红书风控严，抓取方式需单独设计，接入前先记录在库里。",
    PLATFORM_X: "X 的抓取方式待接入，接入前先记录在库里。",
    PLATFORM_CHANNELS: "视频号一般没有公开主页链接，抓取方式待接入，先记录在库里。",
}


class AccountError(RuntimeError):
    """A pasted profile link could not be understood or synced."""


class RiskControlStop(AccountError):
    """Douyin showed a verification page; syncing must stop immediately."""


@dataclass(frozen=True)
class ParsedProfile:
    platform: str
    profile_url: str
    external_id: str | None
    needs_resolution: bool = False


_DOUYIN_USER = re.compile(r"douyin\.com/user/([A-Za-z0-9_\-]+)")
_XHS_USER = re.compile(r"xiaohongshu\.com/user/profile/([A-Za-z0-9]+)")
_X_USER = re.compile(r"^(?:www\.|mobile\.)?(?:x|twitter)\.com$")


def parse_profile_url(raw: str) -> ParsedProfile:
    """Recognise a creator profile link on one of the supported platforms."""
    text = (raw or "").strip()
    match = re.search(r"https?://\S+", text)
    url = match.group(0) if match else text
    if not url:
        raise AccountError("请粘贴账号主页链接")
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    douyin = _DOUYIN_USER.search(url)
    if douyin and douyin.group(1) != "self":
        sec_uid = douyin.group(1)
        return ParsedProfile(PLATFORM_DOUYIN, f"https://www.douyin.com/user/{sec_uid}", sec_uid)
    if host in {"v.douyin.com", "www.iesdouyin.com", "iesdouyin.com"}:
        return ParsedProfile(PLATFORM_DOUYIN, url.split("?", 1)[0], None, needs_resolution=True)
    if "douyin.com" in host:
        raise AccountError("这是抖音链接，但不是账号主页。请在抖音网页版打开对方主页，复制地址栏里 /user/ 开头的链接")

    xhs = _XHS_USER.search(url)
    if xhs:
        return ParsedProfile(PLATFORM_XHS, f"https://www.xiaohongshu.com/user/profile/{xhs.group(1)}", xhs.group(1))
    if host == "xhslink.com":
        return ParsedProfile(PLATFORM_XHS, url.split("?", 1)[0], None)
    if "xiaohongshu.com" in host:
        raise AccountError("这是小红书链接，但不是账号主页。请复制 /user/profile/ 开头的主页链接")

    if _X_USER.match(host):
        handle = parsed.path.strip("/").split("/")[0]
        if not handle or handle in {"home", "explore", "search", "i", "settings", "notifications"}:
            raise AccountError("这是 X 链接，但没有包含账号名。请复制 x.com/账号名 形式的主页链接")
        return ParsedProfile(PLATFORM_X, f"https://x.com/{handle}", handle.lower())

    if "weixin.qq.com" in host:
        return ParsedProfile(PLATFORM_CHANNELS, url.split("#", 1)[0], None)

    raise AccountError("没认出平台：请粘贴抖音、小红书、X 或视频号的账号主页链接")


# ---------------------------------------------------------------------------
# Douyin client seam (real client from content-downloader, fakes in tests)
# ---------------------------------------------------------------------------


class DouyinClient(Protocol):
    async def resolve_profile(self, short_url: str) -> str | None: ...

    async def profile(self, sec_uid: str) -> dict[str, Any]: ...

    async def posts(self, sec_uid: str, cursor: int) -> dict[str, Any]: ...


ClientFactory = Callable[[], Any]


class ContentDownloaderClient:
    """Adapter over content-downloader's signed Douyin web client."""

    def __init__(self, cookies: dict[str, str]) -> None:
        from .deps import ensure_content_downloader

        ensure_content_downloader()
        try:
            from content_downloader.adapters.douyin.api_client import DouyinAPIClient
        except ImportError as exc:
            raise AccountError("content-downloader 未安装或不可导入，无法同步抖音账号") from exc
        self._client = DouyinAPIClient(cookies=cookies)
        self._cookies = dict(cookies)

    async def __aenter__(self) -> "ContentDownloaderClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(*exc)

    async def resolve_profile(self, short_url: str) -> str | None:
        return await self._client.resolve_short_url(short_url)

    async def profile(self, sec_uid: str) -> dict[str, Any]:
        params = await self._client._default_query()
        params.update({"sec_user_id": sec_uid, "publish_video_strategy_type": "2"})
        raw = await self._client._request_json("/aweme/v1/web/user/profile/other/", params)
        raw = raw or {}
        if raw.get("verify_ticket"):
            raise RiskControlStop("抖音要求验证，已停止同步。请在浏览器里打开抖音完成验证后再试")
        return raw.get("user") or {}

    async def posts(self, sec_uid: str, cursor: int) -> dict[str, Any]:
        return await self._client.get_user_post(sec_uid, max_cursor=cursor, count=20)

    async def browser_posts(self, sec_uid: str, pages: int) -> list[dict[str, Any]]:
        """接口被拒时的兜底：真的 Chrome 打开主页，读页面自己拿到的列表。"""
        from .douyin_browser import fetch_user_posts

        got = await asyncio.to_thread(fetch_user_posts, sec_uid, self._cookies, pages=pages)
        return got.posts


def normalize_post(post: dict[str, Any]) -> dict[str, Any] | None:
    video_id = str(post.get("aweme_id") or "").strip()
    if not video_id:
        return None
    stats = post.get("statistics") or {}
    video = post.get("video") or {}
    duration_ms = post.get("duration") or video.get("duration") or 0
    created = post.get("create_time")
    published = (
        datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat(timespec="seconds") if created else None
    )
    is_image = bool(post.get("images") or post.get("image_post_info")) or not duration_ms
    return {
        "platform": PLATFORM_DOUYIN,
        "video_id": video_id,
        "title": str(post.get("desc") or "").strip() or "（无标题）",
        "published_at": published,
        "duration_seconds": round(float(duration_ms) / 1000, 1) if duration_ms else None,
        "is_top": int(bool(post.get("is_top"))),
        "is_image_post": int(is_image),
        "likes": _maybe_int(stats.get("digg_count")),
        "comments": _maybe_int(stats.get("comment_count")),
        "shares": _maybe_int(stats.get("share_count")),
        "collects": _maybe_int(stats.get("collect_count")),
        "views": _maybe_int(stats.get("play_count")) or None,
    }


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Service operations
# ---------------------------------------------------------------------------


def add_account(
    store: StudioStore,
    raw_url: str,
    *,
    client_factory: ClientFactory | None = None,
    is_self: bool = False,
    kind: str | None = None,
) -> dict[str, Any]:
    """Recognise the link and put the account in the library (does not sync)."""
    parsed = parse_profile_url(raw_url)
    external_id = parsed.external_id
    profile_url = parsed.profile_url
    if parsed.platform == PLATFORM_DOUYIN and parsed.needs_resolution:
        if client_factory is None:
            raise AccountError("短链接需要联网解析，请稍后重试")
        resolved = asyncio.run(_resolve(client_factory, parsed.profile_url))
        again = parse_profile_url(resolved or "")
        if again.platform != PLATFORM_DOUYIN or not again.external_id:
            raise AccountError("短链接没有指向抖音账号主页，请复制对方主页链接")
        external_id, profile_url = again.external_id, again.profile_url
    status = STATUS_ACTIVE if parsed.platform == PLATFORM_DOUYIN else STATUS_PENDING_PLATFORM
    try:
        return store.add_account(
            platform=parsed.platform,
            profile_url=profile_url,
            external_id=external_id,
            status=status,
            is_self=is_self,
            kind=kind,
        )
    except StoreError as exc:
        raise AccountError(str(exc)) from exc


async def _resolve(client_factory: ClientFactory, url: str) -> str | None:
    async with client_factory() as client:
        return await client.resolve_profile(url)


def sync_account(
    store: StudioStore,
    account_id: int,
    *,
    client_factory: ClientFactory,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    pages: int | None = None,
) -> dict[str, Any]:
    """One serial pass: profile + up to N pages of posts. Stops on risk control.

    `pages` 只给「拉更早的作品」用：平时 3 页（约 60 条）够看近况，想找一条更早的就得往回翻。
    """
    account = store.account(account_id)
    if account["platform"] != PLATFORM_DOUYIN:
        raise AccountError(PENDING_NOTES.get(account["platform"], "该平台抓取待接入"))
    settings = store.settings()
    try:
        profile, posts = asyncio.run(
            _fetch_account(
                client_factory,
                account["external_id"],
                pages=int(pages or settings["sync_pages"]),
                delay=float(settings["sync_delay_seconds"]),
                sleep=sleep,
            )
        )
    except RiskControlStop as exc:
        store.update_account(account_id, status=STATUS_ERROR, last_error=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 - surface every failure on the account card
        message = str(exc) if isinstance(exc, AccountError) else f"同步失败：{type(exc).__name__}: {exc}"
        store.update_account(account_id, status=STATUS_ERROR, last_error=message[:300])
        raise AccountError(message) from exc

    videos = [video for video in (normalize_post(post) for post in posts) if video]
    store.upsert_videos(account_id, videos)
    fields: dict[str, Any] = {"status": STATUS_ACTIVE, "last_error": None, "last_synced_at": now_iso()}
    if profile.get("nickname"):
        fields["nickname"] = profile["nickname"]
    elif posts and (posts[0].get("author") or {}).get("nickname"):
        fields["nickname"] = posts[0]["author"]["nickname"]
    for key in ("follower_count", "total_favorited"):
        if profile.get(key) is not None:
            fields[key] = _maybe_int(profile[key])
    if profile.get("signature") is not None:
        fields["signature"] = str(profile["signature"])[:300]
    return {"account": store.update_account(account_id, **fields), "video_count": len(videos)}


async def _fetch_account(
    client_factory: ClientFactory,
    sec_uid: str,
    *,
    pages: int,
    delay: float,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    async with client_factory() as client:
        profile = await client.profile(sec_uid)
        posts: list[dict[str, Any]] = []
        cursor = 0
        for page in range(pages):
            await sleep(delay)
            data = await client.posts(sec_uid, cursor)
            risk = data.get("risk_flags") or {}
            if risk.get("verify_page"):
                raise RiskControlStop("抖音要求验证，已停止同步。请在浏览器里打开抖音完成验证后再试")
            status_code = data.get("status_code") or 0
            if status_code:
                raise AccountError(f"抖音返回错误码 {status_code}，可能是登录已过期：请重新登录抖音并导出 cookies")
            if page == 0 and not data.get("items") and _has_works(profile):
                # 资料说有作品、列表却是空的 = 接口被拒（9/27 起 /aweme/post/ 返回 403）。换真的浏览器读。
                browser = getattr(client, "browser_posts", None)
                if browser is None:
                    break
                try:
                    posts = await browser(sec_uid, pages)
                except Exception as exc:  # noqa: BLE001 - 说清楚卡在哪，不要只剩一个异常名
                    raise AccountError(f"抖音拒绝了作品列表接口，改用浏览器读取也失败：{exc}") from exc
                if not posts:
                    raise AccountError("抖音拒绝读取作品列表（接口和浏览器都没拿到）。资料能读，作品读不到，先别信这次的数")
                break
            posts.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            cursor = int(data.get("max_cursor") or 0)
    if not posts and not profile:
        raise AccountError("没有拉到任何作品和资料，可能是登录已过期：请重新登录抖音并导出 cookies")
    return profile, posts


def _has_works(profile: dict[str, Any]) -> bool:
    try:
        return int(profile.get("aweme_count") or 0) > 0
    except (TypeError, ValueError):
        return False
