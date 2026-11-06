"""战况的算法（kpi_board.py）：目标是 作者 拍板的，转化率是算出来的，要多少播放 = 每天要涨的粉 ÷ 转化率。"""
from __future__ import annotations

from datetime import date, timedelta

from content_studio import kpi_board

TODAY = date(2026, 10, 12)
TARGETS = {"douyin": {"start_day": "2026-10-12", "start": 8000, "end_day": "2026-10-31", "end": 20000},
           "x": {"start_day": "2026-10-11", "start": 2500, "end_day": "2026-10-31", "end": 10000}, "x_impressions": 200000}


def _days(n: int, *, start: int, per_day: int, platform: str) -> list[dict]:
    """从 n 天前到今天，每天一行（今天是早上的读数）。"""
    return [{"day": (TODAY - timedelta(days=n - i)).isoformat(), "platform": platform, "followers": start + per_day * i} for i in range(n + 1)]


def test_need_per_day_rate_and_forecast_come_from_the_readings() -> None:
    rows = _days(14, start=6000, per_day=200, platform="douyin")  # 今天 8800
    views = {(TODAY - timedelta(days=i)).isoformat(): {"douyin": 20000} for i in range(1, 15)}
    board = kpi_board.build(today=TODAY, followers=rows, views=views, targets=TARGETS)
    dy = board["kpis"][0]
    assert dy["now"] == 8800 and dy["days_left"] == 19
    assert dy["need_per_day"] == 590  # (20000 - 8800) / 19 向上取整
    assert dy["rate"] == 200.0 and dy["forecast"] == 8800 + 200 * 19
    assert dy["expected"] == 8000 and not dy["ok"]  # 起点那天在线上，但照这个速度（8800 + 200 × 19）到不了 2 万：落后
    # 转化：14 天涨 2600（第 1 天前一天到昨天），播放 14 × 2 万
    conv = dy["tree"]["conv"]
    assert conv["fans"] == 200 * 13 and conv["views"] == 20000 * 13 and conv["per_1k"] == round(2600 / 260000 * 1000, 1)
    assert dy["tree"]["views_need"] == round(dy["need_per_day"] / conv["per_1k"] * 1000)
    assert dy["tree"]["views_avg"] == 20000


def test_behind_says_how_many_times_and_that_posting_comes_first() -> None:
    rows = _days(10, start=7000, per_day=100, platform="douyin")
    views = {(TODAY - timedelta(days=i)).isoformat(): {"douyin": 15000} for i in range(1, 11)}
    vids = [{"video_id": "a", "published_at": "2026-10-08T03:46:00+00:00", "views": 7785}]
    board = kpi_board.build(today=TODAY, followers=rows, views=views, targets=TARGETS, videos=vids,
                            creator={"a": {"view_count": 7785, "bounce_rate_2s": 0.44, "completion_rate_5s": 0.3, "homepage_visit_count": 638, "fan_increment": 50}})
    dy = board["kpis"][0]
    assert dy["forecast"] < dy["end"] and dy["times"] == round(dy["need_per_day"] / 100, 1)
    assert "差" in dy["say"] and "先补条数" in dy["say"] and "每天 1 条不商量" in dy["say"]
    t = dy["tree"]
    assert t["posted_7"] == 1 and t["posted_days_7"] == 1 and t["days_since_post"] == 4
    assert t["bounce_2s"] == 0.44 and round(t["profile_rate"], 3) == round(638 / 7785, 3) and round(t["fans_per_1k"], 1) == round(50 / 7785 * 1000, 1)


def test_x_uses_the_hourly_reading_when_newer() -> None:
    rows = _days(8, start=2000, per_day=50, platform="x")
    board = kpi_board.build(today=TODAY, followers=rows, views={}, targets=TARGETS, x_now=2867)
    x = board["kpis"][1]
    assert x["now"] == 2867 and x["tree"]["conv"] is None and x["tree"]["views_target"] == 200000


def test_no_readings_does_not_invent_a_speed() -> None:
    board = kpi_board.build(today=TODAY, followers=[], views={}, targets=TARGETS)
    dy = board["kpis"][0]
    assert dy["now"] is None and dy["rate"] is None and dy["forecast"] is None and dy["say"] == "抖音还没有读数。"


def test_money_asks_every_three_days() -> None:
    money = {"total": 3000.0, "target": 20000.0, "expected": 7750, "month": 10}
    ask = lambda notes: kpi_board.build(today=TODAY, followers=[], views={}, targets=TARGETS, money=money, money_notes=notes)["money"]
    assert ask([])["ask"]  # 从没问过：今天问
    assert not ask([{"day": "2026-10-10", "note": "张三问了价"}])["ask"]
    m = ask([{"day": "2026-10-09", "note": "没有"}])
    assert m["ask"] and m["last_note"]["note"] == "没有"
    assert m["need_per_day"] == round(17000 / 20) and not m["ok"]


def test_brief_text_has_the_same_numbers() -> None:
    rows = _days(14, start=6000, per_day=200, platform="douyin")
    board = kpi_board.build(today=TODAY, followers=rows, views={}, targets=TARGETS, money={"total": 0.0, "target": 20000.0, "expected": 0, "month": 10})
    text = kpi_board.brief_text(board)
    assert text.startswith("[战况]") and "抖音粉丝：现在 8800" in text and "2026-10-31 前 20,000" in text and "今天问一次" in text


from tests.test_web import client  # noqa: E402,F401 - fixture


def test_kpi_api_targets_and_the_money_question(client) -> None:  # noqa: F811
    """战况接口：默认目标是示例值；改目标只改终点；今天页问收入点、答了 3 天内不再问；Wendy 的账里有同一份战况。"""
    d = client.get("/api/kpi").json()
    assert d["targets"]["douyin"]["end"] == 1000 and d["targets"]["x"]["end"] == 1000
    assert d["targets"]["x_impressions"] == 200000 and d["targets"]["revenue"] == 10000
    assert [k["key"] for k in d["kpis"]] == ["douyin", "x"] and d["money"]["ask"]
    r = client.put("/api/kpi/targets", json={"douyin_end": 25000, "douyin_end_day": "2026-11-15", "revenue": 30000})
    assert r.status_code == 200
    t = r.json()["targets"]
    assert t["douyin"] == {"start_day": "2026-01-01", "start": 0, "end_day": "2026-11-15", "end": 25000} and t["revenue"] == 30000
    assert client.put("/api/kpi/targets", json={"douyin_end_day": "2025-12-01"}).status_code == 400  # 终点早于起点
    assert client.put("/api/kpi/targets", json={"revenue": -1}).status_code == 400
    assert client.post("/api/today/money", json={"note": "这 3 天没有新的收入点"}).status_code == 200
    m = client.get("/api/kpi").json()["money"]
    assert not m["ask"] and m["last_note"]["note"] == "这 3 天没有新的收入点"
    assert "[战况]" in client.get("/api/wendy/brief").json()["text"]
