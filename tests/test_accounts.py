from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_studio.accounts import (
    AccountError,
    RiskControlStop,
    add_account,
    normalize_post,
    parse_profile_url,
    sync_account,
)
from content_studio.store import StoreError, StudioStore


SEC = "MS4wLjABAAAAtest_sec-uid"


@pytest.fixture
def store(tmp_path: Path) -> StudioStore:
    value = StudioStore(tmp_path / "studio.sqlite3")
    yield value
    value.close()


def _post(aweme_id: str, likes: int, *, top: bool = False, duration: int = 60000) -> dict:
    return {
        "aweme_id": aweme_id,
        "desc": f"视频 {aweme_id}",
        # 相对「现在」，不写死：写死的发布时间迟早会掉出所有时间窗口。
        "create_time": int((datetime.now(timezone.utc) - timedelta(days=6) + timedelta(hours=int(aweme_id))).timestamp()),
        "is_top": int(top),
        "duration": duration,
        "statistics": {"digg_count": likes, "comment_count": 1, "share_count": 2, "collect_count": 3, "play_count": 0},
        "author": {"nickname": "作者"},
    }


class FakeClient:
    def __init__(self, pages: list[dict], profile: dict | None = None, resolved: str | None = None) -> None:
        self.pages = pages
        self.profile_data = profile if profile is not None else {"nickname": "对标号", "follower_count": 1000}
        self.resolved = resolved
        self.calls: list[tuple] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def resolve_profile(self, url: str) -> str | None:
        self.calls.append(("resolve", url))
        return self.resolved

    async def profile(self, sec_uid: str) -> dict:
        self.calls.append(("profile", sec_uid))
        return self.profile_data

    async def posts(self, sec_uid: str, cursor: int) -> dict:
        self.calls.append(("posts", cursor))
        return self.pages[len([c for c in self.calls if c[0] == "posts"]) - 1]


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("url", "platform", "external_id"),
    [
        (f"https://www.douyin.com/user/{SEC}?from_tab_name=main", "抖音", SEC),
        (f"看看这个 https://www.douyin.com/user/{SEC} 复制打开", "抖音", SEC),
        ("https://www.xiaohongshu.com/user/profile/5f1a2b3c4d?xsec=1", "小红书", "5f1a2b3c4d"),
        ("https://x.com/SamAltman/status/1", "X", "samaltman"),
        ("twitter.com/karpathy", "X", "karpathy"),
        ("https://channels.weixin.qq.com/abc", "视频号", None),
    ],
)
def test_parse_profile_url_recognises_supported_platforms(url: str, platform: str, external_id: str | None) -> None:
    parsed = parse_profile_url(url)
    assert parsed.platform == platform
    assert parsed.external_id == external_id


@pytest.mark.parametrize(
    "url",
    ["", "https://www.douyin.com/video/123", "https://x.com/home", "https://example.com/u/1"],
)
def test_parse_profile_url_rejects_non_profile_links_with_guidance(url: str) -> None:
    with pytest.raises(AccountError):
        parse_profile_url(url)


def test_add_account_marks_other_platforms_pending_and_rejects_duplicates(store: StudioStore) -> None:
    douyin = add_account(store, f"https://www.douyin.com/user/{SEC}")
    assert douyin["status"] == "active"
    xhs = add_account(store, "https://www.xiaohongshu.com/user/profile/abc123")
    assert xhs["status"] == "pending_platform"
    with pytest.raises(AccountError, match="已经在库里"):
        add_account(store, f"https://www.douyin.com/user/{SEC}?from=share")


def test_short_link_is_resolved_to_profile(store: StudioStore) -> None:
    client = FakeClient([], resolved=f"https://www.douyin.com/user/{SEC}?previous_page=app_code_link")
    account = add_account(store, "https://v.douyin.com/AbCdEf/", client_factory=lambda: client)
    assert account["external_id"] == SEC


