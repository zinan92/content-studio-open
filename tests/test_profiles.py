"""对外简介：一个 Obsidian 文件两段（国内版 / X 版）；各平台只记改没改（9/30 作者）。"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.positioning import x_profile
from content_studio.extras.positioning import profiles
from tests.test_web import client  # noqa: F401 - fixture


def _file(tmp_path: Path) -> Path:
    return tmp_path / "vault-default" / profiles.FILE


def test_one_file_two_versions_and_edits_write_back(client: TestClient, tmp_path: Path) -> None:
    f = _file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("张三\n\n新加坡国立大学金融 × 计算机\n1v1 咨询\n![[头像.png]]\n", encoding="utf-8")
    d = client.get("/api/profile").json()
    v = d["profile"]["variants"]
    assert v["cn"] == {"name": "张三", "bio": "新加坡国立大学金融 × 计算机\n1v1 咨询"} and v["x"] == {"name": "", "bio": ""}
    assert d["profile"]["embeds"] == 1 and d["profile"]["obsidian"].startswith("obsidian://open?path=")
    assert [x["key"] for x in d["variants"]] == ["cn", "x"] and d["variants"][1]["limits"] == {"name": 50, "bio": 160}

    # 写 X 版：国内版一个字不动，图那一行留在最后
    res = client.put("/api/profile/x", json={"name": "作者｜内容工作台", "bio": "一人公司｜给老板做 AI 诊断\n咨询私信「动手」", "mtime": d["profile"]["mtime"]})
    assert res.status_code == 200
    text = f.read_text(encoding="utf-8")
    assert text.startswith("张三\n\n新加坡国立大学金融 × 计算机\n1v1 咨询\n\n## X 版\n\n作者｜内容工作台\n\n一人公司｜给老板做 AI 诊断\n咨询私信「动手」")
    assert text.rstrip().endswith("![[头像.png]]")
    v = client.get("/api/profile").json()["profile"]["variants"]
    assert v["x"]["bio"] == "一人公司｜给老板做 AI 诊断\n咨询私信「动手」" and v["cn"]["name"] == "张三"

    # X 的上限知道：超了就拦；国内版不拦
    assert client.put("/api/profile/x", json={"name": "作者", "bio": "字" * 161}).status_code == 400
    assert client.put("/api/profile/cn", json={"name": "张三", "bio": "字" * 300}).status_code == 200
    assert client.put("/api/profile/cn", json={"name": "", "bio": "x"}).status_code == 400

    # 在 Obsidian 里又改过：带着旧的修改时间来存，不能盖掉
    m = client.get("/api/profile").json()["profile"]["mtime"]
    f.write_text("作者\n\n在 Obsidian 里改的\n", encoding="utf-8")
    os.utime(f, (m + 50, m + 50))
    stale = client.put("/api/profile/cn", json={"name": "x", "bio": "y", "mtime": m})
    assert stale.status_code == 400 and "Obsidian" in stale.json()["error"]
    assert client.get("/api/profile").json()["profile"]["variants"]["cn"]["bio"] == "在 Obsidian 里改的"


def test_each_platform_tracks_its_own_version(client: TestClient, tmp_path: Path) -> None:
    client.put("/api/settings", json={"platform_accounts": {"x": {"on": True, "handle": ""}, "bilibili": {"on": True, "handle": ""}}})
    client.put("/api/profile/cn", json={"name": "作者", "bio": "国内第一版"})
    m = client.get("/api/profile").json()["profile"]["mtime"]
    client.put("/api/profile/x", json={"name": "作者", "bio": "X 第一版", "mtime": m})
    rows = lambda: {p["key"]: (p["variant"], p["state"]) for p in client.get("/api/profile").json()["platforms"]}  # noqa: E731
    assert rows() == {"douyin": ("cn", "never"), "bilibili": ("cn", "never"), "x": ("x", "never")}
    client.post("/api/profile/applied/bilibili")
    client.post("/api/profile/applied/x")
    assert rows()["bilibili"][1] == "synced" and rows()["x"][1] == "synced"
    # 只改 X 版：X 要更新，B 站不受影响
    m = client.get("/api/profile").json()["profile"]["mtime"]
    client.put("/api/profile/x", json={"name": "作者", "bio": "X 第二版", "mtime": m})
    assert rows()["x"][1] == "stale" and rows()["bilibili"][1] == "synced"
    assert client.post("/api/profile/applied/nope").status_code == 400


def test_x_update_signs_the_form_and_only_sends_what_is_filled() -> None:
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout=30):
        seen["url"], seen["body"], seen["auth"] = request.full_url, request.data.decode(), request.headers["Authorization"]
        return Resp(json.dumps({"name": "作者｜内容工作台", "description": "一人公司", "location": "Singapore"}).encode())

    creds = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_secret": "a"}
    live = x_profile.update(name="作者｜内容工作台", bio="一人公司", creds=creds, opener=opener)
    assert seen["url"].endswith("/1.1/account/update_profile.json")
    assert "name=" in seen["body"] and "description=" in seen["body"] and "url=" not in seen["body"]
    assert "oauth_signature=" in seen["auth"] and live["location"] == "Singapore"
    with pytest.raises(Exception, match="没有要改的"):
        x_profile.update(name="", bio="", creds=creds, opener=opener)
