"""全网粉丝和两个预期数（10/5 作者：「I can see the results, I can see it happen」）。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from content_studio import followers
from tests.test_web import client  # noqa: F401 - fixture


def _rows(*rows: tuple[str, str, int]) -> list[dict]:
    return [{"day": d, "platform": p, "followers": n} for d, p, n in sorted(rows)]


def test_month_end_is_now_plus_two_week_rate_times_days_left() -> None:
    rows = _rows(("2026-09-21", "douyin", 6455), ("2026-09-29", "douyin", 6623), ("2026-10-05", "douyin", 6797))
    s = followers.summary(rows, date(2026, 10, 5))
    assert [p["day"] for p in s["points"]] == ["2026-09-21", "2026-09-29", "2026-10-05"]
    assert s["latest"] == 6797
    assert s["rate"] == pytest.approx((6797 - 6455) / 14, abs=0.1)
    assert s["month_end"] == round(6797 + (6797 - 6455) / 14 * 26)  # 10/5 到 10/31 还剩 26 天


def test_a_platform_that_started_late_is_drawn_flat_and_not_given_a_rate() -> None:
    rows = _rows(("2026-09-21", "douyin", 6455), ("2026-10-05", "douyin", 6797), ("2026-10-05", "x", 600))
    s = followers.summary(rows, date(2026, 10, 5))
    assert s["points"][0]["total"] == 6455 + 600  # X 10/5 才开始记，之前按它第一次的数画平
    assert s["late"] == ["X"] and s["pending"] == ["X"]  # 只记了一天，不算它涨多快
    assert s["month_end"] == round(6797 + 600 + (6797 - 6455) / 14 * 26)


def test_no_readings_means_no_numbers_not_zero() -> None:
    s = followers.summary([], date(2026, 10, 5))
    assert s["latest"] is None and s["month_end"] is None and s["points"] == []


def test_expected_month_reach_uses_finished_days_only() -> None:
    days = {"2026-09-28": 100, "2026-09-29": 100, "2026-09-30": 100, "2026-10-01": 200, "2026-10-02": 200,
            "2026-10-03": 300, "2026-10-04": 400, "2026-10-05": 5}  # 今天早上的半截数不算
    m = followers.month_reach(days, date(2026, 10, 5))
    assert m["so_far"] == 200 + 200 + 300 + 400
    assert m["avg7"] == round((100 * 3 + 200 + 200 + 300 + 400) / 7)
    assert m["left"] == 27 and m["expected"] == m["so_far"] + m["avg7"] * 27


def test_sync_records_douyin_from_my_account_and_survives_a_failing_platform(tmp_path) -> None:
    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "s.sqlite3")
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="active", is_self=True)
    store.update_account(me["id"], follower_count=6797, last_synced_at="2026-10-05T01:30:51+00:00")

    def broken() -> int:
        raise followers.FollowersError("B站 登录过期")

    out = followers.sync(store, date(2026, 10, 5), {"x": lambda: 600, "bilibili": broken})
    assert out["douyin"] == 6797 and out["x"] == 600 and out["bilibili"].startswith("error")
    assert {(r["platform"], r["followers"]) for r in store.follower_counts()} == {("douyin", 6797), ("x", 600)}


def test_results_endpoint_and_manual_platforms(client: TestClient) -> None:  # noqa: F811
    r = client.get("/api/today/results").json()
    assert set(r) >= {"reach", "followers", "labels"}
    assert set(r["reach"]["month"]) >= {"expected", "so_far", "avg7", "left"}
    assert {m["key"] for m in r["followers"]["manual"]} == set(followers.MANUAL)
    assert all(d["day"] < date.today().isoformat() for d in r["reach"]["days"])  # 今天没过完，不画

    r = client.put("/api/followers", json={"platform": "xiaohongshu", "followers": 1200}).json()
    assert r["followers"]["latest"] == 1200
    assert next(m for m in r["followers"]["manual"] if m["key"] == "xiaohongshu")["value"] == 1200
    assert client.put("/api/followers", json={"platform": "douyin", "followers": 1}).status_code >= 400  # 自动读的不让手填


def test_wendy_brief_no_longer_chases_dms_or_x_replies(client: TestClient) -> None:  # noqa: F811
    from content_studio.extras.team import wendy

    today = client.get("/api/today").json()
    text = wendy.brief(today, client.get("/api/reach").json(), None)
    assert "X 互动" not in text and "- 回私信" not in text  # 回私信不再单独算一项
    # 10/9 作者：加回第二项变现动作（回私信是做到它的一种）
    assert [k for k, _ in wendy.KPI] == ["ship", "mn"]


def test_douyin_is_not_recorded_when_it_did_not_sync_today(tmp_path) -> None:
    """cookies 过期那天账号表里是昨天的数：不能记成今天的，不然线被拉平、速度变 0。"""
    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "s.sqlite3")
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="active", is_self=True)
    store.update_account(me["id"], follower_count=6797, last_synced_at="2026-10-04T01:30:51+00:00")
    assert "douyin" not in followers.sync(store, date(2026, 10, 5), {})
    assert store.follower_counts() == []


def test_wendy_now_never_points_at_the_unscored_tasks(client: TestClient) -> None:  # noqa: F811
    now = client.get("/api/wendy").json().get("now") or {}
    assert now.get("row") not in ("rd", "dm", "xr")
    assert not any(w in (now.get("text") or "") for w in ("读日报", "回私信", "X 互动"))