def test_sync_stores_profile_videos_and_median_excluding_pinned(store: StudioStore) -> None:
    account = add_account(store, f"https://www.douyin.com/user/{SEC}")
    pages = [
        {"items": [_post("1", 100000, top=True), _post("2", 1000), _post("3", 2000)], "has_more": True, "max_cursor": 9},
        {"items": [_post("4", 3000), _post("5", 60000)], "has_more": False},
    ]
    client = FakeClient(pages)
    result = sync_account(store, account["id"], client_factory=lambda: client, sleep=_no_sleep)
    assert result["video_count"] == 5
    assert result["account"]["nickname"] == "对标号"
    assert result["account"]["follower_count"] == 1000
    assert store.account_median(account["id"]) == 2500.0
    assert ("posts", 9) in client.calls
    outliers = store.outliers(5.0)
    # Pinned posts are excluded from the median but can still be breakout samples.
    assert [video["video_id"] for video in outliers] == ["1", "5"]
    assert outliers[1]["multiple"] == 24.0


def test_sync_respects_page_limit_and_delay_setting(store: StudioStore) -> None:
    store.update_settings({"sync_pages": 2, "sync_delay_seconds": 2.0})
    account = add_account(store, f"https://www.douyin.com/user/{SEC}")
    pages = [{"items": [_post(str(i), 10)], "has_more": True, "max_cursor": i} for i in range(1, 5)]
    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)

    sync_account(store, account["id"], client_factory=lambda: FakeClient(pages), sleep=record)
    assert len(store.videos(account["id"])) == 2
    assert delays == [2.0, 2.0]
    with pytest.raises(StoreError):
        store.update_settings({"sync_delay_seconds": 0.5})


def test_risk_control_stops_sync_and_is_recorded_on_the_account(store: StudioStore) -> None:
    account = add_account(store, f"https://www.douyin.com/user/{SEC}")
    pages = [{"items": [], "has_more": True, "risk_flags": {"verify_page": True}}, {"items": [_post("9", 1)]}]
    client = FakeClient(pages)
    with pytest.raises(RiskControlStop):
        sync_account(store, account["id"], client_factory=lambda: client, sleep=_no_sleep)
    assert len([c for c in client.calls if c[0] == "posts"]) == 1
    refreshed = store.account(account["id"])
    assert refreshed["status"] == "error"
    assert "验证" in refreshed["last_error"]


def test_pending_platform_accounts_cannot_sync(store: StudioStore) -> None:
    account = add_account(store, "https://x.com/someone")
    with pytest.raises(AccountError, match="待接入"):
        sync_account(store, account["id"], client_factory=lambda: FakeClient([]), sleep=_no_sleep)


def test_self_account_is_excluded_from_outliers_and_cannot_be_removed(store: StudioStore) -> None:
    me = add_account(store, f"https://www.douyin.com/user/{SEC}", is_self=True)
    store.upsert_videos(me["id"], [normalize_post(_post("1", 10)), normalize_post(_post("2", 1000))])
    assert store.outliers(2.0) == []
    with pytest.raises(StoreError):
        store.delete_account(me["id"])


def test_image_posts_are_flagged_and_not_breakouts(store: StudioStore) -> None:
    account = add_account(store, f"https://www.douyin.com/user/{SEC}")
    store.upsert_videos(
        account["id"],
        [normalize_post(_post("1", 10)), normalize_post(_post("2", 10)), normalize_post(_post("3", 9999, duration=0))],
    )
    assert store.video("3")["is_image_post"] == 1
    assert store.outliers(5.0) == []


