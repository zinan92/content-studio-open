"""对外的单点功能（10/10）：邀请码、额度、沙盒、只看得到自己的。Codex 一律换成假的。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.tools import codes, public, tools


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: "## 主线\n说清楚了")
    monkeypatch.setattr(tools.Queue, "start", lambda self: None)
    store = codes.CodeStore(tmp_path / "codes.json")
    queue = public.PublicQueue(store, tmp_path / "runs")
    app = public.create_app(store, queue, origins=("https://example.com",))
    return store, queue, TestClient(app)


def H(code: str) -> dict[str, str]:
    return {"x-access-code": code}


def test_codes_are_stored_hashed_and_charged_and_refunded(tmp_path: Path) -> None:
    store = codes.CodeStore(tmp_path / "c.json")
    code = store.issue("张三", 500)
    assert code.startswith("CS-") and code not in (tmp_path / "c.json").read_text(encoding="utf-8")
    h, entry = store.lookup(code.lower().replace("-", " "))  # 抄的时候大小写、横线不用对
    assert entry["balance"] == 500
    assert store.charge(h, 120) and store.get(h)["balance"] == 380
    assert not store.charge(h, 400)
    store.refund(h, 120)
    assert store.get(h)["balance"] == 500
    store.set_disabled(h[:8], True)
    assert store.lookup(code) is None
    with pytest.raises(codes.CodeError):
        store.issue("  ", 100)


def test_no_code_or_a_wrong_code_gets_nothing(env) -> None:
    _, _, client = env
    assert client.get("/api/tools").status_code == 401
    assert client.get("/api/tools", headers=H("CS-AAAA-BBBB")).status_code == 401
    assert client.post("/api/tools/review/run", json={"text": "x"}).status_code == 401
    assert client.get("/health").json()["ok"] is True


def test_a_run_costs_its_price_and_a_failed_one_is_refunded(env, monkeypatch: pytest.MonkeyPatch) -> None:
    store, queue, client = env
    code = store.issue("朋友", 500)
    got = client.get("/api/tools", headers=H(code)).json()
    assert got["balance"] == 500 and len(got["tools"]) == 10 and got["tools"][0]["price"] > 0
    run = client.post("/api/tools/review/run", json={"text": "一篇文章"}, headers=H(code)).json()
    assert run["balance"] == 500 - tools.PRICE["review"] and "owner" not in run and run["token"]
    queue.drain()
    assert queue.read(run["id"])["state"] == "done"
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: (_ for _ in ()).throw(tools.ToolError("Codex 没回话")))
    bad = client.post("/api/tools/humanize/run", json={"text": "原文"}, headers=H(code)).json()
    queue.drain()
    assert queue.read(bad["id"])["state"] == "failed"
    h, _ = store.lookup(code)
    assert store.get(h)["balance"] == 500 - tools.PRICE["review"]  # 失败那次退回


def test_not_enough_balance_and_bad_input_do_not_charge(env) -> None:
    store, _, client = env
    code = store.issue("朋友", 30)
    r = client.post("/api/tools/cover/run", json={"title": "一个标题"}, headers=H(code))
    assert r.status_code == 402 and "余额不够" in r.json()["detail"]
    assert client.post("/api/tools/review/run", json={"text": ""}, headers=H(code)).status_code == 400
    assert client.post("/api/tools/review/run", json={"text": "字" * 9000}, headers=H(code)).status_code == 400
    h, _ = store.lookup(code)
    assert store.get(h)["balance"] == 30


def test_one_code_cannot_pile_up_runs_and_cannot_see_anothers(env) -> None:
    store, queue, client = env
    a, b = store.issue("甲", 500), store.issue("乙", 500)
    ids = [client.post("/api/tools/humanize/run", json={"text": f"原文{i}"}, headers=H(a)).json()["id"] for i in range(2)]
    assert client.post("/api/tools/humanize/run", json={"text": "第三个"}, headers=H(a)).status_code == 429
    assert client.get(f"/api/tools/runs/{ids[0]}", headers=H(a)).status_code == 200
    assert client.get(f"/api/tools/runs/{ids[0]}", headers=H(b)).status_code == 404
    assert client.get("/api/tools", headers=H(b)).json()["runs"] == []


def test_images_need_the_runs_own_token_and_the_kill_switch_closes_everything(env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, queue, client = env
    code = store.issue("朋友", 500)

    def fake_paint(prompt: str, cwd: Path):
        from PIL import Image

        shots = cwd / "shots"
        shots.mkdir(exist_ok=True)
        Image.new("RGB", (900, 1200), "white").save(shots / "01.png")
        return [shots / "01.png"], "好了"

    monkeypatch.setitem(tools.PAINT, "fn", fake_paint)
    monkeypatch.setitem(tools.PUBLIC, "on", True)
    run = client.post("/api/tools/style/run", json={"topic": "猫", "style": "手绘草图"}, headers=H(code)).json()
    queue.drain()
    done = client.get(f"/api/tools/runs/{run['id']}", headers=H(code)).json()
    assert done["state"] == "done" and done["result"]["images"] == ["out/image.png"]
    url = f"/api/tools/runs/{run['id']}/file/out/image.png"
    assert client.get(url).status_code == 404
    assert client.get(url + "?t=wrong").status_code == 404
    assert client.get(url + f"?t={run['token']}").status_code == 200
    off = tmp_path / "off"
    off.write_text("x")
    app = public.create_app(store, queue, origins=("https://example.com",), killed=off.exists)
    c2 = TestClient(app)
    assert c2.get("/api/tools", headers=H(code)).status_code == 503
    assert c2.get(url + f"?t={run['token']}").status_code == 503


def test_only_the_site_may_call_it_from_a_browser(env) -> None:
    _, _, client = env
    ok = client.options("/api/tools", headers={"origin": "https://example.com", "access-control-request-method": "GET",
                                              "access-control-request-headers": "x-access-code"})
    assert ok.headers.get("access-control-allow-origin") == "https://example.com"
    no = client.options("/api/tools", headers={"origin": "https://evil.example", "access-control-request-method": "GET"})
    assert "access-control-allow-origin" not in no.headers


def test_sandbox_blocks_home_and_volumes_but_not_the_job_or_codex_home(tmp_path: Path) -> None:
    home = tmp_path / "me"
    job = home / "jobs/1"
    profile = public.sandbox_profile(job, home)
    assert f'(deny file-read* (subpath "{home}") (subpath "/Volumes")' in profile
    assert f'(subpath "{home}/.codex")' in profile and f'(subpath "{job.resolve()}")' in profile
    assert f'(deny file-write* (subpath "{home}"))' in profile
    job.mkdir(parents=True)
    argv = public.sandboxed(["codex", "exec"], job)
    assert argv[:2] == ["/usr/bin/sandbox-exec", "-f"] and argv[-2:] == ["codex", "exec"]


def test_paint_takes_the_images_from_the_codex_session_in_order_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "h"
    gen = home / ".codex/generated_images/thread-1"
    gen.mkdir(parents=True)
    (gen / "a.png").write_bytes(b"1")
    (gen / "b.png").write_bytes(b"22")
    import os

    os.utime(gen / "a.png", (1, 1))
    os.utime(gen / "b.png", (2, 2))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    job = tmp_path / "job"
    job.mkdir()
    public.CURRENT["dir"] = job

    def fake_run(cmd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_text('[{"after":"x","caption":"y"}]', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"type": "thread.started", "thread_id": "thread-1"}) + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    shots, answer = public.sandboxed_paint("画", job)
    public.CURRENT["dir"] = None
    assert [p.name for p in shots] == ["01.png", "02.png"] and shots[1].read_bytes() == b"22"
    assert json.loads(answer)[0]["caption"] == "y" and not gen.exists()


def test_a_restart_refunds_the_run_that_was_cut_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(tools.Queue, "start", lambda self: None)
    store = codes.CodeStore(tmp_path / "c.json")
    queue = public.PublicQueue(store, tmp_path / "runs")
    code = store.issue("朋友", 500)
    h, _ = store.lookup(code)
    assert store.charge(h, 120)
    run = queue.submit("humanize", {"text": "原文"}, extra={"owner": h, "price": 120, "token": "t"})
    queue._write({**run, "state": "running"})
    queue.recover()
    assert queue.read(run["id"])["state"] == "failed" and store.get(h)["balance"] == 500


def test_public_mode_images_use_image_gen_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = []

    def fake_paint(prompt: str, cwd: Path):
        seen.append(prompt)
        from PIL import Image

        (cwd / "shots").mkdir(exist_ok=True)
        for i in (1, 2):
            Image.new("RGB", (1600, 900), "white").save(cwd / "shots" / f"{i:02d}.png")
        if "JSON 数组" in prompt:
            return [cwd / "shots/01.png", cwd / "shots/02.png"], '好了 [{"after":"第一段讲的是开头","caption":"开头"},{"after":"第二段讲的是复利","caption":"复利"}]'
        return [cwd / "shots/02.png"], "好了"

    monkeypatch.setitem(tools.PAINT, "fn", fake_paint)
    monkeypatch.setitem(tools.PUBLIC, "on", True)
    monkeypatch.setitem(tools.IMAGE, "fn", lambda p, c: (_ for _ in ()).throw(AssertionError("对外的任务不能走本机的 draw")))
    run = tmp_path / "run"
    run.mkdir()
    out = tools.illustrate({"text": "第一段讲的是开头。\n\n第二段讲的是复利怎么滚。"}, run)
    assert out["markdown"].count("![") == 2 and "不要运行任何命令" in seen[0]
    assert tools.cover.__name__ == "cover"
