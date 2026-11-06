"""系列：建系列（起名 + 每集标题）→ 每集进选题池 → 在 Obsidian 改标题，池子跟着变 → 说这集 → 存进系列文件夹。"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from content_studio import vault
from content_studio.extras.series import series
from test_web import client  # noqa: F401 - fixture


def test_index_lines_are_episodes_and_other_lines_are_not() -> None:
    text = "---\ntype: 系列\n---\n\n# 系列1 工作台\n\n一行一集。\n\n1. 为什么自己搭\n2、今天页\n- 打包\n1. 为什么自己搭\n"
    assert series.parse(text) == ["为什么自己搭", "今天页", "打包"]
    assert series.episode_note_name(2, "今天页: 只盯出摊") == "02 今天页 只盯出摊"


def _wait_outline(client: TestClient, tid: int) -> None:
    for _ in range(100):  # 等骨架写完，别让后台线程撞上测试收尾
        if next(t for t in client.get("/api/topics").json() if t["id"] == tid)["outline_state"] != "running":
            return
        time.sleep(0.05)


def test_series_lives_in_obsidian_and_its_episodes_sit_in_the_topic_pool(client: TestClient) -> None:
    vault_dir = Path(client.app.state.store.settings()["obsidian_vault"])
    raw = vault_dir / "003_原始输出"
    raw.mkdir(parents=True)

    assert client.post("/api/series", json={"name": "工作台", "titles": ""}).status_code == 400
    made = client.post("/api/series", json={"name": "工作台", "titles": "1. 为什么自己搭\n2. 今天页\n\n"}).json()["series"]
    assert made["folder"] == "系列1 工作台" and [e["title"] for e in made["episodes"]] == ["为什么自己搭", "今天页"]
    assert (raw / "系列1 工作台" / "系列.md").is_file()
    assert client.post("/api/series", json={"name": "系列1 工作台", "titles": "x"}).status_code == 400  # 不覆盖

    board = client.get("/api/board").json()
    eps = board["series"][0]["episodes"]
    assert [(e["n"], e["title"], e["state"], e["said"]) for e in eps] == [(1, "为什么自己搭", "pool", False), (2, "今天页", "pool", False)]
    cards = {c["id"]: c for c in board["pool"]}
    assert all(cards[e["topic_id"]]["replicate"]["series"] == "系列1 工作台" for e in eps)
    assert len(client.get("/api/board").json()["pool"]) == len(board["pool"])  # 再看一遍不会重复建

    # 在 Obsidian 里改：第 2 集换了标题、加了第 3 集 → 旧的那条（没说、没开做）拿掉，新的进池子
    index = raw / "系列1 工作台" / "系列.md"
    index.write_text(index.read_text(encoding="utf-8").replace("2. 今天页", "2. 今天页只盯出摊\n3. 打包"), encoding="utf-8")
    board = client.get("/api/board").json()
    assert [e["title"] for e in board["series"][0]["episodes"]] == ["为什么自己搭", "今天页只盯出摊", "打包"]
    assert eps[1]["topic_id"] not in {c["id"] for c in board["pool"]}
    assert client.app.state.store.topic(eps[1]["topic_id"])["archived_at"]

    # 说这集：左边是这个系列的每集标题，右边说；存进系列文件夹，文件名「编号 标题」
    tid = eps[0]["topic_id"]
    started = client.post(f"/api/topics/{tid}/replicate", json={"mode": "series"}).json()
    assert started["topic"]["is_focus"] and started["speak"]["episode"] == 1
    assert [e["title"] for e in started["speak"]["series_episodes"]][:1] == ["为什么自己搭"]
    assert client.get("/api/board").json()["series"][0]["episodes"][0]["state"] == "focus"
    client.put(f"/api/topics/{tid}/speak", json={"dictation": "我为什么自己搭一个工作台：因为没有一个现成的能管住我出摊。"})
    saved = client.post(f"/api/topics/{tid}/speak/save", json={"title": "随便改的标题"}).json()
    note = raw / "系列1 工作台" / "01 为什么自己搭.md"
    assert saved["name"] == note.name and note.is_file()
    assert sorted(p.name for p in note.parent.iterdir()) == [note.name, "系列.md"]  # 工作台自己的文件不进 Obsidian
    text = note.read_text(encoding="utf-8")
    assert "能管住我出摊" in text and "series: 系列1 工作台" in text and "structure_from" not in text
    topic = next(t for t in client.get("/api/topics").json() if t["id"] == tid)
    assert topic["title"] == "为什么自己搭" and saved["path"] in topic["note_paths"]  # 标题跟着 系列.md，不改名
    _wait_outline(client, tid)
    done = client.app.state.store.topic(tid)
    assert done["outline_path"] and not done["outline_error"]  # 骨架照常写：一集没有拆解也不影响
    assert client.get("/api/board").json()["series"][0]["episodes"][0]["said"] is True

    # 系列.md 是目录，不是他说的一段话：进项里没有它，说完的那集有
    paths = {i["path"] for i in vault.inbox(str(vault_dir), since=datetime(2000, 1, 1), sources=("raw",))}
    assert "003_原始输出/系列1 工作台/01 为什么自己搭.md" in paths
    assert not any(p.endswith("系列.md") for p in paths)

    # 第二个系列自己排号
    assert client.post("/api/series", json={"name": "交易", "titles": ["怎么守住 beta"]}).json()["series"]["folder"] == "系列2 交易"
