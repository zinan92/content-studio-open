from datetime import datetime, timedelta
import json
import threading
import time

import pytest

from content_studio.extras.xline import x_daily, x_replies, x_suggest, xhot, xops
from test_x_line import client_factory  # noqa: F401

NOW = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)


@pytest.fixture(autouse=True)
def park_lines(monkeypatch):
    """10/12 起回复只用他的原话；这里的老测试测别的（格式、节奏、风控），原话检索和核对用假的放行，专门的测试在 test_x_replies_grounded.py。"""
    monkeypatch.setattr(x_replies, "raw_lines", lambda root: [{"text": "工具需要验证结果才能用", "note": "003_原始输出/a.md"}])
    monkeypatch.setattr(x_replies, "match_lines", lambda text, lines, k=6: list(lines))
    monkeypatch.setattr(x_replies, "grounded", lambda text, chosen: True)


def item(tid, hours=1, category="AI"):
    return {"id": f"https://x.com/user/status/{tid}", "url": f"https://x.com/user/status/{tid}",
            "author": "作者", "text": "AI 工具需要验证结果", "category": category,
            "published_at": (NOW - timedelta(hours=hours)).isoformat()}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    style = tmp_path / "X 写作风格.md"
    style.write_text("风格：用具体判断，不要空夸。", encoding="utf-8")
    role = tmp_path / "Michael.md"
    role.write_text("Michael：不自动回复。", encoding="utf-8")
    monkeypatch.setattr(x_suggest, "style_path", lambda: style)
    monkeypatch.setattr(xops, "role_path", lambda: role)
    original = x_daily.now_bj
    monkeypatch.setattr(x_daily, "now_bj", lambda now=None: original(now or NOW))



def test_candidates_limit_after_filtering_and_prior_day_handled():
    data = {"days": {"2026-10-10": {"1": {"state": "sent"}, "2": {"state": "skip"}}}}
    rows = [item(str(i)) for i in range(1, 30)]
    assert [r["id"] for r in x_replies.candidates(rows, data, NOW)] == [str(i) for i in range(3, 30)]


@pytest.mark.parametrize("text", ["说得好", "这件事你怎么看？", "参考 https://example.com", "成功率 99%", "太长" * 70])
def test_invalid_drafts_are_not_stored(text):
    assert x_replies.draft([item("1")], soul="角色", style="风格",
                           turn_fn=lambda *a: {"text": json.dumps({"replies": [{"id": "1", "text": text}]})}) == 0
    assert x_replies.view([item("1")])["items"] == []  # 没过检查的记成跳过，不再给这条写


def test_skip_during_generation_is_not_resurrected():
    def model(*args):
        x_replies.mark("1", "skip")
        return {"text": json.dumps({"replies": [{"id": "1", "text": "可靠性应该先用失败样本验证。"}]})}
    x_replies.draft([item("1")], soul="角色", style="风格", turn_fn=model)
    assert x_replies.view([item("1")])["items"] == []
    assert "draft" not in json.loads(x_replies.path().read_text())["days"]["2026-10-11"]["1"]


def test_off_topic_posts_are_skipped_not_drafted(tmp_path, monkeypatch):
    monkeypatch.setattr(x_replies, "path", lambda: tmp_path / "x_replies.json")
    rows = [item("1"), item("2")]
    fake = lambda s, u, sid: {"text": json.dumps({"replies": [{"id": "1", "text": "SKIP"}, {"id": "2", "text": "先拿失败样本验证，再谈规模。"}]}, ensure_ascii=False)}
    assert x_replies.draft(rows, soul="", style="", turn_fn=fake, now=NOW) == 1
    assert [r["id"] for r in x_replies.view(rows, now=NOW)["items"]] == ["2"]


def seed(count=3):
    x_daily.save(x_replies.path(), {"days": {"2026-10-11": {
        str(i): {"draft": "工具的可靠性要用失败样本验证。", "state": "draft", "url": f"https://x.com/u/status/{i}"}
        for i in range(1, count + 1)}}})


def test_approve_edit_send_gap_and_cap():
    seed()
    assert x_replies.approve_all(edits={"1": "先验证失败样本，再判断工具是否可靠。"}) == 3
    calls = []
    def send(text, **kw):
        assert x_daily.load(x_replies.path())["days"]["2026-10-11"][kw["in_reply_to_tweet_id"]]["state"] == "sending"
        calls.append(kw)
        return {"id": str(100 + len(calls))}
    settings = {"x_kpi": {"replies_max": 2}, "reply_gap_minutes": 4}
    assert x_replies.tick(post_fn=send, settings=settings, now=NOW.replace(hour=8)) is None
    assert x_replies.tick(post_fn=send, settings=settings, now=NOW)["state"] == "sent"
    assert x_replies.tick(post_fn=send, settings=settings, now=NOW + timedelta(minutes=3)) is None
    assert x_replies.tick(post_fn=send, settings=settings, now=NOW + timedelta(minutes=4))["reply_id"] == "102"
    assert x_replies.tick(post_fn=send, settings=settings, now=NOW + timedelta(minutes=8)) is None
    assert len(calls) == 2
    assert x_replies.view([], now=NOW)["sent"] == 2


