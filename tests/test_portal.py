"""门户（10/6 作者）：GitHub 和网站每天截一次第一屏，AI 当陌生人判断能不能当好门户。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from content_studio.web import STATIC_DIR
from content_studio.extras.portal import portal
from tests.test_web import client  # noqa: F401

ENVS = ("CONTENT_STUDIO_X_GITHUB", "CONTENT_STUDIO_X_SITE")
GOOD = {"checks": [{"k": k, "ok": k != "proof", "note": f"看到了 {k}"} for k, _ in portal.CHECKS],
        "verdict": "像个门户，就是缺证据", "fix": "首屏加一行做过的项目和数字"}
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for env in ENVS:
        monkeypatch.setenv(env, "")
        monkeypatch.delenv(env)
    monkeypatch.setenv("CONTENT_STUDIO_X_GITHUB", "zinan92")
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))


def fake_capture(url: str, folder: Path) -> None:
    for v in portal.VIEWPORTS:
        (folder / f"{v}.png").write_bytes(PNG)


def test_judgement_needs_all_five_checks_and_keeps_their_order() -> None:
    out = portal.parse_judgement("好的：\n" + json.dumps(GOOD, ensure_ascii=False))
    assert [c["k"] for c in out["checks"]] == ["who", "what", "proof", "next", "alive"]
    assert [c["ok"] for c in out["checks"]] == [True, True, False, True, True]
    assert out["checks"][0]["label"] == "知道你是谁" and out["fix"].startswith("首屏")
    missing = {**GOOD, "checks": GOOD["checks"][:4]}
    with pytest.raises(portal.PortalError, match="少了一项"):
        portal.parse_judgement(json.dumps(missing))
    with pytest.raises(portal.PortalError):
        portal.parse_judgement("看不清")


def test_judge_asks_as_a_stranger_reading_only_the_two_shots(tmp_path: Path) -> None:
    seen = {}

    def run(argv, *, input, timeout, cwd):  # noqa: A002
        seen.update(argv=argv, prompt=input, cwd=cwd)
        return subprocess.CompletedProcess(argv, 0, json.dumps(GOOD, ensure_ascii=False), "")

    out = portal.judge_shots(tmp_path, "https://github.com/zinan92", "GitHub", run=run)
    assert out["verdict"] == GOOD["verdict"]
    assert "陌生人" in seen["prompt"] and str(tmp_path / "mobile.png") in seen["prompt"] and "不要猜" in seen["prompt"]
    assert "Read" in seen["argv"] and "WebFetch" not in seen["argv"][seen["argv"].index("--allowedTools") + 1]
    assert seen["cwd"] == str(tmp_path)


def test_once_a_day_and_again_when_the_link_changes() -> None:
    calls = []
    kw = {"capture": lambda u, f: (calls.append(u), fake_capture(u, f)), "judge": lambda f, u, l: GOOD, "background": False}
    assert portal.start("github", **kw) is True
    assert portal.start("github", **kw) is False  # 今天截过了
    assert portal.start("github", force=True, **kw) is True  # 他点了「重新截」
    import os
    os.environ["CONTENT_STUDIO_X_GITHUB"] = "someone-else"
    assert portal.start("github", **kw) is True  # 链接换了
    assert calls == ["https://github.com/zinan92"] * 2 + ["https://github.com/someone-else"]
    assert portal.start("site", **kw) is False  # 网站没填，不截


def test_a_failed_capture_is_shown_and_not_retried_automatically() -> None:
    def boom(url: str, folder: Path) -> None:
        raise portal.PortalError("打不开 https://github.com/zinan92：timeout")

    assert portal.start("github", capture=boom, judge=lambda f, u, l: GOOD, background=False) is True
    v = portal.view("github")
    assert v["shot"]["error"].startswith("打不开") and v["shot"]["judge"] is None
    assert portal.start("github", capture=boom, background=False) is False


def test_judge_failure_still_keeps_the_shots() -> None:
    def bad(folder: Path, url: str, label: str) -> dict:
        raise portal.PortalError("判断没回成 JSON")

    portal.run_once("github", capture=fake_capture, judge=bad)
    shot = portal.view("github")["shot"]
    assert shot["variants"] == ["desktop", "mobile"] and shot["judge_error"] == "判断没回成 JSON" and shot["error"] is None


def test_history_is_kept_for_thirty_days() -> None:
    for day in ("2026-08-01", "2026-09-20", "2026-10-06"):
        portal.run_once("github", capture=fake_capture, judge=lambda f, u, l: GOOD, today=day)
    assert portal.days("github") == ["2026-10-06", "2026-09-20"]
    assert portal.view("github", "2026-09-20")["shot"]["day"] == "2026-09-20"
    assert portal.view("github", "nonsense")["shot"]["day"] == "2026-10-06"


def test_api_serves_the_page_and_the_shots(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portal, "start", lambda key, **kw: False)  # 测试里不开浏览器
    portal.run_once("github", capture=fake_capture, judge=lambda f, u, l: GOOD, today="2026-10-06")
    d = client.get("/api/portal/github").json()
    assert d["label"] == "GitHub" and d["url"] == "https://github.com/zinan92" and d["shot"]["judge"]["fix"]
    img = client.get("/api/portal/github/shot/2026-10-06/mobile.png")
    assert img.status_code == 200 and img.content == PNG
    assert client.get("/api/portal/github/shot/2026-10-06/tablet.png").status_code == 404
    assert client.get("/api/portal/github/shot/..%2F..%2Fx/desktop.png").status_code == 404
    assert client.get("/api/portal/weibo").status_code == 404
    assert client.post("/api/portal/site/refresh").status_code == 400  # 网站没填


def test_rail_has_a_portal_group_and_positioning_no_longer_carries_links() -> None:
    static = STATIC_DIR
    html = (static / "index.html").read_text(encoding="utf-8")
    # 10/9 能收起的分组；10/12 作者：门户、产品收进一个「产品类」，默认收起；10/19 改名「产品」，汇总进「复盘」，单点功能进底下跳出去的那组
    fold = html[html.index('data-rail-fold="more"'):html.index('</nav>')]
    assert '<span>产品</span>' in fold and 'data-view="portal" data-key="github"' in fold
    assert 'data-view="portal" data-key="github"' in html and 'data-view="portal" data-key="site"' in html
    assert 'id="meLinks"' not in html and "renderMeLinks" not in (static / "positioning.js").read_text(encoding="utf-8")


def test_rail_is_find_write_cut_publish_review_then_the_rest_at_the_bottom() -> None:
    """10/20 作者：左栏用「找 写 剪 发 盘」五个字；平台不再各占一行；咨询客户、产品、素材这些沉到底下，和上面分开。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    nav = html[html.index('<nav class="rl"'):html.index('</nav>')]
    zx = [nav.index(f'data-zx="{k}"') for k in ("find", "write", "cut", "fa", "pan")]
    assert zx == sorted(zx)
    assert [nav[nav.index(f'data-zx="{k}"'):].split('class="zx-k">')[1][0] for k in ("find", "write", "cut", "fa", "pan")] == list("找写剪发盘")
    assert 'data-view="platform"' not in nav and 'data-view="board"' not in nav and 'data-view="swipe"' not in nav
    order = [nav.index(s) for s in ('data-zx="pan"', 'class="rail-spacer"', 'data-view="consults"', '<span>产品</span>', 'data-rail-out', 'data-open="/sucai"')]
    assert order == sorted(order) and 'data-view="summary"' not in nav
    tail = nav[nav.index('data-rail-out'):]
    assert all(f'data-open="{u}"' in tail for u in ("/sucai", "/tree", "/moments", "/tools"))
    assert nav[:nav.index('data-rail-out')].count("data-open=") == 0  # 新开标签的只在最底下那组


def test_rail_sucai_group_folds_like_products_and_both_start_folded() -> None:
    """10/19 作者：「素材 group 也要可以收起来，类似产品那个 group，而且这两个 default 都是收起来的」。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for key, label in (("more", "产品"), ("out", "素材")):
        head = html[html.index(f'data-rail-fold="{key}"'):]
        assert head.index('aria-expanded="false"') < head.index(">") and head.index(f"<span>{label}</span>") < head.index("</button>")
    body = html[html.index('data-rail-fold-body="out"'):html.index('</nav>')]
    assert all(f'data-open="{u}"' in body for u in ("/sucai", "/tree", "/moments", "/tools"))
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "const expanded = Boolean(open[key]);" in js  # 没存过开合 = 收起；存过的照他存的
