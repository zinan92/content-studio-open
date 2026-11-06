from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_line
from content_studio.x_post import XError


@pytest.fixture(autouse=True)
def _park_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """10/6 起程序不再默认 作者 的 GitHub 和网站（装到别人电脑上空着就是空着）；这些测试照旧拿它们当样本。"""
    monkeypatch.setenv("CONTENT_STUDIO_X_GITHUB", "zinan92")
    monkeypatch.setenv("CONTENT_STUDIO_X_SITE", "https://example.com")


REPOS = [
    {"name": "trading", "description": "交易系统", "html_url": "https://github.com/zinan92/trading", "pushed_at": "2026-10-04T09:00:00Z",
     "private": False, "fork": False, "archived": False, "stargazers_count": 3},
    {"name": "my-private-notes", "description": "私有", "html_url": "https://github.com/zinan92/my-private-notes",
     "pushed_at": "2026-10-04T08:00:00Z", "private": True, "fork": False, "archived": False, "stargazers_count": 0},
    {"name": "someone-else", "description": "fork", "html_url": "u", "pushed_at": None, "private": False, "fork": True, "archived": False},
]
PRINCIPLES = {"ok": True, "state": {"principles": [{"id": "p012", "primaryCategory": "universal", "quote": "在快速变化的世界中找到不变的东西。"}]}}
PREDICTIONS = {"ok": True, "state": {"predictions": [{"id": "pred-001", "quote": "大模型会成为所有服务的入口。", "horizon": "long", "status": "open"}]}}
GOODPRODUCT = [{"id": "gp-013", "title": "fomomo：交易终端", "kind": "inspiration", "note": "别人的产品说明", "collected_at": "2026-09-09", "source_url": None}]


def fake_fetch(url: str):
    if "api.github.com" in url:
        return REPOS
    if url.endswith("/api/principles"):
        return PRINCIPLES
    if url.endswith("/api/predictions"):
        return PREDICTIONS
    if url.endswith("/goodproduct/manifest.json"):
        return GOODPRODUCT
    raise AssertionError(url)


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    raw = root / "003_原始输出" / "认知提升"
    raw.mkdir(parents=True)
    (raw / "always-on.md").write_text("# Always On\n工具一直在变。", encoding="utf-8")
    (root / "003_原始输出" / "客户咨询1.md").write_text("# 客户\n客户的隐私", encoding="utf-8")
    clip = root / "002_clippings"
    clip.mkdir()
    (clip / "a.md").write_text("---\ntitle: 别人的文章\nsource: https://x.com/1\n---\n别人的长篇正文", encoding="utf-8")
    bench = root / "002_对标内容"
    bench.mkdir()
    (bench / "b.md").write_text("---\ntitle: 对标转写\npublished: 2026-10-04\n---\n对标的话", encoding="utf-8")
    return root


def test_github_lists_only_public_own_repos() -> None:
    """私有仓库永远不进候选：这里的东西是要发到公开的 X 上的。"""
    cards = x_line.github_cards(fake_fetch)
    assert [c["title"] for c in cards] == ["trading"]
    assert cards[0]["prefill"] == "交易系统\nhttps://github.com/zinan92/trading"


def test_site_sources_prefill_his_own_words_but_not_others(tmp_path: Path) -> None:
    assert x_line.principle_cards(fake_fetch)[0]["prefill"] == "在快速变化的世界中找到不变的东西。"
    pred = x_line.prediction_cards(fake_fetch)[0]
    assert pred["prefill"] == "大模型会成为所有服务的入口。" and pred["tag"] == "待验证"
    gp = x_line.goodproduct_cards(fake_fetch)[0]
    assert gp["own"] is False and "别人的产品说明" not in gp["prefill"] and gp["prefill"].startswith("fomomo")


