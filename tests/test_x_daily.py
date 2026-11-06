"""X 每日短帖（10/5 作者）：Wendy 前一晚排好，早上打勾，勾了的当天排着发；没勾的不发。"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_daily
from content_studio.x_post import XError
from test_x_line import client_factory  # noqa: F401 - fixture

BJ = x_daily.BJ
NOTE = "AI 会替代大部分脑力劳动，任何人挡不住历史的车轮。最终所有人都会走向金融市场加自媒体这两条路。"
SOURCES = [
    {"key": "obsidian", "label": "我写的", "items": [{"id": "003_原始输出/a.md", "title": "always-on", "body": NOTE, "at": "2026-07-01"},
                                                   {"id": "003_原始输出/b.md", "title": "旧的", "body": "慢就是快。", "at": "2026-06-01"}]},
    {"key": "principle", "label": "原则", "items": [{"id": "p1", "title": "万物逻辑", "body": "简单的事情重复做。"}]},
    {"key": "goodproduct", "label": "我测评的", "items": [{"id": "g1", "title": "别人的产品", "body": "别人的东西"}]},
]


def at(h: int, m: int = 0, day: int = 6) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=BJ)


def test_wendy_only_uses_his_own_words_and_code_drops_rewrites() -> None:
    cands = x_daily.candidates(SOURCES, avoid={"p1"})
    assert [c["id"] for c in cands] == ["003_原始输出/b.md", "003_原始输出/a.md"]  # 老的积压先排；别人的、放一边的不进来

    def model(prompt: str) -> str:
        assert "别人的东西" not in prompt and "不改词" in prompt
        return ("<<<POST source=1>>>\nAI 会替代大部分脑力劳动，任何人挡不住历史的车轮。\n<<<END>>>\n"
                "<<<POST source=1>>>\n同一个来源第二条，不要。\n<<<END>>>\n"
                "<<<POST source=0>>>\n守住贝塔就是胜利，这是我重新写的一句完全不同的话。\n<<<END>>>\n"
                "<<<POST source=9>>>\n越界\n<<<END>>>")

    posts = x_daily.build(cands, n=10, write_fn=model)
    assert [p["text"] for p in posts] == ["AI 会替代大部分脑力劳动，任何人挡不住历史的车轮。"]  # 改写的、重复来源的、越界的都扔掉，不凑数
    assert posts[0]["source_id"] == "003_原始输出/a.md"
    with pytest.raises(x_daily.DailyError, match="没排出来"):
        x_daily.build(cands, n=10, write_fn=lambda p: "<<<POST source=0>>>\n全是我编的新话新话新话新话。\n<<<END>>>")


def test_queue_spreads_approved_posts_over_the_whole_day() -> None:
    """10/13 作者「改成 24 小时，全天的」：0:00–24:00 都发（以前 9:00–22:00）。"""
    d = {"posts": [{"id": str(i), "state": "approved", "text": "t"} for i in range(10)], "halted": None}
    assert x_daily.next_at(d, at(7)) == "07:00" and x_daily.due(d, at(0))["id"] == "0"  # 半夜也发
    d["posts"][0].update(state="sent", sent_at=at(0).isoformat())
    assert x_daily.gap(at(0), 9) == timedelta(minutes=144)  # 剩 9 条：24 小时分成 10 段，最后一条也在 24:00 前
    assert x_daily.due(d, at(2)) is None and x_daily.next_at(d, at(2)) == "02:24"
    assert x_daily.due(d, at(2, 24))["id"] == "1"
    assert x_daily.gap(at(23, 50), 3) == x_daily.MIN_GAP  # 再紧也至少隔 MIN_GAP
    assert x_daily.gap(at(12), 1) == timedelta(hours=6)  # 只剩一条：12 点到 24 点的中间发
    assert x_daily.due(d, at(23, 59))["id"] == "1"  # 夜里照发
    d["halted"] = "429"
    assert x_daily.due(d, at(12)) is None and x_daily.next_at(d, at(12)) is None  # 额度用完：当天停


def test_tick_records_sending_before_calling_x_and_never_resends_after_restart(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    data = {"days": {"2026-10-06": {"posts": [{"id": "a", "state": "approved", "text": "第一条", "source_id": "s1"},
                                                {"id": "b", "state": "approved", "text": "第二条"},
                                                {"id": "c", "state": "pending", "text": "没勾的", "quote_url": "u"}], "halted": None}}}
    x_daily.save(p, data)
    recorded = []

    def post(text: str) -> dict:
        on_disk = next(x for x in x_daily.load(p)["days"]["2026-10-06"]["posts"] if x["text"] == text)
        assert on_disk["state"] == "sending"  # 先在盘上记「正在发」，再去调 X
        return {"url": "https://x.com/i/web/status/1"}

    row = x_daily.tick(p, post_fn=post, record_fn=recorded.append, now=at(9))
    assert row["state"] == "sent" and recorded == [row]
    assert x_daily.tick(p, post_fn=post, record_fn=recorded.append, now=at(9, 5)) is None  # 还没到下一条的时间

    def quota(text: str) -> dict:
        raise XError("X 说超额了（429）")

    assert x_daily.tick(p, post_fn=quota, record_fn=recorded.append, now=at(17))["state"] == "failed"
    assert x_daily.load(p)["days"]["2026-10-06"]["halted"]
    assert x_daily.tick(p, post_fn=post, record_fn=recorded.append, now=at(18)) is None  # 当天停了

    # 服务在「正在发」的时候重启：不知道 X 收没收到，标「不确定」，绝不再发一遍
    data = x_daily.load(p)
    data["days"]["2026-10-06"]["posts"][1].update(state="sending")
    assert x_daily.unsure_after_restart(data) and data["days"]["2026-10-06"]["posts"][1]["state"] == "unsure"
    assert next(x for x in data["days"]["2026-10-06"]["posts"] if x["id"] == "c")["state"] == "pending"  # 没勾的从来不发


def test_credits_depleted_pauses_without_burning_the_queue_and_resumes_after_top_up(tmp_path: Path) -> None:
    """10/12 15:37 起 X 回 402 credits depleted：以前一分钟一条，排着的全记成「没发成」。现在放回去、停发，每小时试一条。"""
    p = tmp_path / "x_daily.json"
    posts = [{"id": str(i), "state": "approved", "text": f"第{i}条"} for i in range(5)]
    posts.append({"id": "A", "state": "pending", "text": "# 长文", "long": True, "manual_publish": True})  # 他自己存草稿的长文
    x_daily.save(p, {"days": {"2026-10-06": {"posts": posts, "halted": None}}})
    calls = []

    def broke(text: str) -> dict:
        calls.append(text)
        raise XError("X API 余额用完了（402）：去 console.x.com 充值")

    def ok(text: str) -> dict:
        calls.append(text)
        return {"url": "https://x.com/i/web/status/1"}

    row = x_daily.tick(p, post_fn=broke, record_fn=lambda r: None, now=at(9))
    assert row["state"] == "approved" and not row.get("error")  # 不是这条的问题：放回去
    assert x_daily.load(p)["credits_out"]
    for m in (1, 2, 30, 59):
        assert x_daily.tick(p, post_fn=ok, record_fn=lambda r: None, now=at(9, m)) is None  # 一小时内不再试
    assert calls == ["第0条"]
    assert x_daily.view(p, now=at(9, 30))["credits_out"]  # 页面上告诉他去充值
    assert x_daily.tick(p, post_fn=ok, record_fn=lambda r: None, now=at(10, 1))["state"] == "sent"  # 一小时后自己再试，充了就发
    assert "credits_out" not in x_daily.load(p)
    assert {x["state"] for x in x_daily.load(p)["days"]["2026-10-06"]["posts"] if not x.get("long")} == {"sent", "approved"}  # 一条都没记成失败

    x_daily.set_credits_out(p, "X API 余额用完了（402）", now=at(11, 50))
    x_daily.mark_drafted(p, "2026-10-06", "A", "https://x.com/compose/articles", now=at(11, 55))  # 草稿存成了 = 有余额了
    assert "credits_out" not in x_daily.load(p)
    x_daily.set_credits_out(p, "X API 余额用完了（402）", now=at(12, 40))
    data = x_daily.load(p)
    data["days"]["2026-10-06"]["halted"] = "X API 余额用完了"
    x_daily.save(p, data)
    assert x_daily.tick(p, post_fn=ok, record_fn=lambda r: None, now=at(12, 50)) is None
    x_daily.resume(p, now=at(12, 45))  # 他点「充值好了，接着发」：不等一小时
    assert x_daily.tick(p, post_fn=ok, record_fn=lambda r: None, now=at(12, 50))["state"] == "sent"


def test_gap_follows_the_daily_target_not_just_what_is_queued_now() -> None:
    """10/13：短帖、Repost 白天陆续写出来，早上排着的少；按排着的摊，9 点发完 10 点才发。按每天的目标摊。"""
    d = {"posts": [{"id": "s", "state": "sent", "text": "t", "sent_at": at(9).isoformat()}]
         + [{"id": str(i), "state": "approved", "text": "t"} for i in range(5)], "halted": None}
    assert x_daily.next_at(d, at(9)) == "11:30"  # 只看排着的 5 条：隔 2 个半小时
    assert x_daily.next_at(d, at(9), target=200) == "09:04"  # 还要发 199 条：9:00 到 24:00 的 900 分钟 / 200 = 4.5 分钟
    assert x_daily.due(d, at(9, 4), target=200) is None and x_daily.due(d, at(9, 5), target=200)["id"] == "0"
    assert x_daily.gap(at(9), 199) >= x_daily.MIN_GAP == timedelta(minutes=3)


def test_next_day_carries_approved_and_expires_unticked() -> None:
    data = {"days": {"2026-10-06": {"posts": [{"id": "a", "state": "approved", "text": "勾了没发完"},
                                                {"id": "b", "state": "pending", "text": "没勾"}], "halted": "429"},
                     "2026-10-07": {"posts": [{"id": "n", "state": "pending", "text": "今天排的"}], "halted": None}}}
    assert x_daily.roll(data, "2026-10-07")
    today = data["days"]["2026-10-07"]["posts"]
    assert [x["text"] for x in today] == ["勾了没发完", "今天排的"] and today[0]["state"] == "approved"
    assert [x["state"] for x in data["days"]["2026-10-06"]["posts"]] == ["moved", "expired"]
    assert not x_daily.roll(data, "2026-10-07")  # 不会挪第二遍


def test_plan_tick_and_cross_on_the_page(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "always-on.md").write_text(f"# Always On\n{NOTE}", encoding="utf-8")
    (vault / "003_原始输出" / "beta.md").write_text("# beta\n慢就是快。", encoding="utf-8")

    def write(prompt: str) -> str:
        return ("<<<POST source=0>>>\nAI 会替代大部分脑力劳动，任何人挡不住历史的车轮。\n<<<END>>>\n"
                "<<<POST source=1>>>\n慢就是快。\n<<<END>>>")

    sent: list[str] = []
    client: TestClient = client_factory(write_fn=write, x_post_fn=lambda t: sent.append(t) or {"url": "https://x.com/i/web/status/9"},
                                        x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    assert client.put("/api/xline/counts", json={"own_short": 10, "long": 0}).status_code == 200  # 原话短帖 10/9 起默认关，这里打开测
    assert client.get("/api/xline/daily").json()["today"]["posts"] == []
    assert client.post("/api/xline/daily/plan", json={}).json()["started"] is True
    for _ in range(100):
        dd = client.get("/api/xline/daily").json()
        if not dd["planning"]:
            break
        time.sleep(0.05)
    assert dd["error"] is None and len(dd["today"]["posts"]) == 2 and dd["today"]["pending"] == 0  # 10/12 起短帖不过 QA，排好就是勾好的
    key = dd["today"]["day"]
    first, second = dd["today"]["posts"]
    assert not sent  # 排好了，还没到发的时间

    r = client.patch(f"/api/xline/daily/{key}/{second['id']}", json={"state": "rejected"}).json()
    assert r["post"]["state"] == "rejected" and second["source_id"] in client.get("/api/xline").json()["skipped"]  # 打叉：Wendy 以后不再排它
    assert client.patch(f"/api/xline/daily/{key}/{first['id']}", json={"text": "长" * 141}).status_code == 400
    client.patch(f"/api/xline/daily/{key}/{first['id']}", json={"text": "改过的：AI 会替代大部分脑力劳动。"})
    assert client.post(f"/api/xline/daily/{key}/approve-all").json() == {"approved": 1, "left": 0}

    row = x_daily.tick(x_daily.path(), post_fn=lambda t: sent.append(t) or {"url": "u"}, record_fn=lambda r: None,
                       now=datetime.fromisoformat(f"{key}T10:00:00+08:00"))
    assert sent == ["改过的：AI 会替代大部分脑力劳动。"] and row["state"] == "sent"  # 发的是他改过的那句
    stored = json.loads(x_daily.path().read_text(encoding="utf-8"))
    assert stored["days"][key]["posts"][1]["state"] == "rejected"


# -- 长帖（10/7 作者，#505）：原始输出整篇搬，不经过模型；早上勾了才发 ---------------------------------

LONG_BODY = "## 小标题\n\n" + "**闭环**比终局更重要。" * 40  # 去掉记号后 400 多字
LONG_SOURCES = [{"key": "obsidian", "label": "我写的", "items": [
    {"id": "003/已发 2026-09-02__新的.md", "title": "已发 2026-09-02__新的", "body": "截断过的", "at": "2026-09-02"},
    {"id": "003/旧的.md", "title": "旧的", "body": "截断过的", "at": "2026-07-01"},
    {"id": "003/客户咨询1.md", "title": "客户咨询1", "body": "x", "at": "2026-10-01"},
    {"id": "003/每日交易分析/260904.md", "title": "260904", "body": "x", "at": "2026-09-04"},
    {"id": "003/短的.md", "title": "短的", "body": "x", "at": "2026-08-01"},
    {"id": "003/发过的.md", "title": "发过的", "body": "x", "at": "2026-09-30"},
]}]
FULL = {"003/已发 2026-09-02__新的.md": LONG_BODY, "003/旧的.md": LONG_BODY, "003/短的.md": "只有一句话。",
        "003/客户咨询1.md": LONG_BODY, "003/每日交易分析/260904.md": LONG_BODY, "003/发过的.md": LONG_BODY}


def test_long_posts_move_whole_notes_word_for_word_newest_first() -> None:
    assert x_daily.long_title("已发 2026-09-02__AI Demystified：一键生成") == "AI Demystified：一键生成"
    assert x_daily.long_title("260907_口播稿_半年前的AI使用") == "半年前的AI使用"
    assert x_daily.long_title("20260717-芯片存储暴跌") == "芯片存储暴跌"
    assert x_daily.long_title("A股AI硬件与存储ETF组合研究_2026-06-28") == "A股AI硬件与存储ETF组合研究"
    assert x_daily.long_title("口播稿：半年前的 AI 使用和今天的区别（9月7日录音）") == "半年前的 AI 使用和今天的区别（9月7日录音）"

    longs = x_daily.long_candidates(LONG_SOURCES, avoid={"003/发过的.md"}, read_full=FULL.__getitem__)
    # 客户的、每日盘面、太短的、发过的都不排；新写的在前；读的是整篇，不是素材卡里截断的那段
    assert [x["source_id"] for x in longs] == ["003/已发 2026-09-02__新的.md", "003/旧的.md"]
    from content_studio.extras.xline.x_line import plain
    assert longs[0]["text"] == "新的\n\n" + plain(LONG_BODY) and longs[0]["long"] is True
    assert "**" not in longs[0]["text"] and "##" not in longs[0]["text"]
    huge = {**FULL, "003/旧的.md": "长" * 13_000}
    assert [x["source_id"] for x in x_daily.long_candidates(LONG_SOURCES, avoid=set(), read_full=huge.__getitem__, n=9)
            if x["source_id"] == "003/旧的.md"] == []  # 超过 X 长帖上限的不排


def test_notes_that_stop_mid_thought_are_not_offered_as_long_articles() -> None:
    # 10/12 作者：「复杂的工作流」那篇最后一点只有个标题，发出去读者看到的是讲到一半
    for tail in ("最后就是复杂的工作流。", "然后第四个。", "第三，就是做自己：", "后面再说…"):
        assert x_daily.unfinished_tail(LONG_BODY + "\n\n" + tail) is True, tail
    for tail in ("好，peace.", "Okay, peace.", "所以先完成闭环，再往上叠业务架构。"):
        assert x_daily.unfinished_tail(LONG_BODY + "\n\n" + tail) is False, tail
    assert x_daily.unfinished_tail(LONG_BODY + "\n\n最后就是复杂的工作流，我原来做了很多，最后发现自己也用不起来，因为它太复杂了。") is False
    cut = {**FULL, "003/旧的.md": LONG_BODY + "\n\n最后就是复杂的工作流。"}
    assert [x["source_id"] for x in x_daily.long_candidates(LONG_SOURCES, avoid={"003/发过的.md"}, read_full=cut.__getitem__, n=9)] \
        == ["003/已发 2026-09-02__新的.md"]


def test_plan_adds_long_posts_spread_out_and_once_even_if_shorts_exist(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    key = "2026-10-08"
    x_daily.save(p, {"days": {key: {"posts": [{"id": f"s{i}", "state": "pending", "text": "短"} for i in range(4)],
                                    "planned_at": "x", "halted": None}}})

    def no_model(prompt: str) -> str:
        raise AssertionError("短帖排过了，长帖不经过模型")

    d = x_daily.plan(p, key, sources=LONG_SOURCES, posted={"003/发过的.md"}, skipped=set(), write_fn=no_model, read_full=FULL.__getitem__)
    assert [x["id"] for x in d["posts"]] == ["s0", f"{key}-L0", "s1", "s2", f"{key}-L1", "s3"]  # 平均插开，不扎堆
    assert all(x["state"] == "pending" for x in d["posts"]) and d["long_planned_at"]
    again = x_daily.plan(p, key, sources=LONG_SOURCES, posted=set(), skipped=set(), write_fn=no_model, read_full=FULL.__getitem__)
    assert len(again["posts"]) == 6  # 排过的不重排

    assert x_daily.plan_due(p, now=datetime(2026, 10, 7, 21, 0, tzinfo=BJ)) is None
    x_daily.save(p, {"days": {key: {"posts": [{"id": "s0", "state": "pending", "text": "短"}], "halted": None}}})
    assert x_daily.plan_due(p, now=datetime(2026, 10, 7, 21, 0, tzinfo=BJ)) == key  # 长帖还没排：晚上补排


def test_long_articles_need_to_be_ready_and_ticked_then_go_out_as_an_article(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    text = "# 长文\n\n" + "字" * 2000
    x_daily.save(p, {"days": {"2026-10-06": {"posts": [{"id": "L", "state": "pending", "text": text, "long": True},
                                                        {"id": "old", "state": "approved", "text": "老的纯文字长帖", "long": True}],
                                              "halted": None}}})
    calls = []

    def post(t: str, **kw) -> dict:
        calls.append((t, kw.get("long"), (kw.get("post") or {}).get("id")))
        return {"url": "u"}

    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(10)) is None and not calls  # 没做好的、没勾的都不发
    with pytest.raises(x_daily.DailyError, match="做好了才能勾"):
        x_daily.mark(p, "2026-10-06", "L", state="approved")
    x_daily.set_post(p, "2026-10-06", "L", prep="ready", article=str(tmp_path / "a.md"))
    x_daily.mark(p, "2026-10-06", "L", state="approved", text=text + "\n\n" + "改" * 13_000)  # 长文改字不限 280、也不限 25000
    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(10))["state"] == "sent"
    assert calls == [(text + "\n\n" + "改" * 13_000, True, "L")]
    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(21)) is None  # 老的纯文字长帖勾了也不发


def test_page_plans_long_posts_from_the_vault_even_when_shorts_fail(client_factory, tmp_path: Path,  # noqa: F811
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "闭环.md").write_text(LONG_BODY, encoding="utf-8")
    client: TestClient = client_factory(write_fn=lambda prompt: "模型没按格式回", x_post_fn=lambda t, **kw: {"url": "u"},
                                        x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    client.post("/api/xline/daily/plan", json={})
    for _ in range(100):
        dd = client.get("/api/xline/daily").json()
        if not dd["planning"]:
            break
        time.sleep(0.05)
    posts = dd["today"]["posts"]
    assert dd["error"] and [x["long"] for x in posts] == [True]  # 短帖没排出来，长帖照样留着等他勾
    assert posts[0]["text"].startswith("闭环\n\n") and posts[0]["state"] == "pending" and dd["today"]["long_planned_at"]


def test_long_posts_are_planned_seven_days_ahead_without_repeating_a_note(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    items = [{"id": f"003/{i}.md", "title": f"第{i}篇", "body": "截断过的", "at": f"2026-09-{10 + i:02d}"} for i in range(10)]
    sources = [{"key": "obsidian", "label": "我写的", "items": items}]
    full = {c["id"]: LONG_BODY for c in items}
    now = datetime(2026, 10, 7, 10, 0, tzinfo=BJ)
    due = x_daily.long_days_due(p, now=now)
    assert due == [f"2026-10-{d:02d}" for d in range(8, 15)]  # 明天起 7 天，今天不自己排

    def no_model(prompt: str) -> str:
        raise AssertionError("只排长帖，不叫模型")

    for key in due:
        x_daily.plan(p, key, sources=sources, posted=set(), skipped=set(), write_fn=no_model, read_full=full.__getitem__, short=False)
    days = x_daily.load(p)["days"]
    used = [x["source_id"] for k in due for x in days[k]["posts"]]
    assert len(used) == len(set(used)) == 10  # 10 篇排完就没了，不重复；后面的日子排过但是空的
    assert [len(days[k]["posts"]) for k in due] == [3, 3, 3, 1, 0, 0, 0]
    assert x_daily.long_days_due(p, now=now) == []  # 空的也算排过，不会每分钟重试
    assert x_daily.plan_due(p, now=datetime(2026, 10, 7, 21, 0, tzinfo=BJ)) == "2026-10-08"  # 明天的短帖晚上照样排

    v = x_daily.view(p, now=now)
    assert [t["day"] for t in v["ahead"]] == ["2026-10-09", "2026-10-10", "2026-10-11"]  # 后天往后、有东西的


# -- 10/8 作者（#525）：拍成视频的笔记不进长帖；「换一篇」 ---------------------------------------------

def _pool(n: int) -> tuple[list[dict], dict]:
    items = [{"id": f"obsidian:003/{i}.md", "title": f"第{i}篇", "body": "截断过的", "at": f"2026-09-{10 + i:02d}"} for i in range(n)]
    return [{"key": "obsidian", "label": "我写的", "items": items}], {c["id"]: LONG_BODY for c in items}


def test_swap_puts_the_next_note_in_place_and_video_notes_never_come_in(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    sources, full = _pool(5)
    key = "2026-10-08"
    video = {"obsidian:003/4.md"}  # 最新那篇拍成视频了
    d = x_daily.plan(p, key, sources=sources, posted=set(), skipped=set(), write_fn=lambda s: "", read_full=full.__getitem__,
                     short=False, n_long=2, long_avoid=video)
    assert [x["source_id"] for x in d["posts"]] == ["obsidian:003/3.md", "obsidian:003/2.md"]

    x_daily.mark(p, key, f"{key}-L0", state="rejected")
    row = x_daily.swap_long(p, key, f"{key}-L0", sources=sources, avoid=video, read_full=full.__getitem__)  # 打过叉的也能换
    posts = x_daily.load(p)["days"][key]["posts"]
    assert [x["id"] for x in posts] == [f"{key}-L0", row["id"], f"{key}-L1"]  # 新的顶在原位置
    assert row["source_id"] == "obsidian:003/1.md" and row["state"] == "pending" and posts[0]["swapped"]
    with pytest.raises(x_daily.DailyError, match="换掉了"):
        x_daily.mark(p, key, f"{key}-L0", state="pending")  # 换掉的不能再撤回成要发
    with pytest.raises(x_daily.DailyError, match="换过了"):
        x_daily.swap_long(p, key, f"{key}-L0", sources=sources, avoid=video, read_full=full.__getitem__)

    x_daily.swap_long(p, key, row["id"], sources=sources, avoid=video, read_full=full.__getitem__)  # 换到 0 号
    last = next(x for x in x_daily.load(p)["days"][key]["posts"] if x["state"] == "pending" and x["source_id"] != "obsidian:003/2.md")
    with pytest.raises(x_daily.DailyError, match="没有能换的了"):
        x_daily.swap_long(p, key, last["id"], sources=sources, avoid=video, read_full=full.__getitem__)


def test_planned_long_posts_whose_note_became_a_video_are_swapped_unless_he_ticked_them(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    sources, full = _pool(4)
    x_daily.save(p, {"days": {
        "2026-10-07": {"posts": [{"id": "old", "long": True, "state": "pending", "source_id": "obsidian:003/0.md", "text": "t"}]},
        "2026-10-09": {"posts": [{"id": "a", "long": True, "state": "pending", "source_id": "obsidian:003/0.md", "text": "t"},
                                 {"id": "b", "long": True, "state": "approved", "source_id": "obsidian:003/1.md", "text": "t"},
                                 {"id": "c", "long": True, "state": "pending", "source_id": "obsidian:003/2.md", "text": "t"}]}}})
    video = {"obsidian:003/0.md", "obsidian:003/1.md"}
    now = datetime(2026, 10, 8, 10, tzinfo=BJ)
    assert x_daily.video_note_posts(p, video, now=now) == [("2026-10-09", "a")]  # 过去的不管；他勾过的不动
    row = x_daily.swap_long(p, "2026-10-09", "a", sources=sources, avoid=video, read_full=full.__getitem__,
                            reason="拍成视频了，换了一篇", allow_empty=True)
    assert row["source_id"] == "obsidian:003/3.md" and row["note"] == "拍成视频了，换了一篇"
    assert x_daily.video_note_posts(p, video, now=now) == []


def test_swap_on_the_page_sets_the_old_note_aside(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    for name in ("甲", "乙"):
        (vault / "003_原始输出" / f"{name}.md").write_text(LONG_BODY, encoding="utf-8")
    client: TestClient = client_factory(write_fn=lambda prompt: "不按格式", x_post_fn=lambda t, **kw: {"url": "u"},
                                        x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [{"id": f"{key}-L0", "long": True, "state": "pending", "text": "甲\n\n…",
                                                             "source_id": "obsidian:003_原始输出/甲.md"}],
                                                 "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    r = client.post(f"/api/xline/daily/{key}/{key}-L0/swap").json()
    assert r["post"]["source_id"] == "obsidian:003_原始输出/乙.md" and r["post"]["text"].startswith("乙\n\n")
    assert "obsidian:003_原始输出/甲.md" in client.get("/api/xline").json()["skipped"]
    assert client.post(f"/api/xline/daily/{key}/{r['post']['id']}/swap").status_code == 400  # 池子空了


def test_video_notes_are_held_thirty_days_from_the_latest_topic_then_come_back() -> None:
    now = datetime(2026, 10, 8, 12, tzinfo=BJ)
    topics = [{"created_at": "2026-09-20T09:00:00+00:00", "note_paths": ["003/旧视频.md"]},
              {"created_at": "2026-10-05T09:00:00+00:00", "note_paths": ["003/新视频.md"]},
              {"created_at": "2026-08-01T00:00:00+00:00", "note_paths": ["003/又拍了一次.md"]},
              {"created_at": "2026-10-01T00:00:00+00:00", "note_paths": ["003/又拍了一次.md"]},
              {"created_at": None, "note_paths": ["003/读不出时间.md"]}]
    assert x_daily.held_video_notes(topics, now=now) == {"obsidian:003/旧视频.md", "obsidian:003/新视频.md",  # 9/20 建的还不满 30 天
                                                         "obsidian:003/又拍了一次.md", "obsidian:003/读不出时间.md"}  # 按最近那次算
    assert "obsidian:003/旧视频.md" not in x_daily.held_video_notes(topics, now=datetime(2026, 10, 21, tzinfo=BJ))
    assert x_daily.held_video_notes(topics, now=datetime(2026, 11, 5, tzinfo=BJ)) == {"obsidian:003/读不出时间.md"}  # 30 天后回到池子


# -- 10/8 作者（#537）：长文 = park-writing 改一遍 + 个人形象插图 + 他勾了发成 X 图文文章 -----------------------

NOTE_LONG = "我觉得闭环比终局更重要。终局大家都看得到，但是短期做不到。所以小闭环先闭，大闭环后闭。" * 6
SUMMARY = ("我在 2026 年 4 月 30 号写下这篇文章。那时候我在想，终局大家都看得到，但是短期做不到，"
           "所以一直在琢磨到底先做什么。这篇总结的就是一句话：小闭环先闭，大闭环后闭，闭环比终局更重要。")


def long_model(prompt: str) -> str:
    """长文的两次调用：改写正文、写开头那段 summary。"""
    if "<<<SUMMARY>>>" in prompt:
        return f"<<<SUMMARY>>>\n{SUMMARY}\n<<<END>>>"
    return "<<<ARTICLE>>>\n# 闭环\n\n" + NOTE_LONG + "\n<<<END>>>"


def test_long_article_keeps_his_words_and_gets_illustrated(tmp_path: Path) -> None:
    from content_studio.extras.xline import x_long

    def model(prompt: str) -> str:
        if "<<<SUMMARY>>>" in prompt:
            assert "第一人称" in prompt and "我在 2026 年 4 月 30 号写下这篇文章" in prompt and "PokeeSE 录音转写" in prompt
            return f"<<<SUMMARY>>>\n{SUMMARY}\n<<<END>>>"
        assert "park-writing" in prompt and "不改词" in prompt and NOTE_LONG in prompt
        return "<<<ARTICLE>>>\n# 闭环\n\n" + NOTE_LONG.replace("我觉得", "") + "\n<<<END>>>"

    def draw(path: Path) -> None:
        (path.parent / "illustrations").mkdir()
        (path.parent / "illustrations" / "01-loop.png").write_bytes(b"png")
        path.write_text(path.read_text(encoding="utf-8") + "\n![闭环](illustrations/01-loop.png)\n", encoding="utf-8")

    text, path, when = x_long.prepare({"id": "2026-10-09-L0", "source_id": "obsidian:003/已发 闭环.md"}, NOTE_LONG,
                                      write_fn=model, illustrate_fn=draw, root=tmp_path,
                                      meta={"date": "2026-04-30 14:55", "source": "PokeeSE 录音转写"})
    assert text.startswith("# 闭环\n\n" + SUMMARY + "\n\n") and "![闭环](illustrations/01-loop.png)" in text  # summary 是第一段
    assert str(when) == "2026-04-30"
    assert path == tmp_path / "x_long" / "2026-10-09-L0" / "article.md"
    with pytest.raises(x_long.LongError, match="改动太多"):
        x_long.write("闭环", NOTE_LONG, write_fn=lambda p: "<<<ARTICLE>>>\n# 闭环\n\n" + "完全是另外一套说法，模型自己写的新东西。" * 20 + "\n<<<END>>>")


def test_prep_goes_today_first_then_tomorrow_and_skips_done_ones(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    x_daily.save(p, {"days": {
        "2026-10-08": {"posts": [{"id": "t-short", "state": "pending", "text": "短"},
                                 {"id": "t-done", "long": True, "state": "pending", "prep": "ready", "text": "x"},
                                 {"id": "t-no", "long": True, "state": "rejected", "text": "x"}]},
        "2026-10-09": {"posts": [{"id": "m-0", "long": True, "state": "pending", "text": "x"}]},
        "2026-10-10": {"posts": [{"id": "later", "long": True, "state": "pending", "text": "x"}]}}})
    now = datetime(2026, 10, 8, 9, tzinfo=BJ)
    assert x_daily.prep_next(p, now=now)[1]["id"] == "m-0"  # 今天的做完了或打了叉；后天的先不做
    x_daily.set_post(p, "2026-10-09", "m-0", prep="running")
    assert x_daily.prep_next(p, now=now)[1]["id"] == "m-0"  # 做到一半服务重启了：接着做
    x_daily.set_post(p, "2026-10-09", "m-0", prep="failed")
    assert x_daily.prep_next(p, now=now) is None  # 没做成的等他点重做


def test_page_prepares_previews_redoes_and_publishes_long_articles(client_factory, tmp_path: Path,  # noqa: F811
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio.extras.xline import x_article

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "闭环.md").write_text("---\ndate: 2026-04-30 14:55\n---\n" + NOTE_LONG, encoding="utf-8")

    def draw(path: Path) -> None:
        (path.parent / "illustrations").mkdir(exist_ok=True)
        (path.parent / "illustrations" / "01-loop.png").write_bytes(b"png-bytes")
        path.write_text(path.read_text(encoding="utf-8") + "\n![闭环](illustrations/01-loop.png)\n", encoding="utf-8")

    client: TestClient = client_factory(write_fn=long_model, x_illustrate_fn=draw, x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    pid = f"{key}-L0"
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [{"id": pid, "long": True, "state": "pending", "text": "原文",
                                                             "source_id": "obsidian:003_原始输出/闭环.md"}],
                                                 "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    assert client.patch(f"/api/xline/daily/{key}/{pid}", json={"state": "approved"}).status_code == 400  # 还没做好

    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    post = client.get("/api/xline/daily").json()["today"]["posts"][0]
    assert post["prep"] == "ready" and post["text"].startswith("# 闭环") and "illustrations/01-loop.png" in post["text"], post.get("prep_error")
    assert post["text"].split("\n\n")[1] == SUMMARY and post["written_on"] == "2026-04-30"  # 第一段是带日期的 summary
    assert client.get(f"/api/xline/daily/{key}/{pid}/file/illustrations/01-loop.png").content == b"png-bytes"
    assert client.get(f"/api/xline/daily/{key}/{pid}/file/%2E%2E/%2E%2E/x_daily.json").status_code == 404  # 只读这一篇自己的文件夹

    assert client.patch(f"/api/xline/daily/{key}/{pid}", json={"state": "approved"}).status_code == 200
    published = []
    monkeypatch.setattr(x_article, "publish_article",
                        lambda article, publish, cover=None: published.append((article.read_text(encoding="utf-8"), publish))
                        or {"published": True, "url": "https://x.com/i/web/status/7"})
    edited = post["text"] + "\n他自己加的一句。\n"
    assert client.app.state.x_send(edited, long=True, post={**post, "article": post["article"]}) == {"url": "https://x.com/i/web/status/7"}
    assert published == [(edited, True)]  # 发的是他改过的那版，发成图文文章

    r = client.post(f"/api/xline/daily/{key}/{pid}/prep").json()["post"]
    assert r["prep"] is None and r["state"] == "pending"  # 重做：排回去，勾要重新打



# -- 10/9 作者（#564）：每篇长文开头一段 summary，第一句是写这篇的日期 -----------------------------------------


def test_written_date_comes_from_the_note_or_its_file_name_never_a_guess() -> None:
    from content_studio.extras.xline import x_long

    assert str(x_long.written_on("003/always-on.md", {"date": "2026-04-29 19:13"})) == "2026-04-29"
    assert str(x_long.written_on("003/x.md", {"created": "2026-10-05T00:52:54+00:00"})) == "2026-10-05"
    assert str(x_long.written_on("obsidian:003/交易/260511交易反思.md", {})) == "2026-05-11"
    assert str(x_long.written_on("003/A股ETF组合研究_2026-06-28.md", None)) == "2026-06-28"
    assert str(x_long.written_on("003/哲学20260225.md", {})) == "2026-02-25"
    assert x_long.written_on("003/发现自己.md", {"updated_at": "2026-07-14"}) is None  # 不知道就是不知道
    assert x_long.cn_date(x_long.written_on("003/x.md", {"date": "2024-03-25"})) == "2024 年 3 月 25 号"


def test_summary_is_first_person_dated_and_only_says_what_the_note_says() -> None:
    from datetime import date

    from content_studio.extras.xline import x_long

    when = date(2026, 4, 30)
    assert x_long.check_summary(SUMMARY, NOTE_LONG, when) is None
    assert "第一句" in x_long.check_summary(SUMMARY.replace("我在 2026 年 4 月 30 号", "作者 在 2026 年 4 月 30 号"), NOTE_LONG, when)
    assert "亏损" in x_long.check_summary(SUMMARY.replace("所以一直在琢磨", "当时刚经历一波亏损，所以一直在琢磨"), NOTE_LONG, when)
    assert "数字" in x_long.check_summary(SUMMARY.replace("这篇总结", "花了 75 万之后这篇总结"), NOTE_LONG, when)
    assert "日期" in x_long.check_summary("写这篇文章的时候是 4 月 30 号，" + SUMMARY[20:], NOTE_LONG, None)
    assert "一段话" in x_long.check_summary(SUMMARY + "\n\n第二段", NOTE_LONG, when)
    calls = []

    def model(prompt: str) -> str:
        calls.append(prompt)
        bad = SUMMARY.replace("我在", "作者在")
        return f"<<<SUMMARY>>>\n{bad if len(calls) == 1 else SUMMARY}\n<<<END>>>"

    assert x_long.summarize("闭环", NOTE_LONG, when=when, context="", write_fn=model) == SUMMARY  # 不过关就带着问题重写一次
    assert "上一次有问题" in calls[1]
    assert x_long.with_summary("# 闭环\n\n正文第一段\n\n正文第二段\n", SUMMARY) == f"# 闭环\n\n{SUMMARY}\n\n正文第一段\n\n正文第二段\n"


def test_ready_unticked_articles_get_the_summary_added_without_redoing_images(client_factory, tmp_path: Path,  # noqa: F811
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "闭环.md").write_text("---\ndate: 2026-04-30 14:55\n---\n" + NOTE_LONG, encoding="utf-8")
    client: TestClient = client_factory(write_fn=long_model, x_illustrate_fn=lambda p: pytest.fail("不重新配图"),
                                        x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    art = tmp_path / "article.md"
    old = "# 闭环\n\n正文\n\n![图](illustrations/01.png)\n"
    art.write_text(old, encoding="utf-8")
    base = {"long": True, "prep": "ready", "text": old, "article": str(art), "source_id": "obsidian:003_原始输出/闭环.md"}
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [{**base, "id": "a", "state": "approved"}, {**base, "id": "p", "state": "pending"}],
                                                 "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    job = x_daily.summary_next(x_daily.path())
    assert job[1]["id"] == "p"  # 勾过的那篇不动：那是他看过的版本
    client.app.state.x_long_add_summary(*job)
    post = next(x for x in client.get("/api/xline/daily").json()["today"]["posts"] if x["id"] == "p")
    assert post["text"] == f"# 闭环\n\n{SUMMARY}\n\n正文\n\n![图](illustrations/01.png)\n" and post["written_on"] == "2026-04-30"
    assert art.read_text(encoding="utf-8") == post["text"] and x_daily.summary_next(x_daily.path()) is None


def test_rewrite_summary_swaps_only_that_paragraph(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from content_studio.extras.xline import x_long

    assert x_long.replace_summary("# 闭环\n\n旧 summary\n\n正文\n", "新 summary") == "# 闭环\n\n新 summary\n\n正文\n"
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "闭环.md").write_text("---\ndate: 2026-04-30\n---\n" + NOTE_LONG, encoding="utf-8")  # 后来补上了日期
    client: TestClient = client_factory(write_fn=long_model, x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    art = tmp_path / "article.md"
    old = "# 闭环\n\n写这篇文章的时候，没有日期的旧 summary。\n\n正文\n\n![图](illustrations/01.png)\n"
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [{"id": "a", "long": True, "prep": "ready", "state": "approved", "text": old,
                                                             "summary": True, "written_on": None, "article": str(art),
                                                             "source_id": "obsidian:003_原始输出/闭环.md"},
                                                            {"id": "s", "state": "pending", "text": "短帖"}],
                                                 "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    post = client.post(f"/api/xline/daily/{key}/a/summary").json()["post"]
    assert post["text"] == f"# 闭环\n\n{SUMMARY}\n\n正文\n\n![图](illustrations/01.png)\n" and post["written_on"] == "2026-04-30"
    assert art.read_text(encoding="utf-8") == post["text"] and post["state"] == "approved"  # 正文、配图、勾都不动
    assert client.post(f"/api/xline/daily/{key}/s/summary").status_code == 400  # 短帖没有 summary
    # 就地改一段：页面把整篇存回来，长文不限 280 字
    edited = post["text"].replace("正文", "我自己改过的正文")
    assert client.patch(f"/api/xline/daily/{key}/a", json={"text": edited}).json()["post"]["text"] == edited.strip()



# -- 10/9 作者：每天发多少不写死；长的分长帖（短句合并）和长文两种测一周 ------------------------------------

LINES = ["在快速变化的世界中找到不变的东西，找到不用赌那么多的东西。", "人生的本质就是弄清楚最底层最简单的规则，然后不断重复。",
         "简单的事情重复做，用简单规则接触世界，让时间做朋友。", "量变产生质变，简单规则迭代足够久会长出复杂系统。",
         "慢就是快，复利需要时间。", "聪明人用笨方法做事情，找到比你聪明的人让他为你赚钱。"]
LINE_SOURCES = [{"key": "principle", "label": "原则", "items": [{"id": f"p{i}", "title": "万物逻辑", "body": b} for i, b in enumerate(LINES)]},
                {"key": "obsidian", "label": "我写的", "items": []}]


def test_counts_split_and_long_posts_merge_his_lines_by_theme(tmp_path: Path) -> None:
    assert x_daily.split_counts({"long": 10, "post_share": 0.5}) == (5, 5)
    assert x_daily.split_counts({"long": 3, "post_share": 0}) == (3, 0)
    items = x_daily.post_items(LINE_SOURCES, avoid={"p5"})
    assert [x["id"] for x in items] == ["p0", "p1", "p2", "p3", "p4"]

    def model(prompt: str) -> str:
        assert "<<<THEME" in prompt and "不改词" in prompt and "评论区" in prompt
        return ("<<<THEME title=简单规则重复做>>>\n" + "\n".join(f"[{i}] {items[i]['text']}" for i in (1, 2, 3, 0, 4)) + "\n<<<END>>>\n"
                "<<<THEME title=编的>>>\n[0] 这是模型自己编的一句完全不同的新话新话新话。\n<<<END>>>")

    posts = x_daily.build_long_posts(items, k=2, write_fn=model)
    assert len(posts) == 1  # 第二条改了词、条数不够：扔掉，不凑数
    p = posts[0]
    assert p["text"].startswith("简单规则重复做\n\n人生的本质") and p["format"] == "post" and p["prep"] == "ready"
    assert p["items"] == ["p1", "p2", "p3", "p0", "p4"]

    path = tmp_path / "x_daily.json"
    d = x_daily.plan(path, "2026-10-12", sources=LINE_SOURCES, posted=set(), skipped=set(), write_fn=model,
                     read_full=lambda s: "", short=False, n_long=0, n_post=1)
    assert [x["id"] for x in d["posts"]] == ["2026-10-12-P0"] and d["long_planned_at"]
    assert {"p0", "p1", "p2", "p3", "p4"} <= x_daily.recent_sources(x_daily.load(path), "2026-10-13")  # 合进去的短句两周内不再用
    assert x_daily.plan_due(path, now=datetime(2026, 10, 11, 21, tzinfo=BJ), own_short=0) is None  # 原话短帖关了：长的排了就算排完
    assert x_daily.prep_next(path, now=datetime(2026, 10, 12, 9, tzinfo=BJ)) is None  # 长帖不用改写配图


def test_long_posts_go_out_as_one_long_plain_post_and_counts_are_settings(client_factory, tmp_path: Path) -> None:  # noqa: F811
    sent = []
    client: TestClient = client_factory(x_fetch_fn=lambda url: [] if "manifest" in url else {})
    with pytest.raises(XError):  # 没有密钥：说明真的走到了发长帖那一步
        client.app.state.x_send("# 简单规则重复做\n\n第一句\n\n第二句", long=True, post={"format": "post"})
    from content_studio import x_post

    orig = x_post.post_tweet
    x_post.post_tweet = lambda text, **kw: sent.append((text, kw)) or {"url": "u"}
    try:
        client.app.state.x_send("# 简单规则重复做\n\n第一句", long=True, post={"format": "post"})
    finally:
        x_post.post_tweet = orig
    assert sent == [("简单规则重复做\n\n第一句", {"long": True})]

    assert client.get("/api/xline/daily").json()["counts"] == {"long": 0, "post_share": 0.67, "own_short": 100, "hot": 100, "articles": 4}
    r = client.put("/api/xline/counts", json={"long": 20, "post_share": 0.25, "hot": 20}).json()["counts"]
    assert r == {"long": 20, "post_share": 0.25, "own_short": 100, "hot": 20, "articles": 4}
    assert client.get("/api/xline/daily").json()["per_day_long"] == 20
    assert client.put("/api/xline/counts", json={"hot": 9999}).status_code == 400


# -- 10/9 作者：热点短帖——X 运营从持续在涨里挑他有观点的，写引用帖草稿；X 规则不许自动发热点，勾了才发 ---------------

LONG1 = "封号这事说明一件事：工具是租来的，能力才是你的。" * 6  # 长帖：够 HOT_MIN_CHARS
HOT_ITEMS = [{"url": "https://x.com/a/status/11", "title": "Claude 大面积封号", "text": "今天几十个朋友的 Claude 账号被封了", "author": "甲", "gained": 30000},
             {"url": "https://x.com/b/status/22", "title": "懂车帝刹车", "text": "三台车刹车踏板都断了", "author": "乙", "gained": 90000},
             {"url": "https://x.com/c/status/33", "title": "GPT-6 发布", "text": "OpenAI 发布 GPT-6，价格降了 80%", "author": "丙", "gained": 20000}]


def test_hot_drafts_only_where_he_has_a_view_no_bait_no_made_up_numbers() -> None:
    from content_studio.extras.xline import x_suggest

    def model(prompt: str) -> str:
        assert "慢就是快" in prompt and "不以问号结尾" in prompt and "八卦、社会新闻" in prompt
        return (f"<<<POST source=0>>>\n{LONG1}\n<<<END>>>\n"
                f"<<<POST source=1>>>\n{LONG1}刹车断了，你们怎么看？\n<<<END>>>\n"              # 引战：扔
                f"<<<POST source=2>>>\n{LONG1}降价 95% 才是真的拐点。\n<<<END>>>\n"           # 编数字：扔
                "<<<POST source=0>>>\n太短了不算长帖。\n<<<END>>>")
    report = {}
    drafts = x_daily.build_hot(HOT_ITEMS, n=5, style="短句，先下判断。", beliefs="慢就是快", write_fn=model,
                               check_fn=lambda t, it: x_suggest.check(t, it, limit=x_daily.MAX_LONG), report=report)
    assert [d["text"] for d in drafts] == [LONG1]
    d = drafts[0]  # 10/12：引用改回短的，不算长帖，过了 QA 自动发
    assert d["hot"] and not d.get("long") and d["quote_url"] == "https://x.com/a/status/11"
    assert report["found"] == 4 and len(report["drops"]) == 3 and any("95" in x for x in report["drops"])


def test_hot_batches_every_half_hour_up_to_the_daily_cap_and_expire_overnight(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    at9 = datetime(2026, 10, 9, 9, tzinfo=BJ)
    assert x_daily.hot_due(p, 30, now=datetime(2026, 10, 9, 23, 45, tzinfo=BJ)) == 0  # 23:30 以后不写（隔夜就作废）
    assert x_daily.hot_due(p, 30, now=at9) == x_daily.HOT_BATCH
    assert x_daily.hot_due(p, 0, now=at9) == 0  # 上限 0 = 不写
    x_daily.add_hot(p, "2026-10-09", [{"text": f"草稿{i}", "hot": True, "quote_url": f"https://x.com/a/status/{i}"} for i in range(8)],
                    [x["url"] for x in HOT_ITEMS], now=at9)
    assert x_daily.hot_due(p, 30, now=datetime(2026, 10, 9, 9, 20, tzinfo=BJ)) == 0  # 不到半小时
    assert x_daily.hot_due(p, 12, now=datetime(2026, 10, 9, 9, 31, tzinfo=BJ)) == 4   # 上限 12，已经 8 条
    assert x_daily.hot_seen(p, "2026-10-09") == {x["url"] for x in HOT_ITEMS}
    data = x_daily.load(p)
    data["days"]["2026-10-09"]["posts"][0]["state"] = "approved"
    x_daily.roll(data, "2026-10-10")
    assert {x["state"] for x in data["days"]["2026-10-09"]["posts"]} == {"expired"}  # 热点隔夜就凉了：勾了没发的也不挪
    assert "2026-10-10" not in data["days"] or not data["days"]["2026-10-10"]["posts"]


def test_ticked_hot_draft_goes_out_as_a_quote_post(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    x_daily.save(p, {"days": {"2026-10-06": {"posts": [{"id": "H0", "state": "approved", "text": "工具是租来的", "hot": True,
                                                        "quote_url": "https://x.com/a/status/11"}], "halted": None}}})
    calls = []
    row = x_daily.tick(p, post_fn=lambda t, **kw: calls.append((t, kw)) or {"url": "u"}, record_fn=lambda r: None, now=at(10))
    # 10/12：X API 不让带 quote_tweet_id，原帖链接贴在正文最后，当长帖发
    assert row["state"] == "sent" and calls[0][0] == "工具是租来的\n\nhttps://x.com/a/status/11" and calls[0][1]["long"] is True
    assert "quote_url" not in calls[0][1]


def test_quotes_blocked_by_x_become_one_tap_cards(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    posts = [{"id": f"H{i}", "state": "approved", "text": f"判断{i}", "hot": True, "long": True, "format": "post", "prep": "ready",
              "quote_url": f"https://x.com/a/status/{i}"} for i in range(2)]
    x_daily.save(p, {"days": {"2026-10-06": {"posts": posts, "halted": None}}})

    def blocked(t, **kw):
        raise XError('X 返回 403：{"detail":"You can only reply to or quote posts where you are mentioned or are the author."}')
    x_daily.tick(p, post_fn=blocked, record_fn=lambda r: None, now=at(10))
    v = x_daily.view(p, now=at(10))
    assert v["quotes_mode"] == "manual" and not v["today"].get("halted")
    assert [x["state"] for x in v["today"]["posts"]] == ["ready_manual", "ready_manual"]
    assert v["today"]["posts"][0]["intent_url"].startswith("https://x.com/intent/post?text=")
    assert x_daily.tick(p, post_fn=lambda *a, **k: pytest.fail("不该再调 X"), record_fn=lambda r: None, now=at(11)) is None
    assert x_daily.quote_handed(p, "2026-10-06", "H0", now=at(11))["state"] == "handed"
    x_daily.retry_quotes(p)
    assert x_daily.view(p, now=at(11))["quotes_mode"] == "api"
    assert [x["state"] for x in x_daily.load(p)["days"]["2026-10-06"]["posts"]] == ["handed", "approved"]


def test_page_writes_a_hot_batch_on_demand(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from content_studio.extras.xline import xhot

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "a.md").write_text("慢就是快。", encoding="utf-8")

    def write(prompt: str) -> str:
        if "总结他的说话" in prompt:
            return "# X 写作风格\n" + "短句，先下判断。" * 20
        return f"<<<POST source=0>>>\n{LONG1}\n<<<END>>>"

    monkeypatch.setattr(xhot.Board, "rising", lambda self, fresh=False: {"items": HOT_ITEMS})
    monkeypatch.setattr(xhot.Board, "get", lambda self, *a, **k: {"items": HOT_ITEMS[:1]})  # 和持续在涨重复的那条只看一次
    client: TestClient = client_factory(write_fn=write, x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    client.app.state.x_hot_batch(key, 5)
    dd = client.get("/api/xline/daily").json()
    hot = [x for x in dd["today"]["posts"] if x.get("hot")]
    assert [x["text"] for x in hot] == [LONG1] and hot[0]["state"] == "pending"  # 草稿，没勾不发
    assert dd["hot_error"] is None
    client.put("/api/xline/counts", json={"hot": 1})
    assert client.post("/api/xline/hot").json()["started"] is False  # 今天写满了



# -- 10/9 晚 作者：只留长帖和长文，每天 5 + 5；已经排好的补齐；长帖一天最多勾 5 篇（热点算在里面）；都要他勾 ------------


def test_topup_brings_planned_days_to_five_and_five_with_compilations_when_notes_run_out(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    key = "2026-10-11"
    x_daily.save(p, {"days": {key: {"posts": [{"id": f"{key}-L0", "long": True, "state": "approved", "text": "已经勾的长文", "source_id": "n0"},
                                              {"id": f"{key}-L1", "long": True, "state": "rejected", "text": "打叉的", "source_id": "n1"},
                                              {"id": f"{key}-0", "state": "pending", "text": "原话短帖"}],
                                    "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    assert x_daily.topup_due(p, [2, 1], now=datetime(2026, 10, 9, 10, tzinfo=BJ)) == [key]
    sources = [{"key": "principle", "label": "原则", "items": [{"id": f"q{i}", "title": "做自媒体", "body": f"做自媒体的第{i}条心得：先把一件事做到底。"}
                                                             for i in range(10)]}, {"key": "obsidian", "label": "我写的", "items": []}]
    items = x_daily.post_items(sources, avoid=set())

    def model(prompt: str) -> str:
        return "".join(f"<<<THEME title=做自媒体的第{k}组心得>>>\n" + "\n".join(f"[{i}] {items[i]['text']}" for i in range(k * 5, k * 5 + 5))
                       + "\n<<<END>>>\n" for k in range(2))

    d = x_daily.topup(p, key, sources=sources, avoid=set(), read_full=lambda s: "", write_fn=model, n_article=2, n_post=1)
    longs = [x for x in d["posts"] if x.get("long") and x["state"] in x_daily.ACTIVE]
    comp = [x for x in longs if x.get("compiled")]
    assert len([x for x in longs if x.get("format") != "post"]) == 2 and len([x for x in longs if x.get("format") == "post"]) == 1
    assert comp and comp[0]["text"].startswith("# 做自媒体的第") and "\n\n1. " not in comp[0]["text"] and comp[0]["prep"] is None  # 合集：连续段落，等配图
    assert all(x["state"] == "pending" for x in longs if x["id"] != f"{key}-L0")  # 新补的都要他勾
    assert x_daily.topup_due(p, [2, 1], now=datetime(2026, 10, 9, 10, tzinfo=BJ)) == []  # 补过了；打叉的不再补
    assert x_daily.cancel_shorts(p, "2026-10-09") == 1
    assert next(x for x in x_daily.load(p)["days"][key]["posts"] if x["id"] == f"{key}-0")["state"] == "expired"
    assert x_daily.summary_next(p, now=datetime(2026, 10, 11, 9, tzinfo=BJ)) is None  # 合集不写 summary


def test_at_most_five_long_posts_ticked_a_day_hot_ones_included(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    key = "2026-10-09"
    posts = [{"id": f"P{i}", "long": True, "format": "post", "prep": "ready", "state": "approved" if i < 4 else "pending", "text": "长帖"}
             for i in range(6)] + [{"id": "H0", "long": True, "format": "post", "prep": "ready", "hot": True, "state": "pending", "text": "热点长帖"},
                                   {"id": "A0", "long": True, "prep": "ready", "state": "pending", "text": "长文"}]
    x_daily.save(p, {"days": {key: {"posts": posts, "halted": None}}})
    x_daily.mark(p, key, "H0", state="approved", post_cap=5)  # 第 5 篇：热点那篇
    with pytest.raises(x_daily.DailyError, match="5 篇长帖已经勾满"):
        x_daily.mark(p, key, "P4", state="approved", post_cap=5)
    x_daily.mark(p, key, "A0", state="approved", post_cap=5)  # 长文不占长帖的名额
    x_daily.mark(p, key, "P0", state="rejected", post_cap=5)
    x_daily.mark(p, key, "P4", state="approved", post_cap=5)  # 叉掉一篇就能换一篇


def test_article_quota_pauses_only_articles_and_old_full_day_halts_are_narrowed(tmp_path: Path) -> None:
    """10/10：X 文章发布接口 429 了，当天不再发长文（不一遍遍建草稿），勾了的长帖照发；长文第二天接着发。"""
    p = tmp_path / "x_daily.json"
    art = lambda i: {"id": i, "long": True, "prep": "ready", "state": "approved", "text": f"# 长文{i}"}  # noqa: E731
    x_daily.save(p, {"days": {"2026-10-06": {"posts": [art("a1"), art("a2"),
                                                        {"id": "p1", "long": True, "format": "post", "prep": "ready", "state": "approved", "text": "长帖"}],
                                              "halted": None}}})
    sent = []

    def post(text: str, **kw) -> dict:
        if kw.get("post", {}).get("format") != "post":
            raise XError("X 没让直接发，已存草稿：X 说超额了（429），等额度恢复再发")
        sent.append(text)
        return {"url": "u"}

    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(9))["state"] == "failed"
    d = x_daily.load(p)["days"]["2026-10-06"]
    assert d["articles_paused"] and not d["halted"]
    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(21, 59))["id"] == "p1" and sent == ["长帖"]
    assert x_daily.tick(p, post_fn=post, record_fn=lambda r: None, now=at(21, 59)) is None  # 剩下的长文今天不发了

    # 第二天：勾了没发的长文挪过来，照常发
    data = x_daily.load(p)
    assert x_daily.roll(data, "2026-10-07")
    moved = [x for x in data["days"]["2026-10-07"]["posts"] if x["state"] == "approved"]
    assert [x["carried_from"] for x in moved] == ["2026-10-06"] and not data["days"]["2026-10-07"].get("articles_paused")

    # 10/10 之前的那种：长文被限把一整天停了 → 改成只停长文
    data = {"days": {"2026-10-07": {"posts": [], "halted": "X 没让直接发，已存草稿：X 说超额了（429）"}}}
    assert x_daily.roll(data, "2026-10-07")
    assert data["days"]["2026-10-07"]["halted"] is None and data["days"]["2026-10-07"]["articles_paused"]


def test_shorts_top_up_to_fifty_before_eleven_pm_in_batches(tmp_path: Path) -> None:
    """10/12 作者：短帖每天 50 条。晚上一次最多排 25，白天 20:00 前补到数；一篇笔记可以出几条，和发过的意思不能重复。"""
    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    words = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黄宇宙洪荒日月"
    import random
    line = lambda i, j: "".join(random.Random(i * 100 + j).choices(words, k=16)) + "。"  # noqa: E731 - 每条都不一样
    notes = [{"id": f"003/{i}.md", "title": f"笔记{i}", "body": line(i, 0) + line(i, 1), "at": f"2026-07-{i + 1:02d}"} for i in range(30)]
    sources = [{"key": "obsidian", "label": "我写的", "items": notes}]
    x_daily.save(p, {"days": {key: {"posts": [{"id": f"{key}-0", "text": line(0, 0), "state": "sent"}], "planned_at": "2026-10-11T21:00:00+08:00"}}})
    now = datetime(2026, 10, 12, 9, 0, tzinfo=BJ)
    assert x_daily.short_topup_due(p, 50, now=now) == 49
    asked = []

    def model(prompt: str) -> str:
        asked.append(prompt)
        assert line(0, 0) in prompt  # 发过的给模型看，别重复
        return "".join(f"<<<POST source={i}>>>\n{line(int(i), 1)}\n<<<END>>>\n" for i in range(30))

    made = x_daily.topup_shorts(p, key, sources=sources, skipped=set(), posted={"003/0.md"}, write_fn=model, n=49, now=now)
    assert made == 25  # 一次最多 25
    d = x_daily.load(p)["days"][key]
    assert x_daily.short_count(d) == 26 and all(x["state"] == "pending" for x in d["posts"][1:])
    assert x_daily.short_topup_due(p, 50, now=now + timedelta(minutes=5)) == 0  # 10 分钟内不再补
    assert x_daily.short_topup_due(p, 50, now=now + timedelta(minutes=11)) == 24
    assert x_daily.short_topup_due(p, 50, now=datetime(2026, 10, 12, 23, 1, tzinfo=BJ)) == 0  # 10/13 起全天发：23:00 前补
    # 全是重复的：一条都补不出来，连续两轮就停
    for _ in range(2):
        x_daily.topup_shorts(p, key, sources=sources, skipped=set(), posted=set(), write_fn=model, n=24, now=now + timedelta(minutes=30))
    assert x_daily.short_topup_due(p, 50, now=now + timedelta(hours=2)) == 0


def test_weak_long_posts_hide_and_get_merged_into_one(tmp_path: Path) -> None:
    """10/12 作者：价值、完整度不够的不给他看；2–3 篇找共同主题拼一篇顶上，拼的再不过就不再拼。"""
    from content_studio import rawtidy

    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    para = lambda tag: f"{tag}这一段讲的是做内容要先展示结果再讲方法，没人关心方法论，大家只关心你做到了什么，这是{tag}的原话。"  # noqa: E731
    posts = [{"id": f"{key}-L{i}", "text": f"# 第{i}篇\n\n{para(i)}", "long": True, "format": "post", "prep": "ready", "state": "pending",
              "qa": "ready", "qa_value_ok": False, "qa_complete": True, "source_id": f"obsidian:003/{i}.md"} for i in range(3)]
    posts.append({**posts[0], "id": f"{key}-L9", "qa_value_ok": False, "qa_value_override": True})  # 他说过照发的：不藏
    x_daily.save(p, {"days": {key: {"posts": posts}}})
    now = datetime(2026, 10, 12, 10, tzinfo=BJ)
    v = x_daily.view(p, now=now)["today"]
    assert [x.get("hidden", False) for x in v["posts"]] == [True, True, True, False] and v["hidden_long"] == 3
    got = x_daily.merge_next(p, now=now)
    assert got and got[0] == key and [x["id"] for x in got[1]] == [f"{key}-L0", f"{key}-L1", f"{key}-L2"]

    notes = [{"path": f"003/{i}.md", "title": f"第{i}篇", "body": para(i)} for i in range(2)]
    answers = iter([json.dumps([{"type": "merge", "sources": ["003/0.md", "003/1.md"], "mainline": "先展示结果"}]),
                    json.dumps({"outputs": [{"title": "先展示结果", "parts": [{"note": 1, "paragraph": 1}, {"note": 2, "paragraph": 1}]}]})])
    group = rawtidy.propose(notes, write_fn=lambda prompt: next(answers), limit=1)[0]
    row = x_daily.add_merged(p, key, [f"{key}-L0", f"{key}-L1", f"{key}-L2"], group, now=now)
    assert row["merged_from"] == ["003/0.md", "003/1.md"] and row["format"] == "post" and row["text"].startswith("# 先展示结果")
    d = x_daily.load(p)["days"][key]
    by = {x["id"]: x for x in d["posts"]}
    assert by[f"{key}-L0"]["merged_into"] == row["id"] and not by[f"{key}-L2"].get("merge_tries")  # 没用上的留着下次拼
    assert x_daily.merge_next(p, now=now) is None  # 剩下的不够两篇
    assert x_daily.view(p, now=now)["today"]["merge"] == {"count": 1, "max": x_daily.MERGE_PER_DAY, "waiting": 1}
    # 合并稿 QA 也不过：藏起来，但不再拿去拼
    x_daily.apply_qa(p, key, row["id"], seen=row["text"], result={"text": row["text"], "changes": [], "dropped": [], "complete": True,
                                                                   "issues": [], "value_ok": False, "value": {}, "value_issues": ["没有解法"]})
    assert x_daily.load(p)["days"][key]["posts"][-1]["hidden"] is True
    assert x_daily.merge_next(p, now=now) is None


def test_failed_merge_tries_each_post_twice_and_never_the_same_group_back_to_back(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    posts = [{"id": f"{key}-L{i}", "text": f"# {i}", "long": True, "format": "post", "prep": "ready", "state": "pending",
              "qa": "ready", "hidden": True} for i in range(3)]
    x_daily.save(p, {"days": {key: {"posts": posts}}})
    now = datetime(2026, 10, 12, 10, tzinfo=BJ)
    ids = [x["id"] for x in x_daily.merge_next(p, now=now)[1]]
    x_daily.add_merged(p, key, ids, None, reason="拼不出共同主题")
    assert x_daily.merge_next(p, now=now) is None  # 同一组不原样再试
    d = x_daily.load(p)
    d["days"][key]["posts"].append({**posts[0], "id": f"{key}-L9"})  # 又藏了一篇：组变了，再试一次
    x_daily.save(p, d)
    again = x_daily.merge_next(p, now=now)
    assert again and again[1][0]["id"] == f"{key}-L9"
    x_daily.add_merged(p, key, [x["id"] for x in again[1]], None, reason="还是拼不出")
    assert x_daily.view(p, now=now)["today"]["merge"]["waiting"] == 1  # L0–L2 都试过两次了，只剩 L9


def test_ten_picks_a_day_and_four_buttons(tmp_path: Path) -> None:
    """10/12 作者：每天从原始输出挑 10 篇候选；发文 → 改写配图后存 X 草稿（他自己发，工作台不发）；
    长帖 → 整篇原话一条，QA 完整就自动发；拆解 → 拆成几条短帖进自动发；不发 → 只记下。"""
    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    now = datetime(2026, 10, 12, 8, tzinfo=BJ)
    assert x_daily.picks_due(p, now=now) == key
    notes = [{"text": f"标题{i}\n\n" + "这一篇讲的是一个判断。" * 40, "long": True, "source_id": f"obsidian:003/{i}.md", "source_title": f"标题{i}"} for i in range(12)]
    picks = x_daily.add_picks(p, key, notes, now=now)
    assert len(picks) == 10 and x_daily.picks_due(p, now=now) is None
    assert x_daily.picks_due(p, now=datetime(2026, 10, 12, 21, 30, tzinfo=BJ)) == "2026-10-13"
    assert x_daily.picked_sources(x_daily.load(p)) >= {"obsidian:003/0.md"}

    x_daily.choose(p, key, picks[0]["id"], "article", now=now)
    x_daily.choose(p, key, picks[1]["id"], "post", now=now)
    x_daily.choose(p, key, picks[2]["id"], "split", now=now)
    x_daily.choose(p, key, picks[3]["id"], "skip", now=now)
    with pytest.raises(x_daily.DailyError, match="已经选了"):
        x_daily.choose(p, key, picks[0]["id"], "post", now=now)
    d = x_daily.load(p)["days"][key]
    art = next(x for x in d["posts"] if x["id"].endswith("-A0"))
    post = next(x for x in d["posts"] if x["id"].endswith("-P1"))
    assert art["manual_publish"] and art.get("format") is None and art["state"] == "pending"
    assert post["format"] == "post" and post["prep"] == "ready"
    assert x_daily.prep_next(p, now=now)[1]["id"] == art["id"]  # 发文走改写配图

    # 长帖：QA 完整就自动排着发，价值关不拦他自己选的
    x_daily.apply_qa(p, key, post["id"], seen=post["text"], result={"text": post["text"], "changes": [], "dropped": [], "complete": True,
                                                                     "issues": [], "value_ok": False, "value": {}, "value_issues": ["没有解法"]})
    assert next(x for x in x_daily.load(p)["days"][key]["posts"] if x["id"] == post["id"])["state"] == "approved"
    # 发文的就算勾了也不自动发
    data = x_daily.load(p)
    next(x for x in data["days"][key]["posts"] if x["id"] == art["id"]).update(state="approved", prep="ready")
    x_daily.save(p, data)
    assert all(x["id"] != art["id"] for x in x_daily.sendable(x_daily.load(p)["days"][key]))

    # 拆解
    job = x_daily.split_next(p, now=now)
    assert job and job[1]["id"] == picks[2]["id"]
    model = lambda prompt: "<<<POST source=0>>>\n这一篇讲的是一个判断。\n<<<END>>>"  # noqa: E731
    assert x_daily.split_pick(p, key, picks[2]["id"], write_fn=model, now=now) == 1
    d = x_daily.load(p)["days"][key]
    assert any(x["id"] == f"{picks[2]['id']}-S0" and not x.get("long") for x in d["posts"])
    assert next(x for x in d["picks"] if x["id"] == picks[2]["id"])["split"] == "done"
    assert x_daily.split_next(p, now=now) is None

    # 没存草稿的发文第二天跟着挪过去，不作废
    x_daily.mark_drafted(p, key, art["id"], None)
    data = x_daily.load(p)
    data["days"][key]["posts"].append({**art, "id": f"{key}-A9", "state": "pending"})
    x_daily.save(p, data)
    v = x_daily.view(p, now=datetime(2026, 10, 13, 9, tzinfo=BJ))
    assert any(x["id"] == f"2026-10-13-c{key}-A9" and x["state"] == "pending" for x in v["today"]["posts"])


def test_value_track_keeps_two_articles_from_the_picks(tmp_path: Path) -> None:
    """10/12 晚 作者：价值线每天工作台做 2 篇长文（他存草稿自己发）；拆成短帖 / 不发就从候选里补一篇顶上。"""
    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    now = datetime(2026, 10, 12, 8, tzinfo=BJ)
    notes = [{"text": f"标题{i}\n\n" + "正文。" * 200, "long": True, "source_id": f"obsidian:003/{i}.md", "source_title": f"标题{i}"} for i in range(5)]
    x_daily.add_picks(p, key, notes, now=now)
    assert x_daily.fill_articles(p, key, now=now) == 2
    d = x_daily.load(p)["days"][key]
    arts = x_daily.value_articles(d)
    assert [a["source_id"] for a in arts] == ["obsidian:003/0.md", "obsidian:003/1.md"] and all(a["manual_publish"] for a in arts)
    assert x_daily.fill_articles(p, key, now=now) == 0
    x_daily.value_action(p, key, arts[0]["id"], "split", now=now)
    d = x_daily.load(p)["days"][key]
    assert [a["source_id"] for a in x_daily.value_articles(d)] == ["obsidian:003/1.md", "obsidian:003/2.md"]
    assert x_daily.split_next(p, now=now)[1]["source_id"] == "obsidian:003/0.md"
    x_daily.mark_drafted(p, key, arts[1]["id"], None)
    assert len(x_daily.value_articles(x_daily.load(p)["days"][key])) == 2  # 存了草稿的也算今天这 2 篇
    assert x_daily.set_own(p, key, video=True) == {"video": True}


def test_short_posts_are_contrarian_takes_from_his_principles(tmp_path: Path) -> None:
    """10/12 晚 作者：短帖 = 反常识暴论，从他的原则、预测出发，不一定是原话；不编数字和经历，不和发过的重复。"""
    from content_studio.extras.xline import x_suggest

    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    sources = [{"key": "principle", "label": "原则", "items": [{"id": "p1", "title": "万物逻辑", "body": "简单的事情重复做。"},
                                                              {"id": "p2", "title": "AI", "body": "AI 会替代大部分脑力劳动。"}]}]
    x_daily.save(p, {"days": {key: {"posts": [{"id": "old", "text": "简单的事情重复做，就是最难的事。", "state": "sent"}]}}})

    def model(prompt: str) -> str:
        assert "反常识暴论" in prompt and "简单的事情重复做" in prompt and "最近两周发过的短帖" in prompt
        return ("<<<POST source=1>>>\n觉得自己的工作不会被 AI 替代的人，往往就是第一批被替代的。\n<<<END>>>\n"
                "<<<POST source=0>>>\n简单的事情重复做，就是最难的事。\n<<<END>>>\n"          # 和发过的重复：扔
                "<<<POST source=1>>>\n我用 AI 替掉了 90% 的员工。\n<<<END>>>\n"              # 编经历、编数字：扔
                "<<<POST source=0>>>\n你真的觉得复杂才高级吗？\n<<<END>>>")                  # 问号结尾：扔
    made = x_daily.topup_shorts(p, key, sources=sources, skipped=set(), posted=set(), write_fn=model, n=5,
                                style="短、狠", check_fn=x_suggest.check, now=datetime(2026, 10, 12, 9, tzinfo=BJ))
    posts = x_daily.load(p)["days"][key]["posts"]
    assert made == 1 and posts[-1]["text"].startswith("觉得自己的工作不会被 AI 替代") and posts[-1]["take"] and posts[-1]["source_id"] == "p2"
