from __future__ import annotations

from datetime import date

DAY = date(2026, 9, 14)


def test_shooting_streak_counts_back_and_flags_a_broken_chain() -> None:
    from content_studio.today import shooting_streak

    days = {"2026-09-12", "2026-09-13", "2026-09-14"}
    assert shooting_streak(DAY, days) == {"days": 3, "today_done": True, "broken": False, "last_day": "2026-09-14", "days_since_last": 0}
    open_today = shooting_streak(date(2026, 9, 15), days)
    assert open_today["days"] == 3 and not open_today["broken"]
    broken = shooting_streak(date(2026, 9, 17), days)
    assert broken["days"] == 0 and broken["broken"] and broken["days_since_last"] == 3
    assert shooting_streak(DAY, set())["last_day"] is None
