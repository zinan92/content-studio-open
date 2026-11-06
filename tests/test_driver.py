"""「今天」驱动页：KPI 怎么记分、一次只给哪一件（9/29 作者 拍板的顺序）。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from content_studio import driver
from content_studio.extras.consults import consult
from tests.test_web import client  # noqa: F401 - fixture


def test_kpi_days_scores_only_what_he_controls_and_never_before_the_start() -> None:
    today = date(2026, 9, 29)
    days = driver.kpi_days(today, posted={"2026-09-24", "2026-09-29"},
                           dms={"2026-09-29": {"received": 3, "replied": 3}}, started="2026-09-29",
                           x_replies={"2026-09-29": 20}, x_target=20)
    assert [d["day"] for d in days] == [f"2026-09-{n}" for n in range(23, 30)]
    assert [d["ship"] for d in days] == ["miss", "ok", "miss", "miss", "miss", "miss", "ok"]
    # 私信、X 回复从 KPI 开始那天才算，之前没记过，不倒扣
    assert [d["dm"] for d in days[:-1]] == ["n/a"] * 6 and days[-1]["dm"] == "ok"
    assert [d["xr"] for d in days[:-1]] == ["n/a"] * 6 and days[-1]["xr"] == "ok"
    assert driver.demerits(days) == 5


def test_today_is_pending_not_a_miss_until_it_is_over() -> None:
    days = driver.kpi_days(date(2026, 10, 1), posted=set(), dms={"2026-09-30": {"received": 4, "replied": 2}}, started="2026-09-29",
                           x_replies={"2026-09-30": 12}, x_target=20)
    assert days[-1]["ship"] == "pending" and days[-1]["dm"] == "pending" and days[-1]["xr"] == "pending"
    by_day = {d["day"]: d for d in days}
    assert by_day["2026-09-30"]["dm"] == "miss"  # 没回完
    assert by_day["2026-09-30"]["xr"] == "miss"  # 12 < 20
    assert by_day["2026-09-29"]["dm"] == "miss"  # 没填
    assert driver.demerits(days) == 6  # 10/5 起只有没出摊减分；私信、X 回复照样记，不算分


def test_order_follows_the_ladder_and_drops_skipped_and_done() -> None:
    items = [
        driver.item("wrap", "reach", "填数"),
        driver.item("dm", "dm", "回私信"),
        driver.item("ship", "ship", "拍"),
        driver.item("client", "c1", "发 PDF"),
        driver.item("blocker", "cookies", "登录过期"),
        driver.item("tomorrow", "tm", "明天出摊"),
    ]
    got = driver.order(items, skipped={"cookies"}, done={"c1"})
    assert [i["key"] for i in got] == ["ship", "dm", "tm", "reach"]
    assert got[0]["rung_label"] == "出摊"


def _today(client: TestClient) -> dict:
    return client.get("/api/today").json()


def test_today_is_three_things_and_only_do_this_one_starts_a_topic(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/19 作者 拿掉排期：「接下来要拍的」旧清单不再决定下一条；没有正在做的就让他去选题挑一条。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    d = _today(client)
    assert set(d) >= {"first", "ship", "dm", "xr", "days", "demerits"}
    assert d["ship"]["next"]["key"] == "notes:empty" and d["ship"]["next"]["go"] == "input"  # 没有正在做的：去选题挑，不替他挑
    assert [p["form"] for p in d["ship"]["platforms"] if p["key"] in ("douyin", "x")] == ["video", "video"]  # 10/4：X 先发；10/5 起四大平台默认都发视频
    assert d["xr"] == {"count": None, "target": 10}
    client.post("/api/today/notes", json={"text": "内容工作台做完整了，拍出来"})
    d = _today(client)
    assert d["ship"]["next"]["key"] == "notes:empty"  # 旧清单里有一行也不接上
    topic = client.post("/api/topics", json={"title": "接了一单咨询，拍出来", "formats": "video"}).json()
    client.post(f"/api/topics/{topic['id']}/focus").raise_for_status()
    d = _today(client)
    assert d["ship"]["next"]["go"] == f"work/{topic['id']}"  # 接着是这条选题自己的下一步
    assert "写拍摄提纲" in d["ship"]["next"]["text"]


def test_skip_needs_a_reason_and_entries_count_toward_kpis(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert client.post("/api/today/skip", json={"key": "notes:empty", "reason": " "}).status_code == 400
    assert client.post("/api/today/skip", json={"key": "notes:empty", "reason": "今天状态不好"}).status_code == 200
    d = _today(client)
    assert d["ship"]["next"] is None and d["skipped"][0]["reason"] == "今天状态不好"
    assert client.put("/api/today/dm", json={"received": 2, "replied": 3}).status_code == 400
    client.put("/api/today/dm", json={"received": 5, "replied": 2})
    assert _today(client)["dm"]["entry"] == {"received": 5, "replied": 2}
    client.put("/api/today/dm", json={"received": 5, "replied": 5})
    client.put("/api/today/x-replies", json={"value": 20})
    d = _today(client)
    assert d["days"][-1]["dm"] == "ok" and d["days"][-1]["xr"] == "ok" and d["xr"]["count"] == 20
    assert client.put("/api/today/x-replies", json={"value": -1}).status_code == 400


def test_note_order_moves_and_suggestion_only_comes_from_his_pool(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    a = client.post("/api/today/notes", json={"text": "A"}).json()["notes"][0]
    client.post("/api/today/notes", json={"text": "B"})
    notes = client.patch(f"/api/today/notes/{a['id']}", json={"move": 1}).json()["notes"]
    assert [n["text"] for n in notes] == ["B", "A"]
    assert client.post("/api/today/suggest").status_code == 400  # 选题池空：不编新选题


def test_weekly_review_prompt_puts_the_demerits_and_repeated_excuses_in_front_of_him() -> None:
    from content_studio import review

    kpi = {"posted": 2, "dm_missed": 1, "demerits": 6, "skips": [{"day": "2026-10-01", "what": "ship", "reason": "没灵感"}, {"day": "2026-10-02", "what": "ship", "reason": "没灵感"}]}
    inputs = {"week": "2026-W40", "since": "2026-09-26", "until": "2026-10-03", "videos": [], "median_likes": 100, "topics_done": [], "breakouts": [], "kpi": kpi}
    prompt = review.build_prompt(inputs)
    assert "一共减 6 分" in prompt and prompt.count("理由：没灵感") == 2
    # 说执行分的那条没有视频可引，video_ids 给空也算过
    raw = {"summary": "s", "wins": [], "problems": [{"text": "减了 6 分，「没灵感」出现 2 次", "video_ids": []}], "next_week": ["每天出摊"]}
    assert review.validate(raw, inputs) == []
    assert review.validate(raw, {**inputs, "kpi": None}) != []


def test_xiaohongshu_form_is_a_setting_that_changes_pack_and_today(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """给客户选发什么：小红书默认发视频；设置里改成图文，打包多一步、今天那行分到「发图文」。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    r = client.get("/api/reach").json()
    xhs = next(p for p in r["platforms"] if p["key"] == "xiaohongshu")
    # 10/5：四大平台都能选视频 / 图文 / 文字，默认都是视频；10/7 起 B 站、YouTube 只有视频一格、公众号只有文章一格（勾不勾 = 发不发）
    assert xhs["form"] == "video" and [c["key"] for c in xhs["form_choices"]] == ["video", "cards", "text"]
    assert [c["key"] for c in next(p for p in r["platforms"] if p["key"] == "douyin")["form_choices"]] == ["video", "cards", "text"]
    assert [c["key"] for c in next(p for p in r["platforms"] if p["key"] == "bilibili")["form_choices"]] == ["video"]
    assert next(p for p in r["platforms"] if p["key"] == "xiaoyuzhou")["form_choices"] == []
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "video"
    client.put("/api/settings", json={"platform_accounts": {"xiaohongshu": {"on": True, "handle": "作者", "form": "cards"}}})
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "cards"
    forms = {p["key"]: p["form"] for p in _today(client)["ship"]["platforms"]}
    assert forms["xiaohongshu"] == "cards" and forms["douyin"] == "video"
    # 选了图文，视频的上传文件夹就不给
    topic = client.post("/api/topics", json={"title": "t"}).json()
    assert client.post(f"/api/topics/{topic['id']}/upload-folder", json={"platform": "xiaohongshu"}).status_code == 400
    # 认不出的值按默认
    client.put("/api/settings", json={"platform_accounts": {"xiaohongshu": {"on": True, "handle": "作者", "form": "hologram"}}})
    assert client.get("/api/publish/desk").json()["forms"]["xiaohongshu"] == "video"