def test_followed_posts_window_on_publish_date_not_on_when_they_were_first_seen(tmp_path: Path) -> None:
    """A newly added account's first sync pulls its whole back catalogue; only what it actually
    published this week belongs in 进项."""
    from datetime import datetime, timedelta, timezone

    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "followed.sqlite3")
    a = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/a", external_id="a", status="ok")
    b = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/b", external_id="b", status="ok")
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    base = dict(platform="抖音", duration_seconds=60, is_top=0, is_image_post=0, comments=0, shares=0, collects=0, views=None)
    for account in (a, b, me):
        store.upsert_videos(
            account["id"],
            [dict(base, video_id=f"{account['id']}-{i}", title=f"v{i}", published_at=(now - timedelta(days=30 + i)).isoformat(), likes=100) for i in range(5)]
            + [dict(base, video_id=f"{account['id']}-hot", title="hot", published_at=(now - timedelta(days=2)).isoformat(), likes=5000)],
        )
    # Everyone 作者 follows counts the same way; his own account never does.
    assert {v["video_id"] for v in store.followed_posts(7, now)} == {f"{a['id']}-hot", f"{b['id']}-hot"}
    assert {v["video_id"] for v in store.outliers(5.0)} == {f"{a['id']}-hot", f"{b['id']}-hot"}
    assert [x["id"] for x in store.followed_accounts()] == [a["id"], b["id"]]
    store.close()


def test_kind_migration_backfills_an_account_table_that_predates_kinds(tmp_path: Path) -> None:
    import sqlite3

    from content_studio.store import StudioStore

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, profile_url TEXT NOT NULL,"
        " external_id TEXT, nickname TEXT, follower_count INTEGER, total_favorited INTEGER, signature TEXT,"
        " is_self INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, last_error TEXT, added_at TEXT NOT NULL,"
        " last_synced_at TEXT, UNIQUE(platform, external_id));"
        "INSERT INTO accounts(platform, profile_url, is_self, status, added_at) VALUES('抖音', 'a', 1, 'ok', 'now');"
        "INSERT INTO accounts(platform, profile_url, is_self, status, added_at) VALUES('抖音', 'b', 0, 'ok', 'now');"
    )
    conn.commit()
    conn.close()

    store = StudioStore(path)
    assert [a["kind"] for a in store.accounts()] == ["self", "benchmark"]
    store.close()


def test_deep_sync_goes_further_back_and_keeps_what_was_there(store: StudioStore) -> None:
    """9/24：一勾 7/3 那条不在库里——平时只拉 3 页。往回翻多拉几页，已有的作品不丢。"""
    store.update_settings({"sync_pages": 2, "sync_delay_seconds": 2.0})
    account = add_account(store, f"https://www.douyin.com/user/{SEC}")
    pages = [{"items": [_post(str(i), 10)], "has_more": True, "max_cursor": i} for i in range(1, 9)]
    sync_account(store, account["id"], client_factory=lambda: FakeClient(pages), sleep=_no_sleep)
    assert len(store.videos(account["id"])) == 2
    sync_account(store, account["id"], client_factory=lambda: FakeClient(pages), sleep=_no_sleep, pages=6)
    assert len(store.videos(account["id"])) == 6


def test_public_videos_drops_ones_the_latest_sync_no_longer_saw(store: StudioStore) -> None:
    """作者 9/27：只看公开的作品。设成私密后，公开主页的同步就不再刷新它。"""
    acct = add_account(store, f"https://www.douyin.com/user/{SEC}")
    base = {"platform": "douyin", "title": "t", "published_at": "2026-09-12T00:00:00+00:00", "duration_seconds": 10,
            "is_top": 0, "is_image_post": 0, "likes": 0, "comments": 0, "shares": 0, "collects": 0, "views": 0}
    store.upsert_videos(acct["id"], [{**base, "video_id": "gone"}, {**base, "video_id": "kept"}])
    with store.tx() as conn:
        conn.execute("UPDATE videos SET fetched_at = '2026-09-15T08:18:12+00:00' WHERE video_id = 'gone'")
        conn.execute("UPDATE videos SET fetched_at = '2026-09-26T01:53:54+00:00' WHERE video_id = 'kept'")
    assert [v["video_id"] for v in store.public_videos(acct["id"])] == ["kept"]


