"""在哪找到我（10/6 作者：GitHub 和个人网站放进工作台，只给自己点）：profile 里只存一处，X 页素材读同一份。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import conf
from content_studio.extras.xline import x_line
from tests.test_web import client  # noqa: F401

ENVS = ("CONTENT_STUDIO_X_GITHUB", "CONTENT_STUDIO_X_SITE")


@pytest.fixture(autouse=True)
def _no_links(monkeypatch: pytest.MonkeyPatch) -> None:
    # conf.apply / 保存会直接写 os.environ；先 setenv 记下原样，测完还原，不漏到别的测试
    for env in ENVS:
        monkeypatch.setenv(env, "")
        monkeypatch.delenv(env)


def test_github_takes_a_login_or_a_profile_link() -> None:
    for raw in ("zinan92", "@zinan92", "https://github.com/zinan92", "github.com/zinan92/", "https://www.github.com/zinan92?tab=repositories"):
        assert conf.github_login(raw) == "zinan92", raw
    for raw in ("", "https://gitlab.com/zinan92", "not a login!", None):
        assert conf.github_login(raw) == "", raw


def test_site_gets_a_scheme_and_loses_the_trailing_slash() -> None:
    assert conf.site_url("example.com/") == "https://example.com"
    assert conf.site_url("http://example.com/about") == "http://example.com/about"
    assert conf.site_url("随便写的") == "" and conf.site_url("") == ""


def test_me_fields_win_over_the_old_x_line_place() -> None:
    written = conf.apply({"me": {"github": "https://github.com/new-me", "site": "new.example.com"},
                          "x_line": {"github_user": "old-me", "site": "https://old.example.com"}})
    assert "me.github" in written and "x_line.github_user" not in written
    assert conf.me_links() == {"github_user": "new-me", "github": "https://github.com/new-me", "site": "https://new.example.com"}
    assert x_line.github_user() == "new-me" and x_line.site() == "https://new.example.com"


def test_old_x_line_place_still_works_when_me_is_empty() -> None:
    conf.apply({"x_line": {"github_user": "zinan92", "site": "https://example.com/"}})
    assert x_line.github_user() == "zinan92" and x_line.site() == "https://example.com"
    assert conf.me_links()["github"] == "https://github.com/zinan92"


def test_saving_writes_one_place_and_takes_effect_now(client: TestClient) -> None:
    empty = client.get("/api/me/links").json()
    assert empty["github"] == "" and empty["site"] == ""
    path = Path(os.environ["CONTENT_STUDIO_HOME"]) / "profile.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x_line:\n  github_user: old-me\n  site: https://old.example.com\n", encoding="utf-8")

    r = client.put("/api/me/links", json={"github": "https://github.com/zinan92", "site": "example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["github"] == "https://github.com/zinan92" and r.json()["site"] == "https://example.com"
    text = path.read_text(encoding="utf-8")
    assert "github: zinan92" in text and "site: https://example.com" in text and "old-me" not in text
    assert x_line.github_user() == "zinan92"

    # 清空就是清空：老地方也清掉了，重启不会冒回来
    assert client.put("/api/me/links", json={"github": "", "site": ""}).json()["github"] == ""
    assert x_line.github_user() == "" and x_line.site() == ""
    assert "old-me" not in path.read_text(encoding="utf-8")


def test_saving_explains_bad_input(client: TestClient) -> None:
    bad = client.put("/api/me/links", json={"github": "https://gitlab.com/me"})
    assert bad.status_code == 400 and "GitHub" in str(bad.json())
    assert client.put("/api/me/links", json={"site": "不是网址"}).status_code == 400
