"""Benchmark breakouts from the last two days; the daily recommendation reads them as context.

Douyin site search is deliberately absent: its search API answers with an
anti-spam block (see issue #20), and the product never works around risk control.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .store import StudioStore


def benchmark_breakouts(store: StudioStore, *, threshold: float, hours: int = 48, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    recent, week = [], []
    for video in store.outliers(threshold):
        try:
            published = datetime.fromisoformat((video["published_at"] or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published >= cutoff:
            recent.append(video)
        elif published >= now - timedelta(days=7):
            week.append(video)
    synced = [a["last_synced_at"] for a in store.followed_accounts() if a["last_synced_at"]]
    key = lambda v: -v["multiple"]
    return {
        "items": sorted(recent, key=key),
        "fallback": sorted(week, key=key)[:3] if not recent else [],
        "last_synced_at": min(synced) if synced else None,
        "hours": hours,
    }


VIDEO_URL = re.compile(r"douyin\.com/video/(\d+)")


def video_id_in(url: str | None) -> str | None:
    match = VIDEO_URL.search(url or "")
    return match.group(1) if match else None


def mark_breakouts(items: list[dict[str, Any]], outliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给进项条目打上「爆了」标记。

    对标的文字稿在 frontmatter 里带着 `source: …/video/<id>`，所以笔记和视频记录能对上。
    倍数是「这条的赞 ÷ 这个作者平时的中位数」——5.3× 只有在知道他平时多少时才有意义，
    所以两个数一起给前端。
    """
    by_id = {v["video_id"]: v for v in outliers}
    marked = []
    for item in items:
        video = by_id.get(video_id_in(item.get("url")))
        if video is None:
            marked.append(item)
            continue
        marked.append({**item, "breakout": {
            "multiple": video["multiple"],
            "likes": video["likes"],
            "median": video["account_median"],
            "account": video.get("account_nickname"),
        }})
    return marked
