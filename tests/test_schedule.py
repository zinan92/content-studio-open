"""02 排期（10/6 作者）：选题包拖进日历、回收站、一键写开头和骨架。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import coupon, schedule
from content_studio.extras.consults import consult
from tests.test_coupon import _good
from tests.test_web import client  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _consults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))


def _topic(client: TestClient, title: str, **fields) -> dict:
    return client.post("/api/topics", json={"title": title, "formats": "video", **fields}).json()


def _queue(client: TestClient) -> list:
    return [n["pack"]["title"] if n["pack"] else n["text"] for n in client.get("/api/schedule").json()["queue"]]


def _focus(client: TestClient):
    t = client.app.state.store.focus_topic()
    return t["title"] if t else None


def test_only_do_this_one_starts_a_topic_and_one_at_a_time(client: TestClient) -> None:
    """10/19 作者 拿掉排期：选题 →「我的选题」点「做这条」才开始做；整条流水线上一次只有一条，没有「换成这条」；
    发完不会自动接上旧清单里的下一条。"""
    a, b, c = (_topic(client, t) for t in ("甲", "乙", "丙"))
    client.post("/api/today/queue", json={"topic_ids": [b["id"], c["id"]]})  # 旧清单里排着的
    mine = client.get("/api/my-topics").json()
    assert mine["focus"] is None and mine["held"] is None and _focus(client) is None  # 清单第一条不再自己变成正在做
    assert [p["title"] for p in mine["pool"]] == ["丙", "乙", "甲"]  # 新的在上，旧清单里的也在
    client.post(f"/api/topics/{a['id']}/focus").raise_for_status()
    mine = client.get("/api/my-topics").json()
    assert mine["focus"]["title"] == "甲" and "《甲》还没发完" in mine["held"] and [p["title"] for p in mine["pool"]] == ["丙", "乙"]
    refused = client.post(f"/api/topics/{b['id']}/focus")
    assert refused.status_code == 400 and "一次只做一条" in refused.json()["error"]
    # 不做了：归档进「不做了的」，正在做的空出来；放回：回到我的选题
    client.patch(f"/api/topics/{a['id']}", json={"archived": True}).raise_for_status()
    mine = client.get("/api/my-topics").json()
    assert mine["focus"] is None and [p["title"] for p in mine["trash"]] == ["甲"] and _focus(client) is None
    client.patch(f"/api/topics/{a['id']}", json={"archived": False}).raise_for_status()
    assert "甲" in [p["title"] for p in client.get("/api/my-topics").json()["pool"]]
    # 发完：正在做的空出来，不接旧清单
    client.post(f"/api/topics/{c['id']}/focus").raise_for_status()
    client.app.state.store.update_topic(c["id"], closed_at="2026-10-19T12:00:00+00:00")
    client.get("/api/schedule")
    assert client.get("/api/my-topics").json()["focus"] is None and _focus(client) in (None, "丙")
    assert client.post(f"/api/topics/{b['id']}/focus").status_code == 200


def test_calendar_has_no_gaps(client: TestClient) -> None:
    a, b = _topic(client, "甲"), _topic(client, "乙")
    client.post("/api/schedule/place", json={"topic_id": a["id"], "at": 0})
    s = client.post("/api/schedule/place", json={"topic_id": b["id"], "at": 20}).json()
    # 拖到第 20 天：落在第一个空的日子
    assert [n["day"] for n in s["queue"]] == [s["first"], (date.fromisoformat(s["first"]) + timedelta(days=1)).isoformat()]
    assert s["pool"] == []


def test_trash_and_back(client: TestClient, tmp_path: Path) -> None:
    store = client.app.state.store
    note = "003_原始输出/想法.md"
    a = _topic(client, "甲", note_paths=[note])
    store.set_triage(note, "topic")
    b = _topic(client, "乙")
    client.post("/api/schedule/place", json={"topic_id": a["id"], "at": 0})
    client.post("/api/schedule/place", json={"topic_id": b["id"], "at": 1})
    # 正在做的扔进回收站：日历上没了；10/19 起下一条不自动接上
    s = client.post("/api/schedule/trash", json={"topic_id": a["id"]}).json()
    assert [n["pack"]["title"] for n in s["queue"]] == ["乙"] and _focus(client) is None
    assert [p["title"] for p in s["trash"]] == ["甲"] and store.triage().get(note) is None
    with pytest.raises(Exception):
        client.post("/api/schedule/place", json={"topic_id": a["id"], "at": 1}).raise_for_status()
    # 拖回选题池：不在回收站了，笔记重新算「拿来做」，进项不会让他建第二个
    s = client.post("/api/schedule/pool", json={"topic_id": a["id"]}).json()
    assert s["trash"] == [] and "甲" in [p["title"] for p in s["pool"]]
    assert store.triage()[note]["status"] == "topic"


def test_handwritten_line_becomes_a_pack(client: TestClient) -> None:
    client.post("/api/today/notes", json={"text": "手写的一条"})
    s = client.get("/api/schedule").json()
    line = s["queue"][0]
    assert line["topic_id"] is None and line["pack"] is None
    # 扔进回收站也能拖回来：先建成选题再归档
    s = client.post("/api/schedule/trash", json={"note_id": line["id"]}).json()
    assert s["queue"] == [] and [p["title"] for p in s["trash"]] == ["手写的一条"]


def test_write_button_only_writes_packs_with_his_own_words(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = client.app.state.store
    vault = tmp_path / "vault-default"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "想法.md").write_text("# 想法\n\n大多数人以为是能力问题，其实是位置问题。\n", encoding="utf-8")
    (vault / "002_clippings").mkdir(parents=True)
    (vault / "002_clippings" / "别人.md").write_text("# 别人\n\n别人写的东西。\n", encoding="utf-8")
    mine = _topic(client, "我说过的", note_paths=["003_原始输出/想法.md"])
    edited = _topic(client, "我改过骨架的", note_paths=["003_原始输出/想法.md"])
    path = tmp_path / "drafts" / f"topic-{edited['id']}" / "skeleton.md"
    path.parent.mkdir(parents=True)
    path.write_text("# 我改过的\n\n## 开头候选\n1. 原话\n", encoding="utf-8")
    store.update_topic(edited["id"], outline_path=str(path))
    _topic(client, "别人的", note_paths=["002_clippings/别人.md"])
    _topic(client, "空的")

    s = client.get("/api/schedule").json()
    assert s["write"]["can"] == 2 and s["write"]["skip"] == "1 包只有别人的材料，1 包还没有材料"
    packs = {p["title"]: p for p in s["pool"]}
    assert packs["我说过的"]["words"] and not packs["别人的"]["words"]
    assert packs["我改过骨架的"]["hook"] and packs["我改过骨架的"]["skeleton"] and not packs["我改过骨架的"]["coupon"]

    (tmp_path / "workflows" / coupon.FRAMEWORK_FILE).write_text("# 付息稿\n每 10 秒付一次息。", encoding="utf-8")
    fake = tmp_path / "fake_coupon.py"
    fake.write_text(f"import sys; sys.stdin.read(); print({_good()!r})", encoding="utf-8")
    monkeypatch.setenv(coupon.COUPON_COMMAND_ENV, f"{sys.executable} {fake}")
    res = client.post("/api/schedule/write").json()
    assert res["started"] and "2 包" in res["message"]
    for _ in range(300):
        job = client.get("/api/schedule").json()["write"]["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["wrote"] == 2 and job["failed"] == [] and job["skip"] == "1 包只有别人的材料，1 包还没有材料"
    packs = {p["title"]: p for p in client.get("/api/schedule").json()["pool"]}
    assert packs["我说过的"]["skeleton"] and packs["我说过的"]["coupon"]
    assert packs["我改过骨架的"]["coupon"]
    assert path.read_text(encoding="utf-8").startswith("# 我改过的")  # 已有的不覆盖
    assert not packs["别人的"]["skeleton"] and not packs["空的"]["skeleton"]
    # 都写好了：再按没有能写的
    again = client.post("/api/schedule/write").json()
    assert again["started"] is False and "没有能写的包" in again["message"]
    assert (tmp_path / "drafts" / schedule.STATE_FILE).is_file()


def test_nothing_is_prepared_for_the_next_one_until_this_one_ships(client: TestClient, tmp_path: Path) -> None:
    # 10/13 作者：「备料也不要，一条做完再备下一条」。正在做的没发完，别的包不出骨架、口播稿、付息稿。
    store = client.app.state.store
    vault = tmp_path / "vault-default"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "想法.md").write_text("# 想法\n\n大多数人以为是能力问题，其实是位置问题。\n", encoding="utf-8")
    now = _topic(client, "正在做的", note_paths=["003_原始输出/想法.md"])
    nxt = _topic(client, "下一条", note_paths=["003_原始输出/想法.md"])
    client.post("/api/schedule/place", json={"topic_id": now["id"], "at": 0})
    client.post("/api/schedule/place", json={"topic_id": nxt["id"], "at": 1})

    s = client.get("/api/schedule").json()
    assert s["write"]["can"] == 1 and "《正在做的》还没发完" in s["write"]["held"]  # 只剩正在做的这一条能备
    held = {p["title"]: p["held"] for p in s["pool"] + [q["pack"] for q in s["queue"] if q["pack"]]}
    assert held == {"正在做的": False, "下一条": True}
    for refused in (client.post(f"/api/topics/{nxt['id']}/outline"), client.post(f"/api/topics/{nxt['id']}/script", json={"source": "paste", "text": "x" * 400})):
        assert refused.status_code in (400, 409) and "还没发完" in (refused.json().get("error") or refused.json().get("detail"))
    assert not store.topic(nxt["id"]).get("outline_path")

    store.update_topic(now["id"], closed_at="2026-10-13T12:00:00+00:00")  # 发完了
    client.post(f"/api/topics/{nxt['id']}/focus").raise_for_status()  # 10/19：发完由他点「做这条」接下一条
    s = client.get("/api/schedule").json()
    assert s["write"]["can"] == 1 and _focus(client) == "下一条"
    assert client.post(f"/api/topics/{nxt['id']}/outline").status_code != 400


def test_own_words_means_his_raw_folder() -> None:
    assert schedule.own_words({"note_paths": ["003_原始输出/系列1 一环一个 Skill/05 对标.md"]}, "003_原始输出")
    assert not schedule.own_words({"note_paths": ["002_clippings/a.md"]}, "003_原始输出")
    assert not schedule.own_words({"note_paths": []}, "003_原始输出")
    assert schedule.skip_line(28, 0) == "28 包还没说，没有你的原话"
