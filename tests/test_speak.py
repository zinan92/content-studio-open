"""「你说一遍」：拆完的爆款入选题池 → 复刻 → 看着拆解直接说 → （删口水话）→ 存进原始输出 → 写骨架。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import speak
from test_web import client  # noqa: F401 - fixture

def test_long_voice_run_ons_are_cut_at_commas_and_sentences_keep_their_words() -> None:
    text = "嗯，那个，我觉得这东西特别好用。" + "我装了第一个，" * 12 + "\n结尾就是留言领"
    parts = speak.split_sentences(text)
    assert parts[0] == "嗯，那个，我觉得这东西特别好用。" and parts[-1] == "结尾就是留言领"
    assert all(len(p) <= speak.LONG + 8 for p in parts)
    assert "".join(parts) == text.replace("\n", "")  # 切开不丢字、不加字


def test_cleaning_only_drops_whitelisted_fillers_and_keeps_his_order_and_lines() -> None:
    """10/4 作者：只删口水话，一个字都不改写。模型想删白名单外的词、想删不在句子里的词，都被代码挡掉。"""
    said = "嗯，那个，连我妈都开始用 AI 了。我自己装了三个 Skill。\n最后一句：留言领。这个额度够用。"

    def model(prompt: str) -> dict:
        assert "连我妈都开始用 AI 了" in prompt and "额度" in prompt
        return {"drop": [[0, "嗯"], [0, "那个，"], [1, "Skill"], [2, "最后一句："], [3, "额"], [9, "嗯"]]}  # 后几个：白名单外 / 不在这句 / 越界

    out = speak.clean(said, model)
    assert out["text"] == "连我妈都开始用 AI 了。我自己装了三个 Skill。\n\n最后一句：留言领。这个额度够用。"
    assert out["dropped"] == 2
    with pytest.raises(speak.SpeakError, match="先在大框里说一遍"):
        speak.clean("   ", model)
    with pytest.raises(speak.SpeakError, match="再点一次"):
        speak.clean("说了一句。", lambda p: "不是 JSON")


def test_dropping_a_filler_between_two_marks_leaves_no_double_comma() -> None:
    """10/10：「干的：嗯，每天」「所以，嗯，我的」删掉嗯以后不能剩「：，」「，，」。"""
    said = "我现在是这么干的：嗯，每天先看日报。所以，嗯，我的建议是先说一遍。"
    out = speak.clean(said, lambda p: {"drop": [[0, "嗯"], [1, "嗯"]]})
    assert out["text"] == "我现在是这么干的：每天先看日报。所以，我的建议是先说一遍。"


def test_saved_note_has_only_his_words_not_the_other_creators() -> None:
    data = speak.from_report({"content_id": "5", "title": "原标题 #codex", "author": "千雪", "source_url": "https://x/5",
                              "segments": [{"label": "钩子", "text": "他的原话开场", "start": 0, "end": 4},
                                           {"label": "跑题", "text": "自我介绍", "drift": True, "start": 4, "end": 6},
                                           {"label": "案例", "text": "他的案例原话", "start": 6, "end": 9}]})
    assert [s["label"] for s in data["segments"]] == ["钩子", "案例"]  # 跑题段不进底稿
    data["mode"] = "copy"
    data["dictation"] = "我妈都用了。\n\n多说的一句。"
    md = speak.note_markdown(data, "我的标题")
    assert "我妈都用了。" in md and "多说的一句。" in md and "千雪《原标题》" in md and "钩子 → 案例" in md
    assert "每一句都是我（作者）自己说的" in md  # 骨架别把他的经历当成对标博主的
    assert "他的原话开场" not in md and "他的案例原话" not in md  # 骨架会从这篇挑开头：他的话不能进来


def _wait(client: TestClient, tid: int) -> dict:
    for _ in range(100):
        view = client.get(f"/api/topics/{tid}/speak").json()
        if not view["running"] and view["state"] != "running":
            return view
        time.sleep(0.05)
    raise AssertionError("整理没结束")


def test_from_report_to_pool_to_replicate_to_speaking_to_raw_output(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """拆完 → 入选题池（候选）→ 复刻（开始做）→ 说一遍 → 删口水话 → 撤回 / 再删 → 存进原始输出 → 自动写骨架。"""
    from test_web import SEC, _wait_sync

    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"})
    _wait_sync(client)
    client.post("/api/jobs", json={"video_id": "5", "source": "对标"})
    client.app.state.worker.drain()

    assert client.get("/api/reports/5/pool").json()["topic"] is None
    pooled = client.post("/api/reports/5/pool").json()
    tid = pooled["topic"]["id"]
    assert pooled["existing"] is False and "拆解自" in pooled["topic"]["memo"]
    assert client.post("/api/reports/5/pool").json() == {"topic": client.get("/api/reports/5/pool").json()["topic"], "existing": True}
    card = next(c for c in client.get("/api/board").json()["pool"] if c["id"] == tid)
    assert card["replicate"]["mode"] is None and not card["focus"]  # 只是候选：还没开做

    assert client.post(f"/api/topics/{tid}/replicate", json={"mode": "copy-all"}).status_code == 400
    started = client.post(f"/api/topics/{tid}/replicate", json={}).json()  # 10/5 起只有一个「复刻」
    assert started["topic"]["is_focus"] and started["speak"]["mode_label"] == "复刻"
    board = client.get("/api/board").json()
    assert board["focus"]["id"] == tid and "说一遍" in board["focus"]["next"]["text"]

    assert client.post(f"/api/topics/{tid}/speak/arrange").status_code == 400  # 还没说话
    assert client.post(f"/api/topics/{tid}/speak/save", json={}).status_code == 400
    client.put(f"/api/topics/{tid}/speak", json={"dictation": "嗯，那个，我妈都开始用 AI 了。我装了三个 Skill。"})
    monkeypatch.setattr(speak, "cli_ask", lambda p: {"drop": [[0, "嗯"], [0, "那个，"]]})
    assert client.post(f"/api/topics/{tid}/speak/arrange").json()["started"] is True
    view = _wait(client, tid)
    assert view["state"] == "done" and view["dictation"] == "我妈都开始用 AI 了。我装了三个 Skill。"  # 口水话删了，字没改
    undone = client.put(f"/api/topics/{tid}/speak", json={"undo": True}).json()
    assert undone["dictation"].startswith("嗯，那个，") and undone["before_clean"] is None  # 撤回
    client.post(f"/api/topics/{tid}/speak/arrange")
    _wait(client, tid)

    raw = Path(client.app.state.store.settings()["obsidian_vault"]) / "003_原始输出"
    raw.mkdir(parents=True)
    saved = client.post(f"/api/topics/{tid}/speak/save", json={"title": "我的版本"}).json()
    note = raw / saved["name"]
    assert note.is_file() and "我妈都开始用 AI 了。" in note.read_text(encoding="utf-8")
    topic = next(t for t in client.get("/api/topics").json() if t["id"] == tid)
    assert topic["title"] == "我的版本" and saved["path"] in topic["note_paths"]
    assert saved["outline"]["started"] is True  # 存完接着写骨架，骨架读的是他这篇
    for _ in range(100):  # 等骨架写完，别让后台线程撞上测试收尾
        if next(t for t in client.get("/api/topics").json() if t["id"] == tid)["outline_state"] != "running":
            break
        time.sleep(0.05)


def _no_real_outline(monkeypatch: pytest.MonkeyPatch) -> None:
    """存完会接着写骨架：测试里不碰真的模型，直接让它失败收场。"""
    from content_studio import outline

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("测试里不写骨架")

    monkeypatch.setattr(outline, "write_outline", boom)


def test_oral_works_on_other_peoples_material_without_taking_over_today(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_real_outline(monkeypatch)
    """10/13 作者：日报、收藏、Clippings 进池后在排期里多一步「口述」；不抢「正在做」，说完就是他自己的话。"""
    vault_dir = Path(client.app.state.store.settings()["obsidian_vault"])
    (vault_dir / "002_clippings").mkdir(parents=True)
    (vault_dir / "002_clippings" / "a.md").write_text("---\nsource: https://example.com/a\n---\n# 别人写的\n\n别人的一句话。\n", encoding="utf-8")
    (vault_dir / "003_原始输出").mkdir(parents=True)
    tid = client.post("/api/topics", json={"title": "别人的题", "note_paths": ["002_clippings/a.md"]}).json()["id"]

    assert client.get(f"/api/topics/{tid}/speak").status_code == 404  # 没有拆解，也没开口述
    started = client.post(f"/api/topics/{tid}/replicate", json={"mode": "oral"}).json()
    assert not started["topic"]["is_focus"] and started["speak"]["mode_label"] == "口述"
    parts = started["speak"]["source"]["parts"]
    assert parts and "别人的一句话" in parts[0]["body"] and parts[0]["url"] == "https://example.com/a"

    assert client.post(f"/api/topics/{tid}/speak/save", json={}).status_code == 400  # 还没说话
    client.put(f"/api/topics/{tid}/speak", json={"dictation": "我自己的看法，和这篇不一样。"})
    saved = client.post(f"/api/topics/{tid}/speak/save", json={"title": "我的看法"}).json()
    text = (vault_dir / "003_原始输出" / saved["name"]).read_text(encoding="utf-8")
    assert "我自己的看法" in text and "how: 口述" in text and "https://example.com/a" in text
    assert "别人的一句话" not in text  # 别人的话不进他的笔记
    after = client.get(f"/api/topics/{tid}/speak").json()["source"]["parts"]
    assert [p["title"] for p in after] == ["别人写的"]  # 他自己存的那篇不会再冒充「别人的材料」
    topic = next(t for t in client.get("/api/topics").json() if t["id"] == tid)
    assert saved["path"] in topic["note_paths"] and "002_clippings/a.md" in topic["note_paths"]
    for _ in range(100):
        if next(t for t in client.get("/api/topics").json() if t["id"] == tid)["outline_state"] != "running":
            break
        time.sleep(0.05)


def test_oral_with_no_material_creates_a_topic_in_the_pool(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_real_outline(monkeypatch)
    (Path(client.app.state.store.settings()["obsidian_vault"]) / "003_原始输出").mkdir(parents=True)
    made = client.post("/api/schedule/oral", json={}).json()
    tid = made["topic"]["id"]
    assert made["topic"]["title"] == "新口述" and not made["topic"]["is_focus"]
    assert made["speak"]["source"]["parts"] == []
    client.put(f"/api/topics/{tid}/speak", json={"dictation": "直接说的一段。"})
    saved = client.post(f"/api/topics/{tid}/speak/save", json={"title": "直接说的"}).json()
    note = (Path(client.app.state.store.settings()["obsidian_vault"]) / "003_原始输出" / saved["name"]).read_text(encoding="utf-8")
    assert "直接说的一段。" in note and "别人的材料" not in note
    for _ in range(100):
        if next(t for t in client.get("/api/topics").json() if t["id"] == tid)["outline_state"] != "running":
            break
        time.sleep(0.05)
