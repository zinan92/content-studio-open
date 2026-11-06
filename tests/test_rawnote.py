"""进项「作者 原始输出」里直接新建一篇：他写的字原样存进 003，不改写、不覆盖；系列文件夹不在这里选。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from content_studio import vault
from test_web import client  # noqa: F401 - fixture


def test_new_note_is_written_into_raw_output_as_he_wrote_it(client: TestClient) -> None:
    vault_dir = Path(client.app.state.store.settings()["obsidian_vault"])
    raw = vault_dir / "003_原始输出"
    (raw / "认知提升").mkdir(parents=True)
    (raw / "assets").mkdir()
    (raw / "系列1 工作台").mkdir()

    assert client.get("/api/vault/raw-folders").json()["folders"] == ["", "认知提升"]  # 没有附件和系列

    assert client.post("/api/vault/raw-note", json={"title": "空的", "body": "  "}).status_code == 400
    assert client.post("/api/vault/raw-note", json={"folder": "../", "body": "x"}).status_code == 400
    assert client.post("/api/vault/raw-note", json={"folder": "系列1 工作台", "body": "x"}).status_code == 400

    body = "嗯，闭环比终局重要。\n\n小闭环先闭。"
    made = client.post("/api/vault/raw-note", json={"folder": "认知提升", "title": "闭环 vs 终局", "body": body}).json()
    note = raw / "认知提升" / "闭环 vs 终局.md"
    assert made["path"] == "003_原始输出/认知提升/闭环 vs 终局.md" and note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "type: 原始输出" in text and "# 闭环 vs 终局" in text and text.rstrip().endswith(body)  # 一个字都不改

    again = client.post("/api/vault/raw-note", json={"folder": "认知提升", "title": "闭环 vs 终局", "body": "第二篇"}).json()
    assert again["name"] == "闭环 vs 终局-2.md" and note.read_text(encoding="utf-8") == text  # 不覆盖

    untitled = client.post("/api/vault/raw-note", json={"body": "没写标题的时候用第一句\n第二行"}).json()
    assert untitled["path"] == "003_原始输出/没写标题的时候用第一句.md"

    paths = {i["path"] for i in vault.inbox(str(vault_dir), since=datetime(2000, 1, 1), sources=("raw",))}
    assert {made["path"], untitled["path"]} <= paths  # 进项里马上能看到
