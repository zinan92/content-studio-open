"""日结：每天收尾把概览冻结存档（10/3 作者）。"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from content_studio import dayclose
from test_web import client  # noqa: F401 - fixture


def test_plan_picks_tonight_until_close_time_then_tomorrow() -> None:
    tz = timezone(timedelta(hours=8))
    run_at, target = dayclose.plan(datetime(2026, 10, 3, 22, 19, tzinfo=tz))
    assert (run_at, target) == (datetime(2026, 10, 3, 23, 55, tzinfo=tz), date(2026, 10, 3))
    run_at, target = dayclose.plan(datetime(2026, 10, 3, 23, 56, tzinfo=tz))
    assert target == date(2026, 10, 4) and run_at == datetime(2026, 10, 4, 23, 55, tzinfo=tz)
    # Mac 睡过了半夜才醒：要收的还是排的时候那一天，不读（读数会算到新的一天），补存
    assert dayclose.on_time(datetime(2026, 10, 3, 23, 55, 30, tzinfo=tz), date(2026, 10, 3))
    assert not dayclose.on_time(datetime(2026, 10, 4, 0, 30, tzinfo=tz), date(2026, 10, 3))
    assert dayclose.kind_for(date(2026, 9, 20), date(2026, 10, 5)) == "rebuilt"
    assert dayclose.kind_for(date(2026, 10, 4), date(2026, 10, 5)) == "late"


def _at(day: date, hour: int) -> str:
    return datetime.combine(day, time(hour)).astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")


def test_missed_days_are_frozen_once_and_never_rewritten(client) -> None:
    store = client.app.state.store
    today = date.today()
    d3, d2, d1 = (today - timedelta(days=i) for i in (3, 2, 1))
    old = "2026-01-01T00:00:00+00:00"
    for day, views in ((d3, 100), (d2, 160), (d1, 200)):
        store.add_post_snapshots("x", [{"post_id": "1", "views": views, "published_at": old}], _at(day, 12))

    assert client.post("/api/day-close/catch-up").json() == {"made": 3}
    listed = client.get("/api/day-close").json()["days"]
    assert [d["day"] for d in listed] == [d1.isoformat(), d2.isoformat(), d3.isoformat()]
    assert [d["total"] for d in listed] == [40, 60, 0]  # 第一次读只当基准
    snap = client.get(f"/api/day-close/{d2.isoformat()}").json()
    assert snap["reach"]["by_platform"] == {"x": 60} and snap["last_reading"] == {"x": "12:00"}
    assert snap["matrix"] is None and snap["kind"] == dayclose.kind_for(d2, today)  # 补存 / 重算不存各平台累计
    home = Path(os.environ["CONTENT_STUDIO_HOME"])
    assert json.loads((home / "day-close" / f"{d2.isoformat()}.json").read_text(encoding="utf-8"))["reach"]["total"] == 60

    # 存过的不改：那天后来又多出一次读数，日结还是当时的
    store.add_post_snapshots("x", [{"post_id": "1", "views": 999, "published_at": old}], _at(d1, 13))
    assert client.post("/api/day-close/catch-up").json() == {"made": 0}
    assert client.get(f"/api/day-close/{d1.isoformat()}").json()["reach"]["total"] == 40
    # 今天还没过完，不冻结
    assert client.get(f"/api/day-close/{today.isoformat()}").status_code == 404


def test_a_day_frozen_at_close_time_keeps_the_per_platform_totals_and_the_score(client) -> None:
    from tests.test_web import SEC, _wait_sync

    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    today = date.today()
    assert client.app.state.freeze_day(today, "live") is True
    assert client.app.state.freeze_day(today, "live") is False  # 一天只存一次
    snap = client.get(f"/api/day-close/{today.isoformat()}").json()
    assert snap["kind"] == "live" and snap["kind_label"] == "当天收尾时存的"
    assert snap["matrix"] and snap["matrix"]["rows"]  # 当天收尾才有的：每条内容在各平台的累计
    assert "douyin" in snap["last_reading"] and snap["kpi"] is not None and "ship" in snap["kpi"]
