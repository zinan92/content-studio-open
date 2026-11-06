"""After a topic is shot and published: find its Douyin video and show how it performs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
from typing import Any

MILESTONES = ((24, "24 小时"), (72, "72 小时"), (168, "7 天"))
TEARDOWN_AFTER_HOURS = 48
STALE_SYNC_HOURS = 6


def parse_time(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _normalize(title: str) -> str:
    text = re.sub(r"#[^\s#]+", "", title or "")
    return re.sub(r"[\W_]+", "", text.lower())


def title_similarity(a: str, b: str) -> float:
    left, right = _normalize(a), _normalize(b)
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    grams = lambda s: {s[i : i + 2] for i in range(len(s) - 1)}  # noqa: E731
    overlap = len(grams(left) & grams(right)) / max(1, min(len(grams(left)), len(grams(right))))
    return round(max(ratio, overlap * 0.9), 3)


def older_than_topic(topic: dict[str, Any], video: dict[str, Any]) -> bool:
    """这条视频比选题建得还早（留一天余量：先拍后建选题的也有）——不可能是这个选题发出去的那条。"""
    created, published = parse_time(topic.get("created_at")), parse_time(video.get("published_at"))
    return bool(created and published and published < created - timedelta(days=1))


def suggest_matches(topic: dict[str, Any], videos: list[dict[str, Any]], taken: set[str], limit: int = 3) -> list[dict[str, Any]]:
    created = parse_time(topic.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)
    scored = []
    for video in videos:
        published = parse_time(video.get("published_at"))
        if video["video_id"] in taken or video.get("is_image_post") or published is None or published < created - timedelta(days=1):
            continue
        score = title_similarity(topic["title"], video.get("title") or "")
        if score >= 0.25:
            scored.append({**video, "score": score})
    return sorted(scored, key=lambda v: -v["score"])[:limit]


def performance(
    video: dict[str, Any],
    *,
    median_likes: float | None,
    snapshots: list[dict[str, Any]],
    creator: dict[str, Any] | None,
    has_report: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    published = parse_time(video.get("published_at"))
    hours = round((now - published).total_seconds() / 3600, 1) if published else None
    series = []
    for snap in snapshots:
        at = parse_time(snap["fetched_at"])
        if at and published:
            series.append({**snap, "hours": round((at - published).total_seconds() / 3600, 1)})
    milestones = []
    for limit_hours, label in MILESTONES:
        before = [s for s in series if 0 <= s["hours"] <= limit_hours * 1.15]
        reached = hours is not None and hours >= limit_hours
        pick = before[-1] if before and reached else None
        milestones.append({"hours": limit_hours, "label": label, "reached": reached, "likes": pick["likes"] if pick else None,
                           "views": pick["views"] if pick else None, "at_hours": pick["hours"] if pick else None})
    likes = video.get("likes")
    return {
        "video_id": video["video_id"],
        "title": video.get("title"),
        "published_at": video.get("published_at"),
        "url": f"https://www.douyin.com/video/{video['video_id']}",
        "hours_since": hours,
        "likes": likes,
        "views": (creator or {}).get("view_count") or video.get("views"),
        "collects": video.get("collects"),
        "shares": video.get("shares"),
        "comments": video.get("comments"),
        "multiple": round(likes / median_likes, 1) if likes is not None and median_likes else None,
        "collect_per_like": round((video.get("collects") or 0) / likes, 3) if likes else None,
        "creator": {k: creator.get(k) for k in ("fan_increment", "avg_view_second", "completion_rate_5s", "bounce_rate_2s", "homepage_visit_count")} if creator else None,
        "series": series[-30:],
        "milestones": milestones,
        "has_report": has_report,
        "suggest_teardown": bool(hours is not None and hours >= TEARDOWN_AFTER_HOURS and not has_report),
    }


def sync_is_stale(last_synced_at: str | None, now: datetime | None = None) -> bool:
    at = parse_time(last_synced_at)
    return at is None or (now or datetime.now(timezone.utc)) - at > timedelta(hours=STALE_SYNC_HOURS)