def test_obsidian_is_his_writing_and_inbox_titles_only(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    groups = {g["key"]: g for g in x_line.gather(str(root), cache=x_line.Cache(), fetch=fake_fetch)}
    mine = groups["obsidian"]["items"]
    assert [c["title"] for c in mine] == ["Always On"]  # 客户咨询不列
    assert mine[0]["prefill"] == "工具一直在变。"  # 发到 X 的不带 Markdown 标题
    inbox = groups["inbox"]["items"]
    assert [c["title"] for c in inbox] == ["别人的文章"] and "别人的长篇正文" not in inbox[0]["prefill"]
    assert all("对标" not in c["title"] for g in groups.values() for c in g["items"])


def test_a_broken_source_does_not_break_the_page(tmp_path: Path) -> None:
    def down(url: str):
        if "github" in url:
            raise x_line.XLineError("github 返回 503")
        return fake_fetch(url)

    groups = {g["key"]: g for g in x_line.gather(str(_vault(tmp_path)), cache=x_line.Cache(), fetch=down)}
    assert groups["github"]["error"] == "github 返回 503" and groups["principle"]["items"]


def test_remote_sources_are_cached() -> None:
    calls = []
    cache = x_line.Cache(ttl=60, clock=lambda: 0.0)
    for _ in range(2):
        cache.get("github", lambda: calls.append(1) or [])
    assert len(calls) == 1
    cache.get("github", lambda: calls.append(1) or [], fresh=True)
    assert len(calls) == 2


def test_organize_keeps_his_words_and_rejects_rewrites() -> None:
    said = "就是说，我觉得吧，工具一直在变。然后呢，如果你认同这个判断，那么所有人都会失业。"
    good = "<<<POST>>>\n工具一直在变。\n<<<END>>>\n<<<POST>>>\n如果你认同这个判断，那么所有人都会失业。\n<<<END>>>"
    assert x_line.organize(said, write_fn=lambda p: good) == ["工具一直在变。", "如果你认同这个判断，那么所有人都会失业。"]
    prompts = []
    rewrite = "<<<POST>>>\n时代浪潮不可逆转，白领岗位终将消失。\n<<<END>>>"
    with pytest.raises(x_line.XLineError, match="改动太多"):
        x_line.organize(said, write_fn=lambda p: prompts.append(p) or rewrite)
    assert "不改词" in prompts[0] and "改动太多" in prompts[1]


def test_reordered_posts_are_not_penalised_for_the_seam() -> None:
    said = "嗯，第一，X 内容自由。然后呢，第二，形式灵活，长短都可以。你看，第三，更新高效。"
    posts = ["更新高效。", "形式灵活，长短都可以。", "X 内容自由。"]
    assert x_line.posts_fidelity(posts, said) == 1.0


def test_today_counts_beijing_day(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    x_line.record_post(path, text="a", source_id=None, how="manual", now=datetime(2026, 10, 3, 17, 0, tzinfo=timezone.utc))  # 北京 10/4 01:00
    x_line.record_post(path, text="b", source_id=None, how="manual", now=datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc))  # 北京 10/3 23:00
    posts = x_line.load_state(path)["posts"]
    assert x_line.today_count(posts, now=datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)) == 1


@pytest.fixture
def client_factory(tmp_path: Path):
    import json

    from content_studio import web

    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    clients = []

    def make(**kw) -> TestClient:
        app = web.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                             downloads_dir=tmp_path / "dl", start_worker=False, **kw)
        c = TestClient(app, headers={"X-Content-Studio": "1"})
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def test_api_post_skip_and_failure(client_factory, tmp_path: Path) -> None:
    sent = []

    def post(text: str) -> dict:
        if "429" in text:
            raise XError("X 说超额了（429）")
        sent.append(text)
        return {"id": "1", "url": "https://x.com/i/web/status/1"}

    client: TestClient = client_factory(x_fetch_fn=fake_fetch, x_post_fn=post)
    client.put("/api/settings", json={"obsidian_vault": str(_vault(tmp_path))})
    data = client.get("/api/xline").json()
    assert [s["key"] for s in data["sources"]] == ["obsidian", "github", "principle", "prediction", "goodproduct", "inbox"]
    assert data["today"] == 0

    r = client.post("/api/xline/post", json={"text": "在快速变化的世界中找到不变的东西。", "source_id": "principle:p012"})
    assert r.status_code == 200 and sent == ["在快速变化的世界中找到不变的东西。"]
    failed = client.post("/api/xline/post", json={"text": "429 了"})
    assert failed.status_code == 400 and "超额" in failed.json()["detail"]
    client.post("/api/xline/posted", json={"text": "长帖，复制去发的"})
    client.post("/api/xline/skip", json={"source_id": "github:trading"})

    data = client.get("/api/xline").json()
    assert data["today"] == 2 and data["used"] == ["principle:p012"] and data["skipped"] == ["github:trading"]
    assert data["posts"][0]["how"] == "manual" and data["posts"][1]["url"].endswith("/1")


def test_x_daily_machine_is_off_until_turned_back_on(client_factory) -> None:
    """10/19 作者：「X 后台每天排短帖、长文的那套也关掉」。默认关；PUT x_daily 才重新开。实时数据不受影响。"""
    c = client_factory()
    assert c.app.state.store.settings()["x_daily"] is False
    assert c.app.state.x_daily_on() is False
    c.put("/api/settings", json={"x_daily": True}).raise_for_status()
    assert c.app.state.x_daily_on() is True
    c.put("/api/settings", json={"x_daily": False}).raise_for_status()
    assert c.app.state.x_daily_on() is False
