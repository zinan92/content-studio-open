"""Transcripts of what the accounts 作者 follows just posted, written into his vault.

When a followed account posts a breakout (≥ 2× its median likes, this week) or 作者 asks for one, the workbench tears the video down (download → 转文字 →
结构拆解) and saves the transcript as a note in `002_对标内容`. From there it behaves like
any other note in 进项: 作者 reads it in the right pane, takes it into the 选题池, or
attaches it to a topic as 素材 — none of which works while the text only lives in a report.

Announcements are dropped rather than saved. 作者's rule: filter on the content, not on
likes. A 「今晚 8 点见」 clip has no content to read, so it never becomes a note — but it is
only judged after transcription, because that is the first moment the content exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import tempfile
from typing import Any

FOLDER = "002_对标内容"
# 作者自己发出去的，和对标分开放：分析「我的内容适不适合走某条路线」时，要读的是
# 自己讲了什么、怎么开头、哪里散了——不是点赞数。之前只有对标有文字稿，自己一条没有。
MINE_FOLDER = "005_我发出的内容"
MIN_CHARS = 300
MIN_SECONDS = 40
# 进项是为了「今天拍什么」服务的。第一次加一个对标账号会同步他的全部历史作品，
# 半年前的视频今天才进来，在列表里长得和今天发的一样新，但对今天的选题毫无用处。
FRESH_DAYS = 30
# 预告、开播、上架这类：视频本身就是一句通知，没有可读的内容。
ANNOUNCEMENT = re.compile(
    r"(今晚|今天|明天|明晚)?\s*\d{1,2}\s*点\s*(见|开播|直播)|预告|开播|直播间|抽奖|倒计时|上架|"
    r"新课|报名|领取|置顶|公告|通知一下|凡尔赛一下"
)


def looks_like_announcement(title: str) -> bool:
    """Judged from the title alone, before anything is downloaded.

    作者's reason is not only the filter: a downloaded video is stored before it can be
    judged, so deciding from the title saves both a fetch and the disk it would have taken.
    """
    return bool(ANNOUNCEMENT.search(title or ""))


def is_stale(published_at: str | None, *, days: int = FRESH_DAYS, now: datetime | None = None) -> bool:
    """Published too long ago to be worth putting in 进项 today."""
    if not published_at:
        return False
    try:
        when = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - when > timedelta(days=days)


def is_thin(*, title: str, text: str, duration_seconds: float | None, published_at: str | None = None) -> str | None:
    """Why this video is not worth saving, or None if it is."""
    if looks_like_announcement(title):
        return "标题像预告/公告，不是内容"
    if is_stale(published_at, days=FRESH_DAYS):
        return f"{(published_at or '')[:10]} 发的，超过 {FRESH_DAYS} 天，对今天的选题没用了"
    if duration_seconds is not None and duration_seconds < MIN_SECONDS:
        return f"只有 {round(duration_seconds)} 秒，太短"
    if len(text.strip()) < MIN_CHARS:
        return f"转出来只有 {len(text.strip())} 字，没什么可读的"
    return None


def transcript_text(report: dict[str, Any]) -> str:
    segments = report.get("segments") or []
    return "\n\n".join(str(s.get("text") or "").strip() for s in segments if s.get("text"))


def _plain(value: Any) -> str:
    """Report fields are {text, evidence} objects; the note only wants the sentence."""
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def _slug(title: str) -> str:
    return re.sub(r"[\\/:*?\"<>|#\[\]\s]+", " ", title or "").strip()[:40] or "无标题"


def note_name(*, published_at: str | None, account: str, title: str) -> str:
    day = (published_at or "")[:10] or datetime.now().date().isoformat()
    return f"{day} {_slug(account)} {_slug(title)}.md".replace("/", "／")


def render_image_post(*, video: dict[str, Any], account: str) -> str:
    """图文帖没有口播可转写。照样给它一篇——分析内容时「哪几条是图文」本身就是信息。"""
    url = f"https://www.douyin.com/video/{video['video_id']}"
    title = (video.get("title") or "").strip()
    return "\n".join([
        "---",
        f"title: {title.splitlines()[0][:60] if title else ''}",
        f"source: {url}",
        f"author: {account}",
        f"published: {(video.get('published_at') or '')[:19]}",
        f"likes: {video.get('likes')}",
        "format: 图文",
        "by: content-studio",
        "---",
        "",
        f"# {title.splitlines()[0][:60] if title else '（无标题）'}",
        "",
        f"{account} · [原帖]({url}) · 图文帖",
        "",
        "## 说明",
        "",
        "这条是图文帖，没有口播内容，所以没有文字稿。下面是发布时写的文案全文。",
        "",
        "## 文案全文",
        "",
        title or "（没有文案）",
        "",
    ]) + "\n"


def render(*, video: dict[str, Any], account: str, report: dict[str, Any], text: str) -> str:
    facts = report.get("facts") or {}
    url = f"https://www.douyin.com/video/{video['video_id']}"
    head = "\n".join(
        [
            "---",
            f"title: {report.get('title') or video.get('title') or ''}",
            f"source: {url}",
            f"author: {account}",
            f"published: {(video.get('published_at') or '')[:19]}",
            f"likes: {facts.get('likes')}",
            f"multiple_of_median: {facts.get('multiple_of_median')}",
            "by: content-studio",
            "---",
            "",
        ]
    )
    body = [f"# {report.get('title') or video.get('title') or ''}", "", f"{account} · [原视频]({url})", ""]
    thesis = _plain(report.get("thesis"))
    if thesis:
        body += ["## 主线", thesis, ""]
    boom = [_plain(item) for item in (report.get("why_boom") or [])]
    if any(boom):
        body += ["## 为什么爆", *[f"- {line}" for line in boom if line], ""]
    body += ["## 全文", "", text.strip(), ""]
    return head + "\n".join(body)


def write_note(vault_root: Path, name: str, markdown: str, folder: str = FOLDER) -> str:
    """Write one transcript into the vault, atomically. Returns the vault-relative path."""
    folder_name = folder
    folder = vault_root / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=".t-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return f"{folder_name}/{name}"
