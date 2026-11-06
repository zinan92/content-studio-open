"""朋友圈（10/18）：X 是源头。作者 发完 X，来这页点「复刻到其他平台」，原样搬到小红书小号、抖音小号、公众号贴图。

- 不改字：文字、链接、截图原样搬；不生成配图（他的图一般就是自己的截图）。
- 小红书、抖音没有开放的发帖接口，模拟点浏览器容易被判成机器（抖音主页 10/7 已经被限过一次），
  所以这两个由他自己发：这里出现成的一份（标题、正文、原图），他复制、拖图。
- 公众号「贴图」（公众号后台 → 新的创作 → 贴图，不是视频号）走官方接口进草稿箱，他在后台点发布（10/18 作者 同意）。
- 读 X 用 fxtwitter 的公开接口：X API 按次付费，10/13 起余额用完了，小时采集也停了。
  fxtwitter 大约三次里失败一次（回 404），所以每次读最多试三遍；读到的帖子存一份，读不到时页面照样有东西。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
import urllib.request

from ...paths import config_dir

FX = "https://api.fxtwitter.com"
TRIES = 3
NEW_HOURS = 48
TITLE_MAX = 20  # 小红书标题最多 20 字；贴图标题用同一个，省得两边不一样
XHS_BODY_MAX = 1000
LIMITS = {"xhs": 18, "douyin": 35, "wechat": 20}  # 每个平台一条最多几张图
ID = re.compile(r"(?:status(?:es)?/)?(\d{8,25})")

Opener = Callable[[urllib.request.Request], Any]


class MomentsError(RuntimeError):
    """说给 作者 听的一句话。"""


def handle() -> str:
    return os.environ.get("CONTENT_STUDIO_X_HANDLE", "").lstrip("@")


def _open(opener: Opener | None) -> Opener:
    return opener or (lambda r: urllib.request.urlopen(r, timeout=20))


def _get_json(url: str, opener: Opener | None, pause: Callable[[float], None]) -> dict[str, Any]:
    last = ""
    for attempt in range(TRIES):
        try:
            with _open(opener)(urllib.request.Request(url, headers={"User-Agent": "content-studio"})) as response:
                data = json.loads(response.read().decode() or "{}")
            if data.get("code") == 200:
                return data
            last = f"fxtwitter 回 {data.get('code')}"
        except (OSError, ValueError) as exc:
            last = str(exc)
        if attempt < TRIES - 1:
            pause(1 + attempt)
    raise MomentsError(f"读不到 X（试了 {TRIES} 次）：{last}")


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    media = (raw.get("media") or {}).get("all") or []
    stamp = raw.get("created_timestamp")
    at = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat() if stamp else str(raw.get("created_at") or "")
    return {
        "id": str(raw["id"]), "url": raw.get("url") or f"https://x.com/i/status/{raw['id']}", "at": at,
        "text": str(raw.get("text") or ""),
        "photos": [m["url"] for m in media if m.get("type") == "photo" and m.get("url")],
        "video": any(m.get("type") in ("video", "gif") for m in media),
        "kind": "reply" if raw.get("replying_to") else "quote" if raw.get("quote") else "post",
        "repost": bool(raw.get("reposted_by")),
    }


def first_line(text: str) -> str:
    """标题 = 他自己的第一句，原样截，不改写。链接不进标题。"""
    head = re.split(r"[。！？!?\n]", re.sub(r"https?://\S+", "", text).strip(), maxsplit=1)[0].strip(" ：:，,")
    if len(head) <= TITLE_MAX:
        return head
    cut = max(head.rfind(ch, 0, TITLE_MAX + 1) for ch in "，,、；; ")  # 超了就在 20 字内最后一个停顿处断，不把单词切一半
    return head[:cut].rstrip(" ，,、；;") if cut >= 6 else head[:TITLE_MAX]


def packs(post: dict[str, Any], images: int) -> dict[str, Any]:
    text, title = post["text"].strip(), first_line(post["text"])
    xhs_note = [] if images else ["没图：在小红书里用「文字配图」发"]
    if len(text) > XHS_BODY_MAX:
        xhs_note.append(f"小红书正文最多 {XHS_BODY_MAX} 字，这条 {len(text)} 字，超出的部分发不进去")
    out = {
        "xhs": {"label": "小红书小号", "title": title, "body": text, "notes": xhs_note},
        "douyin": {"label": "抖音小号", "title": "", "body": text, "notes": [] if images else ["没图：在抖音里选「文字」发"]},
        "wechat": {"label": "公众号贴图", "title": title, "body": text,
                   "notes": [] if images else ["贴图至少要一张图，这条没图，公众号这次跳过"]},
    }
    for key, part in out.items():
        if images > LIMITS[key]:
            part["notes"].append(f"{part['label']}一条最多 {LIMITS[key]} 张图，这条有 {images} 张，用前 {LIMITS[key]} 张")
        part["images"] = min(images, LIMITS[key])
    if post.get("video"):
        for part in out.values():
            part["notes"].append("原帖有视频，这里只搬文字和图，视频自己传")
    return out


class Moments:
    """一份本机存档：读到过的帖子、复刻过的（图下载到本机）、存过的公众号草稿。"""

    def __init__(self, root: Path | None = None, *, opener: Opener | None = None, pause: Callable[[float], None] = time.sleep,
                 wechat_send: Any = None, wechat_creds: dict[str, str] | None = None) -> None:
        self.root = root or config_dir() / "moments"
        self.opener, self.pause = opener, pause
        self.wechat_send, self.wechat_creds = wechat_send, wechat_creds

    # -- 存档 ---------------------------------------------------------------
    def _state(self) -> dict[str, Any]:
        try:
            data = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"posts": data.get("posts") or {}, "done": data.get("done") or {}}

    def _save(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "state.json.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.root / "state.json")

    def _keep(self, posts: list[dict[str, Any]]) -> None:
        state = self._state()
        for p in posts:
            state["posts"][p["id"]] = p
        self._save(state)

    # -- 读 X ---------------------------------------------------------------
    def check(self) -> dict[str, Any]:
        """读他 X 最新的一页。只留他自己发的（不要回复、不要转发）；读不到就用存档里的，并说一声。"""
        error = None
        try:
            data = _get_json(f"{FX}/2/profile/{handle()}/statuses", self.opener, self.pause)
            fresh = [parse(r) for r in data.get("results") or [] if r.get("id")]
            self._keep([p for p in fresh if p["kind"] != "reply" and not p["repost"]])
        except MomentsError as exc:
            error = str(exc)
        return self.view(error)

    def add(self, link: str) -> dict[str, Any]:
        m = ID.search(str(link or ""))
        if not m:
            raise MomentsError("这不像一条 X 帖子的链接：要 https://x.com/…/status/数字 这种")
        post = parse(_get_json(f"{FX}/status/{m.group(1)}", self.opener, self.pause)["tweet"])
        self._keep([post])
        return post

    def view(self, error: str | None = None, now: datetime | None = None) -> dict[str, Any]:
        state, now = self._state(), now or datetime.now(timezone.utc)
        posts = sorted(state["posts"].values(), key=lambda p: p.get("at") or "", reverse=True)[:30]
        for p in posts:
            done = state["done"].get(p["id"])
            p["done"] = done
            try:
                p["new"] = not done and now - datetime.fromisoformat(p["at"]) < timedelta(hours=NEW_HOURS)
            except ValueError:
                p["new"] = False
        return {"handle": handle(), "posts": posts, "error": error}

    # -- 复刻 ---------------------------------------------------------------
    def _post(self, pid: str) -> dict[str, Any]:
        post = self._state()["posts"].get(pid)
        if not post:
            raise MomentsError("这条帖子还没读到：刷新一下，或者把链接贴进来")
        return post

    def images(self, pid: str) -> list[Path]:
        folder = self.root / pid
        return sorted(folder.glob("img-*.*"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)) if folder.is_dir() else []

    def replicate(self, pid: str) -> dict[str, Any]:
        """原图下载到本机（小红书、抖音拖图用；公众号上传也用这份），出三个平台各一份。"""
        post = self._post(pid)
        folder = self.root / pid
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "text.txt").write_text(post["text"], encoding="utf-8")
        have = self.images(pid)
        if len(have) < len(post["photos"]):
            for n, url in enumerate(post["photos"], 1):
                suffix = Path(url.split("?")[0]).suffix or ".jpg"
                target = folder / f"img-{n}{suffix}"
                if target.is_file():
                    continue
                try:
                    with _open(self.opener)(urllib.request.Request(url, headers={"User-Agent": "content-studio"})) as response:
                        target.write_bytes(response.read())
                except OSError as exc:
                    raise MomentsError(f"第 {n} 张图下载不下来：{exc}") from exc
        state = self._state()
        done = state["done"].get(pid) or {}
        state["done"][pid] = {**done, "at": done.get("at") or datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._save(state)
        return self.pack(pid)

    def pack(self, pid: str) -> dict[str, Any]:
        post, done = self._post(pid), self._state()["done"].get(pid)
        if not done:
            raise MomentsError("这条还没复刻")
        files = [p.name for p in self.images(pid)]
        return {"id": pid, "folder": str(self.root / pid), "images": files, "packs": packs(post, len(files)), "wechat": done.get("wechat")}

    def wechat_draft(self, pid: str) -> dict[str, Any]:
        """存进公众号草稿箱，做成「贴图」（newspic）。不发布：他在后台点。再存一次就更新上次那份。"""
        from ..autopost import wechat_publish as wp

        pack = self.pack(pid)
        part, files = pack["packs"]["wechat"], self.images(pid)[:LIMITS["wechat"]]
        if not files:
            raise MomentsError("贴图至少要一张图，这条没图")
        try:
            token = wp.get_token(self.wechat_creds or wp.load_credentials(), self.wechat_send)
            ids = [wp.upload_cover(f, token, self.wechat_send) for f in files]
            item = {"article_type": "newspic", "title": part["title"] or "朋友圈", "content": part["body"],
                    "image_info": {"image_list": [{"image_media_id": i} for i in ids]},
                    "need_open_comment": 1, "only_fans_can_comment": 0}
            previous = (pack.get("wechat") or {}).get("media_id")
            media_id = ""
            if previous:
                try:
                    wp._post("draft/update", token, {"media_id": previous, "index": 0, "articles": item}, self.wechat_send)
                    media_id = previous
                except wp.WechatError:
                    media_id = ""
            if not media_id:
                media_id = str(wp._post("draft/add", token, {"articles": [item]}, self.wechat_send).get("media_id") or "")
        except wp.WechatError as exc:
            raise MomentsError(str(exc)) from exc
        if not media_id:
            raise MomentsError("微信没返回草稿 id")
        state = self._state()
        record = {"media_id": media_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "updated": media_id == previous}
        state["done"][pid] = {**state["done"].get(pid, {}), "wechat": record}
        self._save(state)
        return {**record, "message": ("已更新草稿箱里那份贴图" if record["updated"] else "已存进公众号草稿箱") + "：去公众号后台点发布"}