def test_each_topic_fixes_its_platform_forms_when_it_starts_and_can_change_them(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/5 作者：每条内容一开始就定好每个平台发什么，也能手动改；改默认不动已经在做的那条。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    for key in ("channels", "xiaohongshu", "x", "wechat_mp", "bilibili", "youtube"):
        client.put(f"/api/platform/{key}/settings", json={"on": True})
    topic = client.post("/api/topics", json={"title": "这一条"}).json()
    got = client.get(f"/api/topics/{topic['id']}/forms").json()["platforms"]
    assert {p["key"]: p["forms"] for p in got} == {"douyin": ["video"], "channels": ["video"], "xiaohongshu": ["video"], "wechat_mp": ["text"],
                                                   "x": ["video"], "bilibili": ["video"], "youtube": ["video"]}
    assert [c["label"] for c in got[0]["choices"]] == ["视频", "图文", "文章"]

    r = client.put(f"/api/topics/{topic['id']}/forms", json={"forms": {"x": "text", "xiaohongshu": "cards"}})
    assert r.status_code == 200 and {p["key"]: p["forms"] for p in r.json()["platforms"]}["x"] == ["text"]
    assert client.get(f"/api/publish/desk?topic_id={topic['id']}").json()["forms"]["xiaohongshu"] == "cards"
    assert client.put(f"/api/topics/{topic['id']}/forms", json={"forms": {"x": "hologram"}}).status_code == 400
    assert client.put(f"/api/topics/{topic['id']}/forms", json={"forms": {"bilibili": "text"}}).status_code == 400
    # 发出去时记下的是这一条定的形式，不是设置里的默认
    recs = client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "x", "published": True, "url": "https://x.com/park/status/1"}).json()
    assert recs["x"]["form"] == "text"

    # 设置里把抖音默认改成文章：新建的那条按新默认，已经在做的这条不变
    client.put("/api/platform/douyin/settings", json={"forms": ["text"]})
    newer = client.post("/api/topics", json={"title": "下一条"}).json()
    assert {p["key"]: p["forms"] for p in client.get(f"/api/topics/{newer['id']}/forms").json()["platforms"]}["douyin"] == ["text"]
    assert {p["key"]: p["forms"] for p in client.get(f"/api/topics/{topic['id']}/forms").json()["platforms"]}["douyin"] == ["video"]