@pytest.mark.parametrize("error", ["429", "403 automated", "spam detected", "restricted"])
def test_block_halts_day_without_retry(error):
    seed()
    x_replies.approve_all()
    calls = []
    def send(*a, **kw):
        calls.append(1)
        raise RuntimeError(error)
    assert x_replies.tick(post_fn=send, now=NOW)["state"] == "failed"
    assert x_replies.stop_message(now=NOW) == f"X 拦了回复：{error}，今天停了"
    assert x_replies.view([], now=NOW)["halted_message"] == x_replies.stop_message(now=NOW)
    assert x_replies.tick(post_fn=send, now=NOW + timedelta(hours=1)) is None
    assert len(calls) == 1
    assert x_replies.stop_message(now=NOW + timedelta(days=1)) is None


def test_restart_uncertain_never_resends():
    seed(1)
    data = x_daily.load(x_replies.path())
    data["days"]["2026-10-11"]["1"]["state"] = "sending"
    x_daily.save(x_replies.path(), data)
    assert x_replies.recover_sending() == 1
    assert x_replies.view([])["items"][0]["state"] == "uncertain"
    assert x_replies.approve_all() == 0
    assert x_replies.tick(post_fn=lambda *a, **k: pytest.fail("duplicate"), now=NOW) is None


def test_skill_fulltext_and_repeat_batches(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("完整 park-writing 首段\n第二段不可截断", encoding="utf-8")
    calls = []
    def model(system, prompt, _):
        calls.append(system)
        rows = json.loads(prompt.split("原帖：\n", 1)[1])
        return {"text": json.dumps({"replies": [{"id": r["id"], "text": "先验证失败样本，再判断工具的可靠性。"} for r in rows]})}
    rows = [item(str(i)) for i in range(1, 41)]
    assert x_replies.draft(rows, soul="Michael 角色", skill_path=str(skill), turn_fn=model, now=NOW) == 30
    assert x_replies.draft(rows, soul="Michael 角色", skill_path=str(skill), turn_fn=model, now=NOW) == 10
    assert "完整 park-writing 首段\n第二段不可截断" in calls[0] and "Michael 角色" in calls[0]
    assert len(x_replies.view(rows)["items"]) == 40


def test_edit_invalidates_approval_and_bulk_validation_atomic():
    seed(2)
    x_replies.approve_all()
    assert x_replies.mark("1", text="先测试失败样本。 ")["state"] == "draft"
    with pytest.raises(ValueError):
        x_replies.approve_all(edits={"1": ""})
    assert x_replies.view([])["items"][0]["state"] == "draft"
    with pytest.raises(ValueError):
        x_replies.mark("1", "sent")


def test_routes_draft_confirm_edit_and_delete(client_factory, monkeypatch):
    monkeypatch.setattr(xhot.Board, "rising", lambda self: {"items": [item("1"), item("2")]})
    monkeypatch.setattr(xhot.Board, "get", lambda *a, **k: {"items": []})
    monkeypatch.setattr(x_replies, "load_style", lambda _: "临时风格")
    def model(*a):
        return {"text": json.dumps({"replies": [{"id": str(i), "text": "先验证失败样本，再判断工具的可靠性。"} for i in (1, 2)]})}
    client = client_factory(anna_fn=model, x_fetch_fn=lambda url: pytest.fail("unexpected X request"))
    assert client.post("/api/xline/replies/draft").json() == {"started": True}
    for _ in range(100):
        got = client.get("/api/xline/replies").json()
        if not got["busy"]:
            break
        time.sleep(.01)
    assert not got["busy"] and got["error"] is None
    assert client.post("/api/xline/replies/approve-all", json={"edits": {"1": "先看失败样本。"}}).json()["approved"] == 2
    assert client.get("/api/xline/replies").json()["items"][0]["state"] == "approved"
    assert client.post("/api/xline/replies/1", json={"text": "先验证工具的输出。"}).json()["reply"]["state"] == "draft"
    assert client.post("/api/xline/replies/1", json={"state": "skip"}).status_code == 200
    assert [r["id"] for r in client.get("/api/xline/replies").json()["items"]] == ["2"]
    assert client.post("/api/xline/replies/2", json={"state": "sent"}).status_code == 400


def test_numeric_success_id_is_not_http_status():
    seed(1)
    x_replies.approve_all()
    assert x_replies.tick(post_fn=lambda *a, **k: {"id": "403", "url": "https://x.com/i/web/status/403"}, now=NOW)["state"] == "sent"
    assert x_replies.stop_message(now=NOW) is None


def test_legacy_intent_is_not_verified_sent():
    x_daily.save(x_replies.path(), {"days": {"2026-10-11": {"1": {"state": "sent", "draft": "旧草稿"}}}})
    got = x_replies.view([], now=NOW)
    assert got["sent"] == 0 and got["items"][0]["state"] == "uncertain"
    assert x_replies.recover_sending() == 1
    assert x_replies.approve_all() == 0


def test_exception_status_attribute_halts():
    seed(1)
    x_replies.approve_all()
    class Blocked(Exception):
        status_code = 429
    def send(*a, **k):
        raise Blocked("limited")
    x_replies.tick(post_fn=send, now=NOW)
    assert "429" in x_replies.stop_message(now=NOW)
