"""Wendy 卡片（#338）：现在做哪一件、她说过的话、在卡片里回她、什么时候去微信催。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import driver
from content_studio.extras.consults import consult
from content_studio.extras.team import wendy
from tests.test_web import client  # noqa: F401 - fixture

NOON = datetime(2026, 10, 1, 13, 0)


@pytest.mark.parametrize(
    ("kw", "due"),
    [
        # 算分的事还没做完，他和她都三小时以上没动静：催
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=4), "last_contact": NOON - timedelta(hours=3, minutes=15), "nudges_today": 0}, True),
        # 今天一点动静都没有，她也没找过他：催
        ({"pending": ["出摊"], "last_activity": None, "last_contact": None, "nudges_today": 0}, True),
        # 都做完了：不催
        ({"pending": [], "last_activity": None, "last_contact": None, "nudges_today": 0}, False),
        # 他一小时前刚动过：不催
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=1), "last_contact": NOON - timedelta(hours=5), "nudges_today": 0}, False),
        # 她半小时前刚催过（他一直没动）：不连着催，一个钟头把三次用完就没意义了
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=6), "last_contact": NOON - timedelta(minutes=30), "nudges_today": 1}, False),
        # 一天最多三次
        ({"pending": ["出摊"], "last_activity": NOON - timedelta(hours=9), "last_contact": NOON - timedelta(hours=4), "nudges_today": 3}, False),
    ],
)
def test_nudge_only_after_three_quiet_hours_and_at_most_three_a_day(kw: dict, due: bool) -> None:
    assert wendy.nudge_due(NOON, **kw)["due"] is due


def test_no_nudge_outside_ten_to_ten() -> None:
    quiet = {"pending": ["出摊"], "last_activity": None, "last_contact": None, "nudges_today": 0}
    assert wendy.nudge_due(datetime(2026, 10, 1, 9, 59), **quiet)["due"] is False
    assert wendy.nudge_due(datetime(2026, 10, 1, 10, 0), **quiet)["due"] is True
    assert wendy.nudge_due(datetime(2026, 10, 1, 21, 59), **quiet)["due"] is True
    assert wendy.nudge_due(datetime(2026, 10, 1, 22, 0), **quiet)["due"] is False


def test_now_item_is_the_first_unfinished_thing_in_page_order() -> None:
    """10/5 作者：唯一算分的是出摊。读日报、回私信、X 互动不再出现在「现在做这一件」里。"""
    base = {"first": [], "rd": {"items": [{"label": "AI 日报", "exists": True, "read_at": None}]},
            "ship": {"done": False, "next": driver.item("ship", "note:1", "拍「接了一单咨询」")}, "days": [{"ship": "pending", "dm": "pending", "xr": "pending"}],
            "dm": {"entry": None}, "xr": {"count": 4, "target": 10}, "video_only": True, "wrap": [driver.item("wrap", "reach", "填播放")]}
    assert driver.now_item({**base, "first": [driver.item("blocker", "cookies", "抖音登录过期了")]})["row"] == "first"
    assert driver.now_item(base)["text"] == "拍「接了一单咨询」"  # 日报没读也不排在出摊前面
    shipped = {**base, "ship": {"done": True, "next": None}, "days": [{"ship": "ok", "dm": "pending", "xr": "pending"}]}
    assert driver.now_item(shipped)["row"] == "wrap"  # 私信、X 没做也不催
    assert driver.now_item({**shipped, "wrap": []}) is None  # 都做完了：没有在等他的事
    for t in (base, shipped):
        now = driver.now_item(t) or {}
        assert now.get("row") not in ("rd", "dm", "xr")


def _hermes(home, job_name: str, stamp: str, response: str) -> None:
    (home / "cron" / "output" / "j1").mkdir(parents=True, exist_ok=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "j1", "name": job_name}, {"id": "j2", "name": "别人的任务"}]}), encoding="utf-8")
    (home / "cron" / "output" / "j1" / f"{stamp}.md").write_text(f"# Cron Job: {job_name}\n\n## Prompt\n\n……\n\n## Response\n\n{response}\n", encoding="utf-8")


def test_what_she_said_on_wechat_is_read_not_rewritten(tmp_path) -> None:
    now = datetime(2026, 10, 1, 10, 0)
    assert wendy.hermes_messages(tmp_path, now=now) == []  # 没装 Hermes：空的，不报错
    _hermes(tmp_path, "wendy-morning", "2026-10-01_09-45-03", "连续出摊 2 天。今天拍的是「接了一单咨询」。")
    _hermes(tmp_path, "wendy-morning", "2026-09-20_09-45-03", "太早的不读")
    _hermes(tmp_path, "wendy-morning", "2026-10-01_09-50-00", "[SILENT]")
    said = wendy.hermes_messages(tmp_path, now=now)
    assert [(m["label"], m["text"]) for m in said] == [("早上", "连续出摊 2 天。今天拍的是「接了一单咨询」。")]
    assert said[0]["at"].startswith("2026-10-01T09:45:03")


def test_card_shows_now_and_answers_in_place(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    doing = client.post("/api/topics", json={"title": "接了一单咨询，拍出来", "formats": "video"}).json()
    client.post(f"/api/topics/{doing['id']}/focus").raise_for_status()
    stamp = datetime.now().replace(hour=0, minute=1, second=0).strftime("%Y-%m-%d_%H-%M-%S")
    _hermes(tmp_path / "hermes", "wendy-morning", stamp, "今天拍的是「接了一单咨询」。")
    for i in client.get("/api/today").json()["rd"]["items"]:  # 今天出了的日报先读完，才轮到出摊
        if i["exists"]:
            client.put("/api/today/checks", json={"day": date.today().isoformat(), "key": i["key"], "checked": True})
    card = client.get("/api/wendy").json()
    assert "《接了一单咨询，拍出来》" in card["now"]["text"] and card["now"]["row"] == "ship"
    assert [m["text"] for m in card["messages"]] == ["今天拍的是「接了一单咨询」。"] and card["messages"][0]["source"] == "wendy-morning"

    assert client.post("/api/wendy", json={"message": "下午三点拍"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert [(m["who"], m["text"]) for m in card["messages"][-2:]] == [("park", "下午三点拍"), ("wendy", "连续 1 天没出摊。今天几点拍？")]
    assert client.post("/api/wendy", json={"message": "x" * 2001}).status_code == 400

    brief = client.get("/api/wendy/brief").json()["text"]
    assert "[现在做这一件] 写拍摄提纲：《接了一单咨询，拍出来》" in brief and "这一周（周一起）" in brief
    assert "作者：下午三点拍" in brief  # 微信那边的她读这一段，才知道他在卡片里回过什么
    assert "周复盘" in client.get("/api/wendy/brief", params={"review": True}).json()["text"]


def test_a_reply_on_the_card_counts_as_activity_and_nudges_are_counted(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    store = client.app.state.store
    today = date.today().isoformat()
    assert store.last_touch(today) is None  # 打开页面不算动静
    verdict = client.get("/api/wendy/nudge").json()
    assert "出摊" in verdict["pending"] and verdict["nudges_today"] == 0
    store.add_wendy("park", "三点拍")
    assert store.last_touch(today) is not None
    assert client.get("/api/wendy/nudge").json()["due"] is False  # 他刚回过：不催
    assert client.post("/api/wendy/nudge").json()["nudges_today"] == 1
    assert client.get("/api/wendy").json()["nudges"] and client.get("/api/wendy/nudge").json()["nudges_today"] == 1
    # 微信里刚说过话也算动静（那边传过来的时间）
    quiet = client.get("/api/wendy/nudge", params={"wechat_at": datetime.now().isoformat()}).json()
    assert quiet["due"] is False
def test_card_asks_first_then_walks_him_through_the_path_he_chose() -> None:
    cells = [{"slot": 0, "title": "how to be successful", "label": "小红书", "topic_id": 36, "sent": True},
             {"slot": 1, "title": "为什么AI重度用户劝你考公", "label": "X", "topic_id": 37, "sent": False}]
    t = {"first": [], "rd": {"items": []}, "ship": {"done": False, "next": driver.item("ship", "note:1", "拍「接了一单咨询」")},
         "days": [{"ship": "pending", "dm": "ok", "xr": "ok"}], "dm": {}, "xr": {}, "wrap": [], "out": {"mode": None, "cells": cells}}
    ask = driver.now_item(t)
    assert ask["inputs"] == "mode" and "发不发新视频" in ask["text"]  # 早上先问
    fill = driver.now_item({**t, "out": {"mode": "backfill", "cells": cells, "need": 4}})
    assert fill["inputs"] == "bw" and "1 格没发出去" in fill["text"] and "X" in fill["text"]  # 去补发工作台
    sent = [{**c, "sent": True} for c in cells]
    assert "再挑 2 格" in driver.now_item({**t, "out": {"mode": "backfill", "cells": sent, "need": 4}})["text"]
    assert "挑 4 格" in driver.now_item({**t, "out": {"mode": "backfill", "cells": [], "need": 4, "left": 71}})["text"]
    assert driver.now_item({**t, "out": {"mode": "backfill", "cells": cells, "running": True}})["text"] == "补发工作台正在一格一格发"
    # 还没挑也先问：旧内容还有，就有补发这条路
    assert driver.now_item({**t, "out": {"mode": None, "cells": [], "left": 71}})["inputs"] == "mode"
    assert driver.now_item({**t, "out": {"mode": "new", "cells": cells}})["text"] == "拍「接了一单咨询」"
    assert driver.now_item({**t, "out": {"mode": None, "cells": []}})["text"] == "拍「接了一单咨询」"  # 没有能补的：只有一条路
    # 补发的格子都发完了：今天算出摊，不再让他去拍
    assert driver.now_item({**t, "days": [{"ship": "ok", "dm": "ok", "xr": "ok"}], "out": {"mode": "backfill", "cells": cells}}) is None


def test_on_the_positioning_page_she_gets_his_positioning_and_talks_direction() -> None:
    today_talk = wendy.compose("今天的账", [], "今晚不拍了")
    assert "<定位>" not in today_talk and "作者：今晚不拍了" in today_talk
    north_talk = wendy.compose("今天的账", [], "我到底卖什么", north="## 三、我卖给客户什么\n商业诊断，然后由我做出来。")
    assert north_talk.index("<定位>") < north_talk.index("<工作台>") and "商业诊断" in north_talk and "定方向模式" in north_talk
    assert "哪一问现在最不清楚" in wendy.compose("账", [], "", north="三问")  # 没说话点「让她看一眼」：说定位，不说今天做哪件


def test_a_reply_from_the_positioning_page_reaches_her_with_the_page(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert client.post("/api/wendy", json={"message": "我到底卖什么", "page": "positioning"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert card["error"] is None and [m["who"] for m in card["messages"][-2:]] == ["park", "wendy"]


def test_a_reply_from_any_other_page_reaches_her(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/9：Wendy 在左栏一直都在，咨询客户、汇总这些页也能问她。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    assert client.post("/api/wendy", json={"message": "这个客户下一步怎么收钱", "page": "other", "screen": "客户"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert card["error"] is None and [m["who"] for m in card["messages"][-2:]] == ["park", "wendy"]


def test_she_sees_what_is_on_his_screen_when_he_writes() -> None:
    """10/5：页面加了全网粉丝，问她看不看得到，她说看不到。他发消息时屏幕上那一页的字一起给她。"""
    seen = wendy.compose("今天的账", [], "你看得到全网粉丝吗", screen="全网粉丝 6,812\n\n\n\n预期月底粉丝数 7,040")
    assert "<他屏幕上这一页>\n全网粉丝 6,812\n\n预期月底粉丝数 7,040\n</他屏幕上这一页>" in seen
    assert seen.index("</工作台>") < seen.index("<他屏幕上这一页>") < seen.index("作者：")
    assert "<他屏幕上这一页>" not in wendy.compose("今天的账", [], "几点拍")  # 微信那边没有屏幕，就不带这一块
    assert len(wendy.compose("账", [], "看", screen="字" * 20000)) < wendy.SCREEN_MAX + 500
    assert "<他屏幕上这一页>" in wendy.system_prompt()  # 规则里告诉她这一块的数可以用

    users = []
    wendy.run_turn("账", [], "看得到吗", turn_fn=lambda system, user, sid: users.append(user) or {"text": "看得到"}, screen="全网粉丝 6,812")
    assert "全网粉丝 6,812" in users[0]


def test_the_follower_line_on_top_of_today_is_in_her_brief_too(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """微信那边的她没有屏幕，读的是 brief：「今天」页最上面那条全网粉丝也要在里面。"""
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    client.put("/api/followers", json={"platform": "xiaohongshu", "followers": 1200})
    brief = client.get("/api/wendy/brief").json()["text"]
    assert "[全网粉丝] 现在 1,200（小红书 1,200；" in brief
    assert client.post("/api/wendy", json={"message": "看得到吗", "screen": "全网粉丝 1,200"}).json()["started"]
    for _ in range(50):
        card = client.get("/api/wendy").json()
        if not card["busy"]:
            break
        time.sleep(0.05)
    assert card["error"] is None and card["messages"][-1]["who"] == "wendy"


def test_settings_page_lists_the_files_she_really_reads(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """「设置与 Skills」列的 Wendy 文件，就是她那一轮读的：角色文件每轮读，定位只在「我是谁」页。"""
    role = tmp_path / "Wendy.md"
    role.write_text("---\nx: 1\n---\n# Wendy\n\n只认出摊。", encoding="utf-8")
    monkeypatch.setenv(wendy.ROLE_ENV, str(role))
    soul = client.get("/api/wendy/soul").json()
    assert soul["files"][0]["name"] == "Wendy.md" and soul["files"][0]["when"] == "每一轮" and soul["files"][0]["exists"]
    assert soul["files"][1]["name"] == "positioning.md" and "我是谁" in soul["files"][1]["when"]
    assert "只认出摊" in wendy.system_prompt() and "只认出摊" in client.get("/api/wendy/soul/0").json()["body"]
    assert any("屏幕" in x for x in soul["also"]) and client.get("/api/wendy/soul/9").status_code == 400
    assert any("屏幕" in x for x in client.get("/api/anna/soul").json()["also"])


def test_wendy_is_the_owner_and_carries_the_kpis(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/12 作者：Wendy 是整个项目的负责人，背 KPI；Anna、Michael 先停用。没配角色文件时的兜底也这么说。"""
    monkeypatch.setenv(wendy.ROLE_ENV, str(tmp_path / "missing.md"))
    assert "负责人" in wendy.load_role()["text"] and "KPI" in wendy.load_role()["text"]
    rules = wendy.DESK_RULES
    assert "[战况]" in rules and "每 3 天" in rules and "不商量" in rules and "流量 CEO Anna" not in rules
