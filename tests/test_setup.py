"""「开始用」三步（10/6 作者：装到别人电脑上，第一次打开不看报错、不碰终端、不改文件）：你是谁、连上抖音、素材在哪。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_web import SEC, client  # noqa: F401


def test_setup_profile_writes_profile_and_registers_my_douyin(client: TestClient) -> None:
    before = client.get("/api/state").json()
    assert before["setup"]["present"] is False and "profile.example" not in before["setup"]["hint"]
    r = client.post("/api/setup/profile", json={"brand": "小王工作室", "name": "小王", "douyin": f"https://www.douyin.com/user/{SEC}", "editor": "小李", "boss": "老张"})
    assert r.status_code == 200, r.text
    path = Path(r.json()["path"])
    assert path == Path(os.environ["CONTENT_STUDIO_HOME"]) / "profile.yaml" and path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "小王工作室" in text and "name: 小王" in text and "backend: claude-cli" in text and "editor: 小李" in text
    st = client.get("/api/state").json()
    assert st["setup"]["present"] is True
    assert st["self_account"] is not None
    # 再填一次只改给的项，别的留着
    client.post("/api/setup/profile", json={"boss": "老李"})
    text = path.read_text(encoding="utf-8")
    assert "name: 小王" in text and "boss: 老李" in text and "editor: 小李" in text
    assert client.post("/api/setup/profile", json={}).status_code == 400
    assert client.post("/api/setup/profile", json={"douyin": "https://example.com/me"}).status_code == 400


def test_setup_cookies_saves_a_private_file_and_explains_bad_input(client: TestClient) -> None:
    r = client.post("/api/setup/cookies", json={"text": json.dumps([{"name": "sessionid", "value": "abc", "domain": ".douyin.com"}, {"name": "x", "value": ""}])})
    assert r.status_code == 200 and r.json()["count"] == 1
    # /api/state 说 ok，就是文件写出来了而且权限是 600（load_cookie_file 不认更松的权限）
    assert client.get("/api/state").json()["cookies"]["ok"] is True
    said = lambda r: str(r.json().get("detail") or r.json().get("error") or "")  # noqa: E731
    bad = client.post("/api/setup/cookies", json={"text": "not json"})
    assert bad.status_code == 400 and "JSON" in said(bad)
    empty = client.post("/api/setup/cookies", json={"text": "[]"})
    assert empty.status_code == 400 and "没有 cookies" in said(empty)


def test_brand_names_the_two_assistants_and_x_sources_default_to_nothing() -> None:
    from content_studio import conf

    b = conf.brand({})
    assert b["editor"] == "Anna" and b["boss"] == "Wendy"
    assert conf.brand({"brand": {"editor": "小李"}})["editor"] == "小李"
    assert conf.ENV_MAP["x_line.github_user"][1] == "" and conf.ENV_MAP["x_line.site"][1] == ""


def test_pages_no_longer_hard_code_park(client: TestClient) -> None:
    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    index = (static / "index.html").read_text(encoding="utf-8")
    assert "cdnjs.cloudflare.com" not in index and 'src="/static/vendor/marked.min.js"' in index
    assert 'rel="preload" as="style"' in index  # 字体不挡首屏
    for name in ("input.js", "speak.js", "board.js", "anna.js"):
        assert "003_原始输出" not in (static / name).read_text(encoding="utf-8"), name
    assert "作者 原始输出" not in (static / "input.js").read_text(encoding="utf-8")
    app_js = (static / "app.js").read_text(encoding="utf-8")
    assert "权限 600" not in app_js and "profile.example.yaml" not in app_js and "setupCard(" in app_js
    assert client.get("/api/state").json()["vault_folders"]["raw"]
