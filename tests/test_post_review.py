"""拍后批注（10/13 作者）：字幕放进项目就自动出，只打分、只批注；引用的原话代码核对，对不上的丢掉。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import post_review, write_module
from test_write_module import with_review
from test_x_line import client_factory  # noqa: F401 - fixture

TRANSCRIPT = "".join(f"第{n}句：我觉得闭环比终局更重要，因为终局大家都看得到，但是短期做不到，所以小闭环先闭，大闭环后闭。" for n in range(1, 8))
GOOD_QUOTE = "我觉得闭环比终局更重要"


def reply(quote: str = GOOD_QUOTE, extra: dict | None = None) -> str:
    scores = {t: {"score": s, "why": f"{t}的理由", "quote": quote} for t, s in
              [("留人", 7), ("密度", 12), ("稀缺", 3), ("口气", 8), ("错字通顺和导语", 9)]}
    scores["稀缺"]["quote"] = "字幕里根本没有这句话，模型编的"
    return "<<<JSON>>>\n" + json.dumps({"scores": scores, "next": ["开头先说结果", "", "证据放前面"], **(extra or {})}, ensure_ascii=False) + "\n<<<END>>>"


@pytest.fixture()
def module(tmp_path: Path):
    return write_module.load(with_review(tmp_path))


# -- 代码核对 ------------------------------------------------------------------------------------

def test_scores_are_clamped_quotes_must_be_in_the_transcript_and_edits_are_never_kept(module) -> None:
    data = json.loads(reply(extra={"rewrite": "改稿", "edits": [{"op": "replace"}]}).split("<<<JSON>>>\n")[1].split("\n<<<END>>>")[0])
    out = post_review.validate(module, TRANSCRIPT, data)
    assert out["scores"]["密度"]["score"] == 10                              # 12 压到 10
    assert out["scores"]["留人"]["quote"] == GOOD_QUOTE                      # 真在字幕里的留着
    assert out["scores"]["稀缺"]["quote"] == "" and out["dropped_quotes"] == 1  # 编的丢掉，理由留着
    assert out["scores"]["稀缺"]["why"] == "稀缺的理由"
    assert out["next"] == ["开头先说结果", "证据放前面"]                      # 空的不要
    assert set(out) == {"scores", "next", "dropped_quotes"}                  # 改稿一类的字段一概不收


def test_fewer_than_three_scored_items_is_not_a_review(module) -> None:
    with pytest.raises(post_review.ReviewError, match="不到三项"):
        post_review.validate(module, TRANSCRIPT, {"scores": {"留人": {"score": 5, "why": "x"}}, "next": []})


def test_the_prompt_carries_the_rule_text_the_items_and_forbids_rewriting(module) -> None:
    prompt = post_review.build_prompt(module, TRANSCRIPT)
    assert "每项 0–10 分" in prompt                       # 规则来自 park-writing 的 post-shoot 那一段
    assert "留人、密度、稀缺、口气、错字通顺和导语" in prompt
    assert "只打分、只批注，一个字都不改" in prompt and TRANSCRIPT[:20] in prompt


def test_the_newest_review_with_notes_is_the_reminder_and_the_current_topic_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "drafts"
    for tid, when, notes in [(1, "2026-10-11T10:00:00", ["旧的"]), (2, "2026-10-12T10:00:00", ["新的"]), (3, "2026-10-13T10:00:00", [])]:
        post_review.save(root, tid, {"scores": {"留人": {"score": 5}}, "next": notes, "created_at": when, "title": f"t{tid}"})
    assert post_review.latest(root)["topic_id"] == 2          # 3 号没有「下一条要注意的」
    assert post_review.latest(root, exclude=2)["topic_id"] == 1
    assert post_review.latest(tmp_path / "none") is None


# -- 页面接口 ------------------------------------------------------------------------------------

def make_client(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer=lambda p: reply()):  # noqa: F811
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(with_review(tmp_path)))
    calls: list[str] = []

    def model(prompt: str) -> str:
        calls.append(prompt)
        return answer(prompt) if "刚拍完的一条视频" in prompt else ""

    client: TestClient = client_factory(write_fn=model, drafts_dir=tmp_path / "drafts", x_fetch_fn=lambda url: [] if "manifest" in url else {})
    topic = client.post("/api/topics", json={"title": "闭环", "formats": "video"}).json()
    return client, topic["id"], calls


def give_transcript(client: TestClient, tmp_path: Path, tid: int, text: str = TRANSCRIPT) -> None:
    client.app.state.store.update_topic(tid, published_video_id="7000001")
    folder = tmp_path / "dl" / "douyin" / "acct" / "7000001"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "transcript.json").write_text(json.dumps({"full_text": text}, ensure_ascii=False), encoding="utf-8")


def wait_review(client: TestClient, tid: int) -> dict:
    for _ in range(300):
        d = client.get(f"/api/topics/{tid}/review").json()
        if not d["running"]:
            return d
        time.sleep(0.02)
    raise AssertionError("批注没结束")


def test_no_transcript_means_nothing_to_review_and_nothing_starts(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, tid, calls = make_client(client_factory, tmp_path, monkeypatch)
    d = client.get(f"/api/topics/{tid}/review").json()
    assert d["has_transcript"] is False and d["can_auto"] is False and d["available"] is True
    assert client.post(f"/api/topics/{tid}/review", json={}).json()["started"] is False
    assert calls == []


def test_a_transcript_gets_one_review_and_the_same_transcript_is_not_reviewed_twice(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, tid, calls = make_client(client_factory, tmp_path, monkeypatch)
    give_transcript(client, tmp_path, tid)
    assert client.get(f"/api/topics/{tid}/review").json()["can_auto"] is True
    assert client.post(f"/api/topics/{tid}/review", json={}).json()["started"] is True
    d = wait_review(client, tid)
    assert d["error"] is None and d["can_auto"] is False and d["stale"] is False
    rec = d["review"]
    assert rec["scores"]["留人"]["quote"] == GOOD_QUOTE and rec["scores"]["稀缺"]["quote"] == "" and rec["next"] == ["开头先说结果", "证据放前面"]
    assert [i["title"] for i in rec["items"]][-1] == "错字通顺和导语"
    again = client.post(f"/api/topics/{tid}/review", json={}).json()
    assert again["started"] is False and "批注过了" in again["message"] and len(calls) == 1
    assert client.post(f"/api/topics/{tid}/review", json={"force": True}).json()["started"] is True  # 点了重来才重来
    wait_review(client, tid)
    assert len(calls) == 2
    # 字幕换了：旧批注标「过期」，可以自动再来一次
    give_transcript(client, tmp_path, tid, TRANSCRIPT + "又补了一句新的内容，用来让字幕和上次不一样，批注就该重来一遍。")
    d = client.get(f"/api/topics/{tid}/review").json()
    assert d["stale"] is True and d["can_auto"] is True


def test_a_failed_review_says_why_and_is_not_retried_automatically(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, tid, calls = make_client(client_factory, tmp_path, monkeypatch, answer=lambda p: "没按格式")
    give_transcript(client, tmp_path, tid)
    client.post(f"/api/topics/{tid}/review", json={})
    d = wait_review(client, tid)
    assert d["error"] and d["review"] is None and d["can_auto"] is False  # 同一份字幕失败过，不自动再试，等他点
    assert len(calls) == 2                                              # 一次调用里最多试两遍


def test_the_reminder_endpoint_skips_the_topic_being_worked_on(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, tid, _ = make_client(client_factory, tmp_path, monkeypatch)
    give_transcript(client, tmp_path, tid)
    client.post(f"/api/topics/{tid}/review", json={})
    wait_review(client, tid)
    got = client.get("/api/review/latest").json()["review"]
    assert got["topic_id"] == tid and got["next"] and got["title"] == "闭环"
    assert client.get(f"/api/review/latest?exclude={tid}").json()["review"] is None


def test_without_the_review_sections_the_page_is_told_it_is_unavailable(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    from test_write_module import make_skill

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(make_skill(tmp_path)))  # 老清单：没有 review / post-shoot
    client = client_factory(write_fn=lambda p: "", drafts_dir=tmp_path / "drafts", x_fetch_fn=lambda url: [] if "manifest" in url else {})
    tid = client.post("/api/topics", json={"title": "闭环", "formats": "video"}).json()["id"]
    give_transcript(client, tmp_path, tid)
    d = client.get(f"/api/topics/{tid}/review").json()
    assert d["available"] is False and d["can_auto"] is False
    assert client.post(f"/api/topics/{tid}/review", json={}).status_code == 400
    assert client.get(f"/api/topics/{tid}/script").json()["review"] == []   # 口播稿页退回原来的打分
