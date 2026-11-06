"""Shooting streak: consecutive days 作者 shot or published a video."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def _day(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    return parsed.astimezone().date().isoformat() if parsed.tzinfo else parsed.date().isoformat()


def shooting_streak(today: date, shot_days: set[str]) -> dict[str, Any]:
    """Consecutive days with a shoot or a published video, counting back from today (or yesterday if today is still open)."""
    today_done = today.isoformat() in shot_days
    cursor = today if today_done else today - timedelta(days=1)
    days = 0
    while cursor.isoformat() in shot_days:
        days += 1
        cursor -= timedelta(days=1)
    last = max((d for d in shot_days if d <= today.isoformat()), default=None)
    gap = (today - date.fromisoformat(last)).days if last else None
    return {"days": days, "today_done": today_done, "broken": not today_done and days == 0, "last_day": last, "days_since_last": gap}