class RefusedListClient(FakeClient):
    """9/27：资料接口能读（作品 62 条），作品列表接口被拒，回来的是空页。"""

    def __init__(self, browser: list[dict] | None) -> None:
        super().__init__([{"items": [], "has_more": False}], profile={"nickname": "徐兆猛", "aweme_count": 62})
        self.browser = browser

    async def browser_posts(self, sec_uid: str, pages: int) -> list[dict]:
        self.calls.append(("browser", pages))
        return self.browser or []


def test_refused_post_list_falls_back_to_the_browser(store: StudioStore) -> None:
    acct = add_account(store, f"https://www.douyin.com/user/{SEC}")
    client = RefusedListClient([_post("1", 10), _post("2", 20)])
    result = sync_account(store, acct["id"], client_factory=lambda: client, sleep=_no_sleep)
    assert result["video_count"] == 2 and ("browser", 3) in client.calls


def test_refused_everywhere_is_an_error_not_a_silent_zero(store: StudioStore) -> None:
    acct = add_account(store, f"https://www.douyin.com/user/{SEC}")
    with pytest.raises(AccountError, match="拒绝读取作品列表"):
        sync_account(store, acct["id"], client_factory=lambda: RefusedListClient(None), sleep=_no_sleep)
    assert "拒绝读取作品列表" in store.account(acct["id"])["last_error"]


def test_browser_pages_dedupe_and_track_has_more() -> None:
    from content_studio.douyin_browser import Pages

    got = Pages()
    got.add({"aweme_list": [{"aweme_id": "1"}, {"aweme_id": "2"}], "has_more": 1})
    got.add({"aweme_list": [{"aweme_id": "2"}, {"aweme_id": "3"}], "has_more": 0})
    assert [p["aweme_id"] for p in got.posts] == ["1", "2", "3"] and got.pages == 2 and not got.has_more


class BrokenBrowserClient(RefusedListClient):
    async def browser_posts(self, sec_uid: str, pages: int) -> list[dict]:
        raise RuntimeError("这台电脑没装浏览器组件")


def test_browser_failure_names_the_cause_not_a_bare_exception(store: StudioStore) -> None:
    acct = add_account(store, f"https://www.douyin.com/user/{SEC}")
    with pytest.raises(AccountError, match="浏览器读取也失败：这台电脑没装浏览器组件"):
        sync_account(store, acct["id"], client_factory=lambda: BrokenBrowserClient(None), sleep=_no_sleep)


def test_missing_playwright_says_how_to_install_it(monkeypatch) -> None:
    import sys
    from content_studio import douyin_browser

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    with pytest.raises(douyin_browser.BrowserUnavailable, match="playwright install chromium"):
        asyncio.run(douyin_browser.user_posts(SEC, {}, pages=1))


class _Chromium:
    def __init__(self, has_chrome: bool) -> None:
        self.has_chrome = has_chrome
        self.launches: list[tuple[str, str | None]] = []

    async def launch_persistent_context(self, user_data_dir: str, **kw):
        self.launches.append((user_data_dir, kw.get("channel")))
        if kw.get("channel") == "chrome" and not self.has_chrome:
            raise RuntimeError("Chromium distribution 'chrome' is not found")
        return "ctx"


def test_without_google_chrome_the_bundled_chromium_reads_the_page() -> None:
    from content_studio import douyin_browser

    chromium = _Chromium(has_chrome=False)
    pw = type("PW", (), {"chromium": chromium})()
    assert asyncio.run(douyin_browser._launch(pw)) == "ctx"
    (chrome_dir, chrome), (fallback_dir, fallback) = chromium.launches
    assert chrome == "chrome" and fallback is None
    # 两种浏览器的配置文件不通用，各用各的文件夹
    assert chrome_dir.endswith("douyin-chrome") and fallback_dir.endswith("douyin-chromium")


def test_google_chrome_is_used_when_installed() -> None:
    from content_studio import douyin_browser

    chromium = _Chromium(has_chrome=True)
    pw = type("PW", (), {"chromium": chromium})()
    asyncio.run(douyin_browser._launch(pw))
    assert [c for _, c in chromium.launches] == ["chrome"]
