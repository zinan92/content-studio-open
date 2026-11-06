"""试用版开关（#526）：profile.yaml 一行 edition: trial，砍掉的入口和接口都没有；不写就是完整版。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import edition, web
from tests.test_web import client  # noqa: F401


@pytest.mark.parametrize("profile", [None, {}, {"edition": ""}, {"edition": "full"}, {"edition": "试用"}, {"edition": 3}])
def test_missing_or_unknown_edition_is_full(profile) -> None:
    """作者 那台的 profile 没这一项：合并后自动部署也不能少任何东西。"""
    assert edition.name(profile) == "full"
    assert edition.off(profile) == frozenset()
    assert edition.platforms_off(profile) == ()
    assert edition.blocked("/api/portal/github", profile) is None


def test_trial_blocks_cut_routes_only() -> None:
    p = {"edition": "Trial"}
    assert edition.name(p) == "trial"
    cut = {
        "/api/portal/github": "portal", "/api/products": "products", "/api/consults": "consults", "/api/clients/x": "consults",
        "/api/anna": "team", "/api/wendy/brief": "team", "/api/positioning": "positioning", "/api/persona": "positioning",
        "/api/platform/others": "others", "/api/vault/dailies": "dailies", "/api/kline/board": "dailies",
        "/api/series": "series", "/api/video-v2/settings": "motion", "/api/topics/3/video-project/v2/init": "motion",
        "/api/topics/3/proof/pick": "proof", "/api/topics/3/evidence": "proof", "/api/evidence/queue": "proof",
        "/api/topics/3/platform/x/send": "autopost", "/api/topics/3/publish-jobs": "autopost", "/api/publish-jobs/9/confirm": "autopost",
        "/api/xline/daily": "xline", "/api/xline": "xline",
    }
    for path, key in cut.items():
        assert edition.blocked(path, p) == key, path
    kept = ["/api/state", "/api/platform/x", "/api/platform/douyin", "/api/topics/3/platform/x/sent", "/api/topics/3/video-project",
            "/api/backfill/desk", "/api/backfill/desk/go", "/api/topics/3/video-project/external", "/api/reports", "/api/followed/posts", "/api/schedule", "/api/today/home", "/static/app.js"]
    for path in kept:
        assert edition.blocked(path, p) is None, path


@pytest.fixture
def trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    app = web.create_app(store_path=tmp_path / "studio.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "data",
                         downloads_dir=tmp_path / "downloads", start_worker=False, drafts_dir=tmp_path / "drafts",
                         profile={"edition": "trial"})
    with TestClient(app) as c:
        c.headers["X-Content-Studio"] = "1"
        yield c


def test_trial_state_and_routes(trial: TestClient) -> None:
    st = trial.get("/api/state").json()
    assert st["edition"]["name"] == "trial"
    assert set(st["edition"]["off"]) == set(edition.EDITIONS["trial"])
    assert not {"qa", "coupon", "figs"} & set(st["edition"]["off"])  # 流水线里的一步只给用户开关，试用版不砍
    assert st["edition"]["platforms_off"] == ["bilibili", "youtube", "wechat_mp"]
    assert st["daily_sources"] == []  # 作者 的 AI 日报不出现
    r = trial.get("/api/portal/github")
    assert r.status_code == 404 and "门户" in r.json()["error"]
    assert trial.post("/api/topics/1/platform/x/send", json={"form": "text"}).status_code == 404
    assert trial.get("/api/platform/x").status_code == 200


def test_trial_has_no_machine_posting_and_hides_the_other_three(trial: TestClient) -> None:
    for key in ("bilibili", "youtube", "wechat_mp", "x"):
        trial.put(f"/api/platform/{key}/settings", json={"on": True})
    page = trial.get("/api/platform/x").json()
    assert page["how"][0] == "hand"
    on = {p["key"]: p["on"] for p in trial.get("/api/platforms").json()["platforms"]}
    assert on["x"] and not on["bilibili"] and not on["youtube"] and not on["wechat_mp"]


def test_full_edition_unchanged(client: TestClient) -> None:  # noqa: F811
    st = client.get("/api/state").json()
    ed = st["edition"]
    assert (ed["name"], ed["off"], ed["cut"], ed["user_off"], ed["platforms_off"]) == ("full", [], [], [], [])
    assert client.get("/api/platform/others").status_code == 200
    assert client.get("/api/platform/x").json()["how"][0] == "auto"


def test_trial_backfill_desk_only_prepares_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """补发工作台在试用版里照样能点「开始」，但 X 这种本来机器发的格子也只备上传文件夹，不去发。"""
    import sys
    import time

    from content_studio import approvals, channel_probe
    from content_studio.extras.consults import consult
    from tests.test_web import SEC, FakeClient, _wait_sync

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    monkeypatch.setenv("CONTENT_STUDIO_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setenv("CONTENT_STUDIO_NO_OPEN", "1")
    monkeypatch.setattr(channel_probe, "CACHE_PATH", tmp_path / "probes.json")
    monkeypatch.setattr(approvals, "status", lambda folder, fps: {k: {"approved": True, "valid": True, "made": True, "by": "park"}
                                                                   for k in ("copy", "cover", "article", "figs", "wx", "xhs")})
    sent = tmp_path / "sent.txt"
    cred = tmp_path / "secrets.yaml"
    cred.write_text("{}")
    upload = [sys.executable, "-c", f"import json, pathlib; pathlib.Path({str(sent)!r}).write_text('x'); print(json.dumps({{'ok': True, 'url': 'https://x.com/i/1'}}))", "{article}"]
    specs = {"x": {"label": "X", "copy_key": "x", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                   "modes": {"article_publish": {"label": "发", "argv": upload}}}}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    app = web.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                         downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                         publishers=specs, profile={"edition": "trial"})
    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        c.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
        _wait_sync(c)
        vid = c.get("/api/backfill").json()["videos"][0]["video_id"]
        c.post(f"/api/backfill/{vid}/take")
        assert c.post("/api/backfill/desk/go", json={"cells": [{"video_id": vid, "platform": "x"}]}).json() == {"started": 1}
        for _ in range(200):
            run = c.get("/api/backfill/desk").json()["run"]
            if not run["running"]:
                break
            time.sleep(0.05)
        item = run["items"][0]
        assert item["how"] == "hand" and item["state"] != "done" and not sent.exists()
    app.state.store.close()