def test_backfill_desk_lists_every_open_cell_and_says_why_the_others_cannot_go(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/1 作者：补发工作台是一张和全平台追踪一样的表，他点格子挑今天发什么。E「整条补发」拿掉了。"""
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert "backfill" not in _today(client)
    assert client.post("/api/today/backfill/999/go").status_code in (404, 405)
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    desk = client.get("/api/backfill/desk").json()
    assert desk["need"] == 4 and desk["planned"] == 0 and desk["run"] == {"items": [], "running": False}
    assert "douyin" not in [p["key"] for p in desk["platforms"]]
    how = {p["key"]: p["how"] for p in desk["platforms"]}
    assert how.get("channels", "hand") == "hand" and how.get("wechat_mp", "draft") == "draft" and how.get("youtube", "auto") == "auto"
    assert desk["rows"]
    cell = next(iter(desk["rows"][0]["cells"].values()))
    assert cell["state"] == "blocked" and "选题" in cell["why"]  # 还没接上选题的：挑不了，说清为什么
    # 挑了发不了的格子：预览和发都拒绝，不排进今天
    pick = {"cells": [{"video_id": desk["rows"][0]["video_id"], "platform": desk["platforms"][0]["key"]}]}
    assert client.post("/api/backfill/desk/preview", json=pick).status_code == 400
    assert client.post("/api/backfill/desk/go", json=pick).status_code == 400
    assert client.post("/api/backfill/desk/go", json={"cells": []}).status_code == 400
    assert client.app.state.store.backfill_plan(date.today().isoformat()) == []
    # 今天排了、还没发的格子：列在「今天在发的」里（重启后也在，能再发、能标发了、能拿掉）
    row = desk["rows"][0]
    plats = [p["key"] for p in desk["platforms"] if row["cells"][p["key"]]["state"] != "sent"]
    client.app.state.store.set_backfill_plan(date.today().isoformat(), [(row["video_id"], plats[0]), (row["video_id"], plats[1])])
    desk = client.get("/api/backfill/desk").json()
    assert [(i["platform"], i["state"], i["sent"]) for i in desk["run"]["items"]] == [(plats[0], "idle", False), (plats[1], "idle", False)]
    assert desk["planned"] == 2 and desk["rows"][0]["cells"][plats[0]]["state"] == "planned"
    assert client.post("/api/backfill/desk/drop", json={"video_id": row["video_id"], "platform": plats[0]}).json() == {"ok": True}
    assert [i["platform"] for i in client.get("/api/backfill/desk").json()["run"]["items"]] == [plats[1]]
    assert client.post("/api/backfill/desk/drop", json={"video_id": row["video_id"], "platform": plats[0]}).status_code == 400
    client.post(f"/api/backfill/{row['video_id']}/mark", json={"platform": plats[1], "done": True})
    assert client.post("/api/backfill/desk/drop", json={"video_id": row["video_id"], "platform": plats[1]}).status_code == 400  # 发出去的拿不掉
    # 他点「发了」记的那一格标着 marked：审核没过可以撤回（页面上给「撤回」）
    item = client.get("/api/backfill/desk").json()["run"]["items"][0]
    assert item["sent"] and item["marked"] and _today(client)["out"]["cells"][0]["marked"]
    client.post(f"/api/backfill/{row['video_id']}/mark", json={"platform": plats[1], "done": False})
    item = client.get("/api/backfill/desk").json()["run"]["items"][0]
    assert not item["sent"] and not item["marked"]


def test_backfill_preview_shows_what_would_go_out(client: TestClient, tmp_path) -> None:
    topic = client.post("/api/topics", json={"title": "旧视频"}).json()
    art = tmp_path / "drafts" / f"topic-{topic['id']}" / "article.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("# 文章标题\n\n第一段。\n\n![图](figs/01.png)\n\n第二段**加粗**。\n", encoding="utf-8")
    client.app.state.store.update_topic(topic["id"], article_path=str(art))
    v = client.get(f"/api/today/backfill/{topic['id']}/preview").json()
    assert v["article_title"] == "文章标题"
    assert v["article_head"] == ["第一段。", "第二段加粗。"]
    assert v["layout_url"].endswith("/wechat-preview.html")


def test_reading_the_dailies_is_scored_from_the_start_day_and_only_when_one_came_out() -> None:
    days = driver.kpi_days(date(2026, 10, 2), posted=set(), dms={}, started="2099-01-01",
                           reads={"2026-09-30": True, "2026-10-01": False, "2026-10-02": False}, read_started="2026-09-30")
    by = {d["day"]: d["rd"] for d in days}
    assert by["2026-09-29"] == "n/a"  # 开始之前不倒扣
    assert by["2026-09-30"] == "ok" and by["2026-10-01"] == "miss" and by["2026-10-02"] == "pending"
    # 那天一份日报都没出（reads 里没有这天）：不算
    days = driver.kpi_days(date(2026, 10, 2), posted=set(), dms={}, started="2099-01-01", reads={}, read_started="2026-09-30")
    assert all(d["rd"] == "n/a" for d in days)


def test_today_lists_both_dailies_and_marks_them_read(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio.extras.dailies import kline_board

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setattr(kline_board, "KLINE_DIR", tmp_path / "kline")
    root = tmp_path / "vault-default"
    today = date.today()
    (root / "006_ai daily newsletter").mkdir(parents=True, exist_ok=True)
    (root / "006_ai daily newsletter" / f"{today:%y-%m-%d}.md").write_text("# AI 日报", encoding="utf-8")
    client.app.state.store.update_settings({"kpi": {"read_started": "2000-01-01"}})
    d = _today(client)
    items = {i["key"]: i for i in d["rd"]["items"]}
    assert items["ai_daily"]["exists"] and not items["kline_daily"]["exists"]  # K 线日报今天没出，不要求
    assert d["days"][-1]["rd"] == "pending"
    client.put("/api/today/checks", json={"day": today.isoformat(), "key": "ai_daily", "checked": True})
    assert _today(client)["days"][-1]["rd"] == "ok"
    # K 线日报出了（它自己的文件夹），就也要读
    (tmp_path / "kline").mkdir()
    (tmp_path / "kline" / f"{today:%Y-%m-%d}-kline-daily-newsletter.md").write_text("# K", encoding="utf-8")
    d = _today(client)
    assert {i["key"]: i["exists"] for i in d["rd"]["items"]}["kline_daily"] and d["days"][-1]["rd"] == "pending"
    assert client.put("/api/today/checks", json={"day": today.isoformat(), "key": "kline_daily", "checked": True}).status_code == 200
    assert _today(client)["days"][-1]["rd"] == "ok"


# -- 周历（#334）：能排一整周，能看每天做没做到、减了几分 ---------------------------------

def test_a_week_is_scored_with_the_same_rules_and_never_before_he_started() -> None:
    today = date(2026, 9, 30)  # 周三
    days = driver.kpi_range(driver.week_start(today), date(2026, 10, 4), today, posted={"2026-09-29"}, started="2026-09-29",
                            dms={"2026-09-30": {"received": 0, "replied": 0}}, x_replies={"2026-09-30": 10}, x_target=10,
                            reads={"2026-09-30": True}, read_started="2026-09-30", ship_started="2026-09-29")
    assert [d["day"][-2:] for d in days] == ["28", "29", "30", "01", "02", "03", "04"]  # 周一到周日
    by = {d["day"][-2:]: d for d in days}
    assert by["28"]["ship"] == "n/a" and by["28"]["dm"] == "n/a"  # 开始算之前：不倒扣
    assert (by["29"]["ship"], by["29"]["dm"], by["29"]["xr"], by["29"]["rd"]) == ("ok", "miss", "miss", "n/a")
    assert (by["30"]["ship"], by["30"]["dm"], by["30"]["xr"], by["30"]["rd"]) == ("pending", "ok", "ok", "ok")  # 今天没发不算减分
    assert all(by[k][f] == "future" for k in ("01", "04") for f in ("rd", "ship", "dm", "xr"))
    assert driver.demerits(days) == 0  # 29 号出摊了；私信、X 没做到不再减分（10/5）


def test_streak_says_which_line_he_is_on() -> None:
    posted = {"2026-09-24", "2026-09-29"}
    assert driver.ship_streak(date(2026, 9, 30), posted) == {"kind": "ok", "days": 1}  # 今天还没发不算断
    assert driver.ship_streak(date(2026, 9, 29), posted) == {"kind": "ok", "days": 1}
    assert driver.ship_streak(date(2026, 9, 29), {"2026-09-24"}) == {"kind": "miss", "days": 4}  # 25–28 四天没发
    assert driver.ship_streak(date(2026, 9, 30), {"2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"}) == {"kind": "ok", "days": 4}
    assert driver.ship_streak(date(2026, 9, 30), set()) == {"kind": "none", "days": 0}


def test_the_top_of_the_list_is_what_he_shoots_next_whatever_was_planned() -> None:
    """10/4 作者：不排哪天拍哪条，每天拍清单最上面那条。以前排过的日子不再起作用。"""
    notes = [{"id": 1, "planned_day": None}, {"id": 2, "planned_day": "2026-10-03"}, {"id": 3, "planned_day": "2026-10-01"},
             {"id": 4, "planned_day": "2026-09-29"}, {"id": 5, "planned_day": None}]
    assert [n["id"] for n in driver.plan_order(notes, "2026-10-01")] == [1, 2, 3, 4, 5]


def test_week_calendar_holds_the_plan_and_the_score(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    client.post("/api/today/notes", json={"text": "清单第一条"})
    client.post("/api/today/notes", json={"text": "排在今天的这条", "planned_day": today.isoformat()})
    d = _today(client)
    week = d["week"]
    assert week["current"] and len(week["days"]) == 7 and date.fromisoformat(week["start"]).weekday() == 0
    assert set(d) >= {"days", "demerits", "week", "streak"}  # 原来的字段还在，含义没变
    cell = next(c for c in week["days"] if c["state"] == "today")
    assert cell["planned"] == []  # 10/19 拿掉排期：旧清单不再往日历上摆，只有正在做的那条
    assert d["ship"]["next"]["key"] == "notes:empty"  # 没有正在做的：去选题挑一条
    doing = client.post("/api/topics", json={"title": "正在做的这条", "formats": "video"}).json()
    client.post(f"/api/topics/{doing['id']}/focus").raise_for_status()
    cells = {c["day"]: c for c in _today(client)["week"]["days"]}
    assert [p["text"] for p in cells[today.isoformat()]["planned"]] == ["正在做的这条"]  # 日历只写正在做的那条
    assert all(c["planned"] == [] for k, c in cells.items() if k > today.isoformat())
    client.delete(f"/api/topics/{doing['id']}/focus")
    d = _today(client)
    assert [n["text"] for n in d["ship"]["notes"]] == ["清单第一条", "排在今天的这条"]  # 清单自己的顺序不动

    # 把清单第一条拖到明天（= 放到第 2 位）；再加一件不算分的事，做完勾掉
    first = d["ship"]["notes"][0]["id"]
    client.patch(f"/api/today/notes/{first}", json={"at": 1})
    item = client.post("/api/today/plan", json={"day": tomorrow, "text": "约两个博主诊断"}).json()["item"]
    wk = client.get("/api/today/week", params={"start": tomorrow}).json()
    cell = next(c for c in wk["days"] if c["day"] == tomorrow)
    assert cell["planned"] == [] and cell["items"] == [{"id": item["id"], "text": "约两个博主诊断", "done": False}]
    if cell["state"] == "future":
        assert cell["ship"] == "future" and cell["demerits"] == 0
    client.patch(f"/api/today/plan/{item['id']}", json={"done": True})
    client.delete(f"/api/today/notes/{first}")  # 不拍了：后面没有了，明天空着
    cell = next(c for c in client.get("/api/today/week", params={"start": tomorrow}).json()["days"] if c["day"] == tomorrow)
    assert cell["planned"] == [] and cell["items"][0]["done"] is True
    client.delete(f"/api/today/plan/{item['id']}")
    assert all(c["items"] == [] for c in client.get("/api/today/week", params={"start": tomorrow}).json()["days"])

    # 翻到上一周、下一周：都是周一开头的七天；没发过视频的时候，过去的日子不倒扣
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    nxt = client.get("/api/today/week", params={"start": week["next"]}).json()
    assert prev["next"] == week["start"] and nxt["prev"] == week["start"] and not prev["current"]
    # 只看出摊：私信、X 回复、读日报从 KPI 开始那天起照算，上一周走进 9/29 之后就会有它们的扣分（10/5 起这里不再是 0）
    assert all(c["state"] == "past" and c["ship"] == "n/a" for c in prev["days"])
    assert all(c["state"] == "future" for c in nxt["days"])
    second = client.get("/api/today/queue").json()["notes"][0]["id"]
    assert client.patch(f"/api/today/notes/{second}", json={"planned_day": "下周三"}).status_code == 400


def test_past_days_show_what_went_out_and_the_demerits(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    today = date.today()
    two_ago, yesterday = today - timedelta(days=2), today - timedelta(days=1)
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="ok", is_self=True)
    store.upsert_videos(me["id"], [{"platform": "抖音", "video_id": "v1", "title": "接了一单咨询\n把这件事拍出来", "published_at": f"{two_ago.isoformat()}T10:00:00+08:00",
                                    "duration_seconds": 600, "is_top": 0, "is_image_post": 0, "likes": 1, "comments": 0, "shares": 0, "collects": 0, "views": 10}])
    d = _today(client)
    cells = {c["day"]: c for wk in (d["week"], client.get("/api/today/week", params={"start": two_ago.isoformat()}).json()) for c in wk["days"]}
    assert cells[two_ago.isoformat()]["ship"] == "ok" and cells[two_ago.isoformat()]["shipped"] == ["接了一单咨询 把这件事拍出来"]
    assert cells[yesterday.isoformat()]["ship"] == "miss" and cells[yesterday.isoformat()]["demerits"] >= 1  # 昨天没发：减分
    assert d["streak"] == {"kind": "miss", "days": 1}
    week = client.get("/api/today/week", params={"start": yesterday.isoformat()}).json()
    # 周一跑的时候「昨天」那一周已经过完，周下限少的条数也算进去（new_short）
    assert week["demerits"] == sum(c["demerits"] for c in week["days"]) + week["new_short"] and week["ship_days"] >= 1


# -- 追平阶段（9/30 作者）：每天发一条新视频，或者补发当天那几格；每周至少 3 条新的；出关 = 旧内容清完 + 连续出摊 14 天 --

def test_a_backfill_day_counts_as_shipping_and_keeps_the_streak() -> None:
    today = date(2026, 10, 4)
    new_video, backfilled = {"2026-10-01", "2026-10-03"}, {"2026-10-02"}
    days = driver.kpi_range(date(2026, 9, 30), today, today, posted=new_video | backfilled, dms={}, started="9999", ship_started="2026-09-30")
    assert [(d["day"][-2:], d["ship"]) for d in days] == [("30", "miss"), ("01", "ok"), ("02", "ok"), ("03", "ok"), ("04", "pending")]
    assert driver.demerits(days) == 1 and all("bf" not in d for d in days)  # 补发不再单独算一项
    assert driver.ship_streak(today, new_video | backfilled) == {"kind": "ok", "days": 3}  # 新视频和补发交替，连续天数接着算
    assert driver.ship_streak(today, new_video) == {"kind": "ok", "days": 1}


def test_stage_is_catchup_until_backlog_is_clear_and_the_streak_is_long_enough() -> None:
    st = driver.stage(backlog=71, streak={"kind": "ok", "days": 1}, streak_target=14)
    assert (st["key"], st["backlog"], st["streak"], st["done"]) == ("catchup", 71, 1, False)
    assert driver.stage(backlog=0, streak={"kind": "ok", "days": 13}, streak_target=14)["done"] is False
    assert driver.stage(backlog=3, streak={"kind": "ok", "days": 20}, streak_target=14)["done"] is False
    assert driver.stage(backlog=0, streak={"kind": "miss", "days": 2}, streak_target=14)["streak"] == 0  # 断了就从头数
    assert driver.stage(backlog=0, streak={"kind": "ok", "days": 14}, streak_target=14)["done"] is True


def test_todays_cells_count_only_when_enough_are_picked_and_all_sent(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    store = client.app.state.store
    today = date.today().isoformat()
    sheet = client.get("/api/backfill").json()
    old = [v for v in sheet["videos"] if not v["published_at"].startswith(today)][:2]
    keys = [p["key"] for p in sheet["platforms"] if p["key"] != "douyin"]
    for i in _today(client)["rd"]["items"]:  # 今天出了的日报先读完，才轮到出摊
        if i["exists"]:
            client.put("/api/today/checks", json={"day": today, "key": i["key"], "checked": True})
    d = _today(client)
    assert d["out"]["cells"] == [] and d["out"]["mode"] is None  # 没有打好包的旧内容：今天没有能补的格子
    core = {p["key"] for p in sheet["platforms"] if p["core"]}
    assert d["stage"]["backlog"] == sum(1 for v in sheet["videos"] for k in v["missing"] if k in core)  # 旧内容按格数，降权的三个不算（10/4）
    assert client.post("/api/today/cells/0/sent", json={"sent": True}).status_code == 400

    # 今天排了两格（测试里直接排上；线上是他在补发工作台点的）
    store.set_backfill_plan(today, [(old[0]["video_id"], keys[0]), (old[1]["video_id"], keys[1])])
    d = _today(client)
    assert [(c["slot"], c["platform"], c["sent"]) for c in d["out"]["cells"]] == [(0, keys[0], False), (1, keys[1], False)]
    assert _today(client)["out"]["cells"] == d["out"]["cells"]  # 再读一次：还是这两格
    was = d["days"][-1]["ship"]
    video_only = d["video_only"]  # 10/5 起出摊只认新视频：补发格子照样能发，但不再问「发不发新的」，发完也不顶出摊
    if not video_only:
        assert driver.now_item(d)["inputs"] == "mode"  # 还没说今天发不发新的：先问

    assert client.post("/api/today/mode", json={"mode": "maybe"}).status_code == 400
    assert client.post("/api/today/mode", json={"mode": "backfill"}).json() == {"mode": "backfill"}
    d = _today(client)
    now = driver.now_item(d)
    assert d["out"]["mode"] == "backfill"
    if not video_only:
        assert now["inputs"] == "bw" and "2 格没发出去" in now["text"]  # 去补发工作台

    client.post("/api/today/cells/0/sent", json={"sent": True})
    d = _today(client)
    assert d["out"]["sent"] == 1 and not d["out"]["done"] and d["days"][-1]["ship"] == was  # 只发了一格：还不算
    client.post("/api/today/cells/1/sent", json={"sent": True})
    d = _today(client)
    # 一天要挑够 4 格；但现在能发的旧内容一共只有这 2 格（别的包都没定稿）：有几格算几格
    assert d["out"]["need"] == 2
    if video_only:
        assert d["out"]["done"] and d["days"][-1]["ship"] == was  # 格子发完了，但补发不再算出摊
    elif was != "ok":  # 今天没发新视频：补发的格子都发完，就算出摊，连续天数接着算
        assert d["out"]["done"] and d["days"][-1]["ship"] == "ok" and d["streak"]["kind"] == "ok"
        assert next(c for c in d["week"]["days"] if c["state"] == "today")["backfilled"] is True
        assert "挑的 2 格都发完了" in client.get("/api/wendy/brief").json()["text"]
    # 点错了撤回：这一天又不算了
    client.post("/api/today/cells/1/sent", json={"sent": False})
    d = _today(client)
    assert d["out"]["sent"] == 1 and not d["out"]["done"] and d["days"][-1]["ship"] == was


def test_three_new_videos_a_week_is_only_charged_after_the_week_ends_and_never_backdated(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    d = _today(client)
    week = d["week"]
    assert (week["new_videos"], week["new_target"], week["new_short"]) == (0, 3, 0)  # 这一周还没过完：只看进度，不扣
    cur = store.settings()["kpi"]
    store.update_settings({"kpi": {**cur, "new_weekly_started": week["start"]}})  # 规矩从这一周起（不靠今天是哪天）
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    assert prev["new_short"] == 0 and not prev["new_counts"]  # 定规矩之前的周：不倒扣
    store.update_settings({"kpi": {**cur, "new_weekly_started": "2000-01-03"}})
    prev = client.get("/api/today/week", params={"start": week["prev"]}).json()
    assert prev["new_counts"] and prev["new_short"] == 3 and prev["demerits"] == sum(c["demerits"] for c in prev["days"]) + 3
    assert client.get("/api/today/week", params={"start": week["start"]}).json()["new_short"] == 0
    brief = client.get("/api/wendy/brief").json()["text"]
    assert "[本周新视频] 0/3 条，周日前还差 3 条" in brief and "[现在在哪个阶段] 追平" in brief


# -- 月历（10/1 作者：「今天」最上面放 monthly calendar，能看清哪天在哪些平台发了什么）------------------

def test_month_is_whole_weeks_and_shows_what_went_out_where(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    today = date.today()
    m = client.get("/api/today/month").json()
    days = [d for w in m["weeks"] for d in w["days"]]
    assert m["current"] and m["month"] == today.isoformat()[:7] and len(days) % 7 == 0 and 28 <= len(days) <= 42
    assert date.fromisoformat(days[0]["day"]).weekday() == 0 and days[0]["day"] <= today.replace(day=1).isoformat()  # 从周一开始，盖住 1 号
    assert {d["day"] for d in days if d["in_month"]} >= {today.isoformat(), today.replace(day=1).isoformat()}
    assert all(d["sent"] == [] for d in days)  # 还没往别的平台发过

    # 一格标了已发：那一天就写着发到了哪个平台、哪一条
    sheet = client.get("/api/backfill").json()
    video, key = sheet["videos"][0], sheet["platforms"][1]["key"]
    def today_cell() -> dict:
        return next(d for w in client.get("/api/today/month").json()["weeks"] for d in w["days"] if d["day"] == today.isoformat())

    # 在全平台追踪里补记「以前在外面发过」：不是今天发的，月历上不写
    client.post(f"/api/backfill/{video['video_id']}/mark", json={"platform": key})
    assert today_cell()["sent"] == []
    # 今天补发的格子里点了「发了」：今天这一格就写着发到了哪个平台、哪一条
    other = sheet["platforms"][2]["key"]
    client.app.state.store.set_backfill_plan(today.isoformat(), [(video["video_id"], other)])
    client.post("/api/today/cells/0/sent", json={"sent": True})
    cell = today_cell()
    assert [(x["platform"], x["marked"]) for x in cell["sent"]] == [(other, True)] and cell["sent"][0]["title"]

    prev = client.get("/api/today/month", params={"start": m["prev"]}).json()
    nxt = client.get("/api/today/month", params={"start": m["next"]}).json()
    assert not prev["current"] and prev["next"] == today.replace(day=1).isoformat() and nxt["prev"] == today.replace(day=1).isoformat()
    assert all(d["state"] == "future" for w in nxt["weeks"] for d in w["days"] if d["in_month"])


def test_backfill_desk_sends_the_picked_cells_one_by_one_in_the_order_he_clicked(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """确认以后后台按他点的顺序一格一格发（假的发布脚本，不碰真平台）：X 直接发出去，公众号进草稿箱。"""
    import json
    import sys
    import time

    from content_studio import approvals, web as web_module
    from tests.test_web import SEC, FakeClient, _wait_sync

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    monkeypatch.setenv("CONTENT_STUDIO_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    # 包都定稿了（打包页的定稿状态不是这条测试要测的）
    monkeypatch.setattr(approvals, "status", lambda folder, fps: {k: {"approved": True, "valid": True, "made": True, "by": "park"}
                                                                   for k in ("copy", "cover", "article", "figs", "wx", "xhs")})
    log = tmp_path / "sent.txt"
    cred = tmp_path / "secrets.yaml"
    cred.write_text("{}")

    def fake(platform: str, published: bool) -> list[str]:
        script = (f"import json,time,pathlib; time.sleep(0.2); p=pathlib.Path({str(log)!r}); "
                  f"p.write_text((p.read_text() if p.exists() else '') + {platform!r} + '\\n'); "
                  f"print(json.dumps({{'ok': True, 'published': {published}, 'url': 'https://example.com/{platform}'}}))")
        return [sys.executable, "-c", script, "{article}"]

    specs = {"x": {"label": "X", "copy_key": "x", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                   "modes": {"article_publish": {"label": "发", "argv": fake("x", True)}}},
             "wechat_mp": {"label": "公众号", "copy_key": "wechat_mp", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                           "modes": {"draft": {"label": "草稿", "argv": fake("wechat_mp", False)}}}}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    monkeypatch.setenv("CONTENT_STUDIO_NO_OPEN", "1")
    app = web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                publishers=specs)
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
        _wait_sync(c)
        vid = c.get("/api/backfill").json()["videos"][0]["video_id"]
        tid = c.post(f"/api/backfill/{vid}/take").json()["topic_id"]
        art = tmp_path / "drafts" / f"topic-{tid}" / "article.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("# 文章标题\n\n第一段。\n", encoding="utf-8")
        app.state.store.update_topic(tid, article_path=str(art))

        row = next(r for r in c.get("/api/backfill/desk").json()["rows"] if r["video_id"] == vid)
        # 10/4：公众号降权了，不用他挑——这一格是「自动」，按排期发
        assert row["cells"]["x"]["state"] == "open" and row["cells"]["wechat_mp"]["state"] == "auto"
        picks = {"cells": [{"video_id": vid, "platform": "x"}]}
        pv = c.post("/api/backfill/desk/preview", json=picks).json()
        assert [(i["n"], i["platform"], i["how"]) for i in pv["items"]] == [(1, "x", "auto")]
        assert pv["items"][0]["article"]["title"] == "文章标题"
        assert not log.exists()  # 预览不发

        assert c.post("/api/backfill/desk/go", json=picks).json() == {"started": 1}
        assert c.post("/api/backfill/desk/go", json=picks).status_code == 400  # 还在发：不能再起一批
        for _ in range(200):
            run = c.get("/api/backfill/desk").json()["run"]
            # 线程可能还没起来就读到 running=False：等那一格真的发完
            if not run["running"] and all(i["state"] not in ("idle", "waiting", "running") for i in run["items"]) and all(i["sent"] or i["state"] != "done" for i in run["items"]):
                break
            time.sleep(0.05)
        assert log.read_text().split() == ["x"]
        assert [(i["platform"], i["state"], i["sent"]) for i in run["items"]] == [("x", "done", True)]
        today = date.today().isoformat()
        assert [(r["video_id"], r["platform"]) for r in app.state.store.backfill_plan(today)] == [(vid, "x")]
        out = c.get("/api/today").json()["out"]
        assert out["sent"] == 1 and out["mode"] == "backfill"
    app.state.store.close()


def test_backfill_desk_marks_a_cell_not_sent_and_closes_the_current_video(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/3 作者：「发布完毕」和「跳过」从发布页搬进补发工作台。

    标「不发」的格子不算缺（全平台追踪、补发、打包都认）；今天排上的格子要先拿掉才能标。
    「发布完毕」只给打包页还挂着的那条：点了打包、发布页就收起它，没发的格子以后照样能补。"""
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    desk = client.get("/api/backfill/desk").json()
    row = desk["rows"][0]
    vid, plats = row["video_id"], [p["key"] for p in desk["platforms"]]
    assert row["closable"] is False  # 没接上选题的老内容：没有「结」这回事

    assert client.post(f"/api/backfill/{vid}/skip", json={"platform": plats[0]}).json() == {"ok": True, "skip": True}
    cell = next(r for r in client.get("/api/backfill/desk").json()["rows"] if r["video_id"] == vid)["cells"][plats[0]]
    assert cell == {"state": "skipped"}
    sheet = next(v for v in client.get("/api/backfill").json()["videos"] if v["video_id"] == vid)
    assert plats[0] not in sheet["missing"] and sheet["done"][plats[0]] == "skip"
    client.post(f"/api/backfill/{vid}/skip", json={"platform": plats[0], "skip": False})
    assert plats[0] in next(v for v in client.get("/api/backfill").json()["videos"] if v["video_id"] == vid)["missing"]
    assert store.settings()["tracker_skip"] == {}
    assert client.post(f"/api/backfill/{vid}/skip", json={"platform": "douyin"}).status_code == 400
    assert client.post("/api/backfill/nope/skip", json={"platform": plats[0]}).status_code == 400
    store.set_backfill_plan(date.today().isoformat(), [(vid, plats[1])])
    assert client.post(f"/api/backfill/{vid}/skip", json={"platform": plats[1]}).status_code == 400
    store.set_backfill_plan(date.today().isoformat(), [])

    # 接上选题、抖音发了的新视频：打包页挂着它，工作台给「发布完毕」
    client.put("/api/settings", json={"platform_accounts": {k: {"on": True, "handle": ""} for k in plats[:2]}})
    topic = client.post("/api/topics", json={"title": "抖音刚发"}).json()
    store.update_topic(topic["id"], published_video_id=vid)
    row = next(r for r in client.get("/api/backfill/desk").json()["rows"] if r["video_id"] == vid)
    assert row["topic_id"] == topic["id"] and row["closable"] is True
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    # 开着的平台都标了不发：也算发完
    for k in plats[:2]:
        client.post(f"/api/backfill/{vid}/skip", json={"platform": k})
    assert client.get("/api/publish/desk").json()["topic"] is None
    client.post(f"/api/backfill/{vid}/skip", json={"platform": plats[0], "skip": False})
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    client.post(f"/api/topics/{topic['id']}/close")
    assert client.get("/api/publish/desk").json()["topic"] is None
    row = next(r for r in client.get("/api/backfill/desk").json()["rows"] if r["video_id"] == vid)
    assert row["closable"] is False and row["cells"][plats[0]]["state"] != "skipped"  # 结了，没发的格子还能补

    # 抖音上两周前发的老内容：选题刚被批量打包过（更新时间是新的）也不挂在打包页、不给「发布完毕」
    client.delete(f"/api/topics/{topic['id']}/close")
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    with store.tx() as conn:
        conn.execute("UPDATE videos SET published_at = ? WHERE video_id = ?", ("2026-01-01T00:00:00+00:00", vid))
    assert client.get("/api/publish/desk").json()["topic"] is None
    assert next(r for r in client.get("/api/backfill/desk").json()["rows"] if r["video_id"] == vid)["closable"] is False


def test_a_platform_that_needs_login_is_not_sent_and_resends_itself_after_login(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/3 作者：出了问题要知道怎么解决、我要做什么、在这一页马上就能做，做完自己检测、自己再发。

    发之前先探测：没登上就不发，这一格变成「要登录」，给登录按钮和一句话。点登录跑平台自己的登录命令，
    退出后真探测一次；登上了，这个平台今天没发出去的格子自动再发一遍。（假的通道，不碰真平台。）"""
    import json
    import sys
    import time

    from content_studio import approvals, channel_probe, web as web_module
    from tests.test_web import SEC, FakeClient, _wait_sync

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    monkeypatch.setenv("CONTENT_STUDIO_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setattr(channel_probe, "CACHE_PATH", tmp_path / "probes.json")
    monkeypatch.setattr(approvals, "status", lambda folder, fps: {k: {"approved": True, "valid": True, "made": True, "by": "park"}
                                                                   for k in ("copy", "cover", "article", "figs", "wx", "xhs")})
    flag, sent = tmp_path / "logged-in", tmp_path / "sent.txt"
    cred = tmp_path / "secrets.yaml"
    cred.write_text("{}")
    probe = [sys.executable, "-c", f"import pathlib; print('token_valid' if pathlib.Path({str(flag)!r}).exists() else 'expired')"]
    login = [sys.executable, "-c", f"import pathlib, time; time.sleep(0.3); pathlib.Path({str(flag)!r}).write_text('1')"]
    upload = [sys.executable, "-c", f"import json, pathlib; pathlib.Path({str(sent)!r}).write_text('x'); print(json.dumps({{'ok': True, 'url': 'https://x.com/i/1'}}))", "{article}"]
    specs = {"x": {"label": "X", "copy_key": "x", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                   "probe": probe, "probe_ok": "token_valid", "login_argv": login,
                   "modes": {"article_publish": {"label": "发", "argv": upload}}}}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    monkeypatch.setenv("CONTENT_STUDIO_NO_OPEN", "1")
    app = web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                publishers=specs)

    def settle(c):
        for _ in range(200):
            run = c.get("/api/backfill/desk").json()["run"]
            if not run["running"]:
                return run
            time.sleep(0.05)
        raise AssertionError("还在发")

    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
        _wait_sync(c)
        vid = c.get("/api/backfill").json()["videos"][0]["video_id"]
        tid = c.post(f"/api/backfill/{vid}/take").json()["topic_id"]
        art = tmp_path / "drafts" / f"topic-{tid}" / "article.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("# 文章标题\n\n第一段。\n", encoding="utf-8")
        app.state.store.update_topic(tid, article_path=str(art))

        assert c.post("/api/backfill/desk/go", json={"cells": [{"video_id": vid, "platform": "x"}]}).json() == {"started": 1}
        item = settle(c)["items"][0]
        assert item["state"] == "login" and not sent.exists()  # 没登上：没去发
        assert item["diag"]["fix"] == "login" and item["diag"]["todo"]
        assert c.post("/api/platforms/douyin/login").status_code == 400  # 没有登录命令的平台

        assert c.post("/api/platforms/x/login").json()["state"] == "running"
        for _ in range(200):
            if sent.exists() and not c.get("/api/backfill/desk").json()["run"]["running"]:
                break
            time.sleep(0.05)
        assert c.get("/api/platforms/x/login").json()["state"] in ("ok", "idle")  # 再发起来以后「登好了」那句就清掉
        item = settle(c)["items"][0]
        assert item["state"] == "done" and item["sent"] and item["url"] == "https://x.com/i/1"  # 登好了自己再发，链接能点
    app.state.store.close()


def test_login_resends_what_failed_before_a_restart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/3：YouTube 登好了却没再发——中间自动部署重启过，内存里「今天在发的」是空的。
    重启后从库里认出上次失败的格子：登好了照样自动再发；没自动发出去时，这一行给「再发一次」而不是再登一次。"""
    import json
    import sys
    import time

    from content_studio import approvals, channel_probe, web as web_module
    from tests.test_web import SEC, FakeClient, _wait_sync

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    monkeypatch.setenv("CONTENT_STUDIO_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setenv("CONTENT_STUDIO_NO_OPEN", "1")
    monkeypatch.setattr(channel_probe, "CACHE_PATH", tmp_path / "probes.json")
    monkeypatch.setattr(approvals, "status", lambda folder, fps: {k: {"approved": True, "valid": True, "made": True, "by": "park"}
                                                                   for k in ("copy", "cover", "article", "figs", "wx", "xhs")})
    flag, sent = tmp_path / "logged-in", tmp_path / "sent.txt"
    cred = tmp_path / "secrets.yaml"
    cred.write_text("{}")
    # 探测说登着（像 YouTube：令牌在，刷新时才报过期）；上传没登好就报 invalid_grant
    probe = [sys.executable, "-c", "print('token_valid')"]
    login = [sys.executable, "-c", f"import pathlib; pathlib.Path({str(flag)!r}).write_text('1')"]
    upload = [sys.executable, "-c", (f"import json, pathlib, sys\nif not pathlib.Path({str(flag)!r}).exists():\n"
                                     f"    print('RefreshError: invalid_grant: Token has been expired', file=sys.stderr); sys.exit(1)\n"
                                     f"pathlib.Path({str(sent)!r}).write_text('x'); print(json.dumps({{'ok': True, 'url': 'https://x.com/i/2'}}))"), "{article}"]
    specs = {"x": {"label": "X", "copy_key": "x", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                   "probe": probe, "probe_ok": "token_valid", "login_argv": login,
                   "modes": {"article_publish": {"label": "发", "argv": upload}}}}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)

    def make_app():
        return web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                     downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                     publishers=specs)

    def settle(c):
        for _ in range(200):
            run = c.get("/api/backfill/desk").json()["run"]
            if not run["running"]:
                return run
            time.sleep(0.05)
        raise AssertionError("还在发")

    app = make_app()
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
        _wait_sync(c)
        vid = c.get("/api/backfill").json()["videos"][0]["video_id"]
        tid = c.post(f"/api/backfill/{vid}/take").json()["topic_id"]
        art = tmp_path / "drafts" / f"topic-{tid}" / "article.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("# 文章标题\n\n第一段。\n", encoding="utf-8")
        app.state.store.update_topic(tid, article_path=str(art))
        c.post("/api/backfill/desk/go", json={"cells": [{"video_id": vid, "platform": "x"}]})
        assert settle(c)["items"][0]["state"] == "failed"
    app.state.store.close()

    app = make_app()  # 重启：内存里的进度没了
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        item = c.get("/api/backfill/desk").json()["run"]["items"][0]
        assert item["state"] == "failed" and "invalid_grant" in item["message"]
        assert item["diag"]["fix"] == "login"  # 发之前那次探测比失败早：还是要登录
        # 登录后探测过（比失败晚）、自动再发没起来——比如又重启了：这一行给「再发一次」，不是再登一次
        probes = tmp_path / "cs-home" / "channel-probes.json"
        probes.parent.mkdir(parents=True, exist_ok=True)
        probes.write_text(json.dumps({"x": {"ok": True, "checked_at": "2999-01-01T00:00:00+00:00"}}))
        assert c.get("/api/backfill/desk").json()["run"]["items"][0]["diag"]["fix"] == "retry"

        c.post("/api/platforms/x/login")
        for _ in range(200):
            if sent.exists() and not c.get("/api/backfill/desk").json()["run"]["running"]:
                break
            time.sleep(0.05)
        item = settle(c)["items"][0]
        assert item["sent"] and item["url"] == "https://x.com/i/2"  # 重启前失败的那格，登好了照样自己再发
    app.state.store.close()


def test_backfill_desk_keeps_fully_sent_rows_folded_and_shows_douyin(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/3 作者：发齐了的别从工作台里消失，折起来、展开能看到；抖音也放进表里，最左边。"""
    from tests.test_web import SEC, _wait_sync

    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    desk = client.get("/api/backfill/desk").json()
    row = desk["rows"][0]
    vid = row["video_id"]
    assert row["douyin"]["url"] == f"https://www.douyin.com/video/{vid}" and desk["done_rows"] == []
    plats = [p["key"] for p in desk["platforms"]]
    for i, k in enumerate(plats):
        if i % 2:
            client.post(f"/api/backfill/{vid}/skip", json={"platform": k})
        else:
            client.post(f"/api/backfill/{vid}/mark", json={"platform": k, "done": True})
    desk = client.get("/api/backfill/desk").json()
    assert vid not in [r["video_id"] for r in desk["rows"]]
    done = next(r for r in desk["done_rows"] if r["video_id"] == vid)
    assert {c["state"] for c in done["cells"].values()} == {"sent", "skipped"} and done["douyin"]["url"]
    assert done["closable"] is False


def test_from_oct_5_shipping_means_a_new_video(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/4 作者：「每天至少要拍一个视频」。10/5 起页面不再问今天发不发新视频，补发不顶出摊。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    d = _today(client)
    assert d["video_only"] is (date.today().isoformat() >= "2026-10-05")


# -- 选题拖进日历（10/5 作者）：日子 = 清单按顺序摆，拖到哪天 = 插到清单那一位 ----------------------------

def test_queue_days_start_today_or_tomorrow_once_today_shipped() -> None:
    notes = [{"id": 1}, {"id": 2}, {"id": 3}]
    today = date(2026, 10, 5)
    assert {k: n["id"] for k, n in driver.queue_days(notes, today, False).items()} == {"2026-10-05": 1, "2026-10-06": 2, "2026-10-07": 3}
    # 今天已经发了新视频：清单第一条排明天
    assert {k: n["id"] for k, n in driver.queue_days(notes, today, True).items()} == {"2026-10-06": 1, "2026-10-07": 2, "2026-10-08": 3}
    # 漏拍一天不用重排：明天再看，整列自动往后挪
    assert min(driver.queue_days(notes, date(2026, 10, 6), False)) == "2026-10-06"
    assert driver.queue_days([], today, False) == {}


def test_drag_topics_from_pool_onto_days(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    a, b, c = (client.post("/api/topics", json={"title": t}).json() for t in ("选题甲", "选题乙", "选题丙"))
    client.post("/api/today/notes", json={"text": "手写的一条"})

    q = client.get("/api/today/queue").json()
    assert len(q["days"]) == 14 and q["days"][0]["day"] == date.today().isoformat() and q["days"][0]["note"]["text"] == "手写的一条"
    assert q["days"][1]["note"] is None and q["more"] == 0

    # 甲拖到今天（第 0 位）：手写那条挪到明天
    q = client.post("/api/today/queue", json={"topic_ids": [a["id"]], "at": 0}).json()
    assert [d["note"]["text"] if d["note"] else None for d in q["days"][:3]] == ["选题甲", "手写的一条", None]
    assert q["days"][0]["note"]["topic_id"] == a["id"]
    # 乙、丙不带位置：接在最后（系列「整个排上」走的就是这条）
    q = client.post("/api/today/queue", json={"topic_ids": [b["id"], c["id"]]}).json()
    assert [n["text"] for n in q["notes"]] == ["选题甲", "手写的一条", "选题乙", "选题丙"]
    # 已经在清单里的再拖一次：只挪位置，不重复加
    q = client.post("/api/today/queue", json={"topic_ids": [c["id"]], "at": 1}).json()
    assert [n["text"] for n in q["notes"]] == ["选题甲", "选题丙", "手写的一条", "选题乙"]
    # 日历里上下拖：PATCH at
    q_notes = client.patch(f"/api/today/notes/{q['notes'][0]['id']}", json={"at": 99}).json()["notes"]
    assert [n["text"] for n in q_notes] == ["选题丙", "手写的一条", "选题乙", "选题甲"]

    # 月历上以后的日子写着排到的那条；过去的日子不写
    cells = {d["day"]: d for w in client.get("/api/today/month").json()["weeks"] for d in w["days"]}
    assert all(c["planned"] == [] for c in cells.values())  # 10/19：没有正在做的，月历不按旧清单往后排
    assert all(c["planned"] == [] for k, c in cells.items() if k < date.today().isoformat())

    # 丙发出去了：从清单划掉，后面的往前补
    client.app.state.store.update_topic(c["id"], closed_at="2026-10-05T10:00:00+08:00")
    q = client.get("/api/today/queue").json()
    assert [n["text"] for n in q["notes"]] == ["手写的一条", "选题乙", "选题甲"] and q["days"][0]["note"]["text"] == "手写的一条"
    # 发过的、不做了的选题拖进来不算
    assert [n["text"] for n in client.post("/api/today/queue", json={"topic_ids": [c["id"]], "at": 0}).json()["notes"]] == ["手写的一条", "选题乙", "选题甲"]


def test_platform_forms_are_chosen_only_on_the_title_and_cover_page() -> None:
    """每条内容在每个平台发什么只在一处定。10/7 作者：拍完（写完）在「标题和封面」页一张表上定；
    平台页只显示、给一个回去改的链接，平台自己的设置只管以后新建的默认。"""
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    assert "renderFormsRow" not in (static / "video.js").read_text(encoding="utf-8")
    assert "pkForms" in (static / "pack.js").read_text(encoding="utf-8")
    platform = (static / "platform.js").read_text(encoding="utf-8")
    assert "data-pp-form=" not in platform and "data-pp-def-form=" in platform
