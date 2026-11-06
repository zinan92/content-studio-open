from __future__ import annotations

from datetime import date

import pytest

from content_studio import reach


def test_daily_views_counts_gains_per_video_per_day() -> None:
    today = date(2026, 9, 19)
    snaps = [
        {"video_id": "a", "fetched_at": "2026-09-17T09:30:00", "views": 1000, "published_at": "2026-09-16T20:00:00"},  # published yesterday: first snapshot counts
        {"video_id": "old", "fetched_at": "2026-09-17T09:30:00", "views": 90000, "published_at": "2026-03-01T00:00:00"},  # baseline only
        {"video_id": "old", "fetched_at": "2026-09-18T09:30:00", "views": 90010},
        {"video_id": "a", "fetched_at": "2026-09-18T09:30:00", "views": 1300},
        {"video_id": "a", "fetched_at": "2026-09-18T20:00:00", "views": 1400},  # last of the day wins
        {"video_id": "a", "fetched_at": "2026-09-19T09:30:00", "views": 1350},  # a drop never goes negative
        {"video_id": "b", "fetched_at": "2026-09-19T09:30:00", "views": 50},
        {"video_id": "c", "fetched_at": "2026-09-19T09:30:00", "views": None},
    ]
    got = reach.daily_views(snaps, 3, today)
    assert got == {"2026-09-17": 1000, "2026-09-18": 410, "2026-09-19": 50}


def test_summary_adds_platforms_and_projects_the_pace() -> None:
    today = date(2026, 9, 19)
    totals = {"2026-09-18": {"douyin": 400, "x": 100}, "2026-09-19": {"douyin": 50}}
    s = reach.summary(totals, today)
    assert [d["total"] for d in s["days"]] == [500, 50]
    assert s["today"] == 50 and s["avg7"] == 275 and s["pace30"] == 275 * 30
    assert reach.PLATFORMS[0] == ("douyin", "抖音", True) and "xiaoyuzhou" in reach.PLATFORM_KEYS


@pytest.fixture
def beijing(monkeypatch: pytest.MonkeyPatch):
    """钉在北京时间：CI 跑在 UTC 上，新旧两种分天法在 UTC 里一模一样，不钉住测不出来。"""
    import time

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_a_reading_after_local_midnight_counts_for_the_new_day(beijing) -> None:
    """10/3 作者：「概览晚上 12 点就归零」。一天是北京时间 0 点到 24 点：
    凌晨 1 点（UTC 前一天 17 点）的读数算新的一天，不再记到前一天。"""
    rows = [
        {"video_id": "v", "fetched_at": "2026-10-01T15:00:00+00:00", "views": 100, "published_at": "2026-09-01T00:00:00+00:00"},  # 10/1 23:00
        {"video_id": "v", "fetched_at": "2026-10-02T17:00:00+00:00", "views": 150, "published_at": "2026-09-01T00:00:00+00:00"},  # 10/3 01:00
    ]
    out = reach.daily_views(rows, 3, date(2026, 10, 3))
    assert out == {"2026-10-01": 0, "2026-10-02": 25, "2026-10-03": 25}  # 10/2 没读到：涨的 50 平摊回 10/2、10/3（10/12）
    assert reach.local_day("2026-10-02T17:00:00+00:00") == "2026-10-03"
    assert reach.local_day("2026-10-02T09:30:00") == "2026-10-02"  # 没带时区：按字面
    assert reach.utc_bound(date(2026, 10, 3)) == "2026-10-02T16:00:00+00:00"



def test_gains_after_missed_days_are_spread_back_not_dumped_on_one_day() -> None:
    """10/12 作者：「X 19 万触达数据有问题，昨天 impressions 只有一万多」——老帖几天没读到，再读到时涨的全记在那一天了。"""
    rows = [{"video_id": "p", "fetched_at": f"2026-10-0{d}T12:00:00+08:00", "views": v, "published_at": "2026-10-05T10:00:00+08:00"}
            for d, v in ((6, 40000), (9, 160000))]
    out = reach.daily_views(rows, 5, date(2026, 10, 9))
    assert out == {"2026-10-05": 0, "2026-10-06": 40000, "2026-10-07": 40000, "2026-10-08": 40000, "2026-10-09": 40000}
