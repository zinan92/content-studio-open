"""变现（10/9 作者 在变现流程板上定的）：每天一个变现动作算分，没做减 1 分；收入是结果，记在账本里，今天页一张卡。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from content_studio import driver
from content_studio.extras.consults import consult
from tests.test_web import client  # noqa: F401 - fixture


def test_money_action_is_scored_from_its_start_day_and_never_before() -> None:
    days = driver.kpi_range(date(2026, 10, 8), date(2026, 10, 13), date(2026, 10, 12), posted={"2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12"},
                            dms={}, started="2026-09-29", money={"2026-10-10"}, money_started="2026-10-10")
    assert [d["mn"] for d in days] == ["n/a", "n/a", "ok", "miss", "pending", "future"]
    # 出摊都做到了，只有 10/11 没做变现动作：减 1 分；今天还没过完不算
    assert driver.demerits(days) == 1


def test_without_money_data_nothing_is_scored() -> None:
    days = driver.kpi_days(date(2026, 10, 12), posted=set(), dms={}, started="2026-09-29")
    assert {d["mn"] for d in days} == {"n/a"}


def test_month_money_adds_up_by_source_and_projects_the_month_end() -> None:
    rows = [{"day": "2026-10-05", "amount": 1000, "source": "consult"},
            {"day": "2026-10-08", "amount": 19.9, "source": "p3"},
            {"day": "2026-09-30", "amount": 500, "source": "consult"}]  # 上个月的不算
    m = driver.month_money(rows, date(2026, 10, 10), target=10000, labels={"consult": "咨询", "p3": "天机"})
    assert m["total"] == pytest.approx(1019.9)
    assert m["target"] == 10000 and m["month"] == 10
    assert [(s["label"], s["amount"]) for s in m["by_source"]] == [("咨询", 1000), ("天机", 19.9)]
    # 照这个月到今天的速度：1019.9 / 10 天 × 31 天
    assert m["expected"] == round(1019.9 / 10 * 31)


def _today_money(client: TestClient) -> str:  # noqa: F811
    return client.get("/api/today").json()["days"][-1]["mn"]


@pytest.fixture
def scored(client: TestClient) -> TestClient:  # noqa: F811
    """把变现动作的起算日拨到一周前，今天就在算分范围里。"""
    store = client.app.state.store
    kpi = store.settings()["kpi"]
    store.update_settings({"kpi": {**kpi, "money_started": (date.today() - timedelta(days=7)).isoformat(), "money_ended": "9999"}})
    return client


def test_a_money_action_needs_a_line_saying_what_was_done(scored: TestClient) -> None:
    assert _today_money(scored) == "pending"
    assert scored.post("/api/today/money", json={"note": "  "}).status_code == 400
    assert scored.post("/api/today/money", json={"note": "给张三发了方案报价"}).json()["ok"] is True
    assert _today_money(scored) == "ok"
    home = scored.get("/api/today/home").json()
    assert home["money"]["action"] == {"done": True, "how": ["给张三发了方案报价"]}


def test_recording_income_counts_as_the_money_action(scored: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    today = date.today().isoformat()
    assert scored.post("/api/revenue", json={"day": today, "amount": 0, "source": "consult"}).status_code == 400
    row = scored.post("/api/revenue", json={"day": today, "amount": 1000, "source": "consult", "note": "45 分钟咨询"}).json()
    assert row["amount"] == 1000 and row["source"] == "consult"
    assert _today_money(scored) == "ok"
    money = scored.get("/api/today/home").json()["money"]
    assert money["total"] == 1000 and money["target"] == 10000
    assert money["by_source"] == [{"key": "consult", "label": "咨询", "amount": 1000}]
    assert any(s["key"] == "consult" for s in money["sources"])
    assert "收了 ¥1,000（咨询）" in money["action"]["how"]
    # 记错了能删，删了就不算
    assert scored.delete(f"/api/revenue/{row['id']}").json()["ok"] is True
    assert scored.get("/api/today/home").json()["money"]["total"] == 0
    assert _today_money(scored) == "pending"


def test_replying_to_dms_counts_as_the_money_action(scored: TestClient) -> None:
    store = scored.app.state.store
    store.set_dm(date.today().isoformat(), 3, 0)
    assert _today_money(scored) == "pending"  # 收到了没回，不算
    store.set_dm(date.today().isoformat(), 3, 2)
    assert _today_money(scored) == "ok"


def test_wendy_tells_him_about_the_money_action_and_the_month(scored: TestClient) -> None:
    from content_studio.extras.team import wendy

    text = wendy.brief(scored.get("/api/today").json(), scored.get("/api/reach").json(), None)
    assert "变现动作（算分，没做减 1 分）：还没做" in text
    assert "[本月收入]" in text and "目标 ¥10,000" in text and "还没记过一笔" in text
