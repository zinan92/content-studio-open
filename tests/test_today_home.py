"""「今天」下半页（10/5 作者：「空荡荡」「我今天明明完成了任务，也没有地方可以点」）：
今天这一条、本月咨询几单、接下来 3 条备好没有；「我发了」= 马上同步一次自己的抖音号，看到了才算。"""
from __future__ import annotations

from datetime import date
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import web
from content_studio.extras.consults import consult
from tests.test_web import client  # noqa: F401 - fixture


def _video(store, me, day: str) -> None:
    store.upsert_videos(me["id"], [{"platform": "抖音", "video_id": "v-today", "title": "今天这条", "published_at": f"{day}T10:00:00+08:00",
                                    "duration_seconds": 120, "is_top": 0, "is_image_post": 0, "likes": 1, "comments": 0, "shares": 0, "collects": 0, "views": 10}])


def _wait_check(client: TestClient) -> dict:  # noqa: F811
    for _ in range(50):
        h = client.get("/api/today/home").json()
        if (h.get("check") or {}).get("state") != "running":
            return h
        time.sleep(0.05)
    raise AssertionError("核对一直没跑完")


def test_home_lists_today_upcoming_and_consults(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    for text in ("第二条", "第三条"):  # 旧「接下来要拍的」清单：10/19 拿掉排期后不再往后排
        client.post("/api/today/notes", json={"text": text})
    assert client.get("/api/today/home").json()["focus"] is None  # 没有正在做的：不拿清单第一条顶上
    first = client.post("/api/topics", json={"title": "第一条", "formats": "video"}).json()
    client.post(f"/api/topics/{first['id']}/focus").raise_for_status()
    h = client.get("/api/today/home").json()
    assert h["focus"]["title"] == "第一条" and h["focus"]["shipped"] is False
    assert h["focus"]["steps"][0] == "骨架" and h["focus"]["steps"][-1] == "发出"
    assert h["upcoming"] == []  # 只有正在做的那一条
    assert h["consults"]["count"] == 0 and h["consults"]["latest"] is None
    assert h["check"] is None


def test_i_shipped_syncs_my_douyin_and_only_counts_what_it_sees(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    store = client.app.state.store
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)
    first = client.post("/api/topics", json={"title": "第一条", "formats": "video"}).json()
    client.post(f"/api/topics/{first['id']}/focus").raise_for_status()
    seen = {"video": False}

    def fake_sync(st, account_id, *, client_factory, pages=None):
        assert account_id == me["id"]
        if seen["video"]:
            _video(st, me, date.today().isoformat())
        return {"video_count": 1}

    monkeypatch.setattr(web, "sync_account", fake_sync)
    # 抖音上还没有：核对完说没看到，不打勾
    assert client.post("/api/today/check-shipped").json()["started"] is True
    h = _wait_check(client)
    assert h["check"]["state"] == "done" and h["focus"]["shipped"] is False
    # 两分钟内再点：不重复去抖音
    assert client.post("/api/today/check-shipped").json()["started"] is False


def test_i_shipped_turns_today_green_once_douyin_has_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    store = client.app.state.store
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)

    def fake_sync(st, account_id, *, client_factory, pages=None):
        _video(st, me, date.today().isoformat())
        return {"video_count": 1}

    monkeypatch.setattr(web, "sync_account", fake_sync)
    client.post("/api/today/check-shipped")
    h = _wait_check(client)
    assert h["focus"]["shipped"] is True and h["focus"]["step"] == len(h["focus"]["steps"]) - 1
    month = client.get("/api/today/month").json()
    cell = next(c for w in month["weeks"] for c in w["days"] if c["day"] == date.today().isoformat())
    assert cell["ship"] == "ok"  # 月历今天那格变绿


def test_a_failed_check_says_why_and_can_be_retried(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    store = client.app.state.store
    store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)

    def broken(*_a, **_kw):
        raise RuntimeError("抖音登录过期了")

    monkeypatch.setattr(web, "sync_account", broken)
    client.post("/api/today/check-shipped")
    h = _wait_check(client)
    assert h["check"]["state"] == "failed" and "登录过期" in h["check"]["error"]
    assert client.post("/api/today/check-shipped").json()["started"] is True  # 失败了马上能再点


def test_today_page_draws_the_new_blocks() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/content_studio/static/today.js").read_text(encoding="utf-8")
    # 10/13：战况就是首页。「今天这一条」、三行 KPI、今天页那段 Wendy 都拿掉；钱的动作收进收入那张卡
    assert "dailyReviewBlock(TD.review)" in js and "moneyBook(TD.home)" in js and "moneyAsk(k)" in js and "kpiTargets(k.targets)" in js
    assert not any(f"function {name}(" in js for name in ("todayOneBlock", "todayWendyBlock", "kpiStrip", "todayMoneyCard", "bindTodayHome", "todayNextBlock", "todayMoneyAction"))


def test_fupan_is_one_page_with_the_sheet_and_douyin_analysis() -> None:
    """10/19 作者：「战况和汇总放到一起，改名叫复盘……抖音作品分析 subtab 可以保留」「核心是要 simplify」。"""
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    index = (static / "index.html").read_text(encoding="utf-8")
    app = (static / "app.js").read_text(encoding="utf-8")
    out = (static / "output.js").read_text(encoding="utf-8")
    today = (static / "today.js").read_text(encoding="utf-8")
    rail = index.split('id="nav"')[1].split("</nav>")[0]
    assert '<i class="zx-k">盘</i>复盘</span>' in rail and "战况" not in rail and "汇总" not in rail and 'data-view="summary"' not in rail
    assert 'id="v-summary"' not in index and 'id="summaryBody"' not in index
    # 顺序：上面的卡 → 每条内容 × 每个平台 → 改目标
    assert index.index('id="todayBody"') < index.index('id="fupanTable"') < index.index('id="todayTargets"')
    assert "out: [['today', '复盘'], ['plats', '各平台'], ['mine', '抖音作品分析']]" in app  # 10/20 平台的数据归「盘」
    assert "summary: 'today'" in app and "weekly: 'today'" in app and "backfill: 'today'" in app
    # 汇总上半（触达、往日、这周复盘、倍数图）和 Wendy 里的抖音小表都拿掉了
    for gone in ("function reachBlock(", "function pastBlock(", "function reviewBlock(", "function multipleChart(", "VIEWS.summary"):
        assert gone not in out, gone
    assert "function rvDouyinTable(" not in today and "window.renderFupanTable" in today
    assert "function sheetBlock(" in out and "window.renderFupanTable = " in out
