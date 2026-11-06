"""切 Hook（10/19 作者；10/21 起切片在 park-video-v2 的 pv2.py hook 里，切法的测试也搬过去了）。
这里测工作台这头：没标 Hook 当场说、交给 pv2 切、进度读回来、剪 Hook + 加动效也走这条。pv2 是假的。"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time

import pytest

from content_studio import hookcut
from test_web import client  # noqa: F401  (fixture)


def project(root: Path, hooks: list[tuple[str, float, float]]) -> Path:
    base = root / "2026-10-19_切钩子"
    (base / "analysis").mkdir(parents=True)
    (base / "subtitles").mkdir()
    (base / "粗剪-10月19日.mov").write_bytes(b"rough cut")
    (base / "subtitles" / "source.srt").write_text("1\n00:00:00,000 --> 00:00:02,400\n我每个月花四百\n", encoding="utf-8")
    table = {"schema": "park-video-worktable/v1", "hooks": [
        {"slot": n, "order": n, "text": text, "anchor": {"start_hint": a, "end_hint": b}} for n, (text, a, b) in enumerate(hooks, 1)]}
    (base / "analysis" / "worktable.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return base


@pytest.fixture()
def fake_pv2(tmp_path: Path, monkeypatch) -> Path:
    """假 park-video-v2：pv2.py hook 打两行进度，切出 h1.mp4，写 qa.json，stdout 吐 qa。有 FAIL 文件就报错。"""
    home = tmp_path / "pv2home"
    (home / "scripts").mkdir(parents=True)
    log = tmp_path / "pv2.log"
    (home / "scripts" / "pv2.py").write_text(f"""import json, sys
from pathlib import Path
args = sys.argv[1:]
open({str(log)!r}, "a").write(json.dumps(args) + "\\n")
base = Path(args[1])
if Path({str(tmp_path / "FAIL")!r}).exists():
    print("ERROR h2「花四百」在逐字稿里找不到：回表里重新标一下", file=sys.stderr)
    sys.exit(2)
print("STAGE 对词级时间", file=sys.stderr, flush=True)
print("STAGE 切 h1", file=sys.stderr, flush=True)
out = base / "part-a-hook" / "individual"
out.mkdir(parents=True, exist_ok=True)
(out / "h1.mp4").write_text("clip")
qa = {{"at": "2026-10-21T00:00:00+00:00", "flags": [{{"id": "h1", "notes": ["听一下"]}}]}}
(base / "part-a-hook" / "qa.json").write_text(json.dumps(qa, ensure_ascii=False))
print(json.dumps({{**qa, "clips": [{{"id": "h1"}}]}}, ensure_ascii=False))
""", encoding="utf-8")
    monkeypatch.setenv("CONTENT_STUDIO_PV2_HOME", str(home))
    return log


def test_without_marked_hooks_it_says_so_before_starting(tmp_path: Path) -> None:
    base = project(tmp_path, [])
    with pytest.raises(hookcut.HookCutError, match="表里没有标 Hook"):
        hookcut.picked(base)
    (base / "analysis" / "worktable.json").unlink()
    with pytest.raises(hookcut.HookCutError, match="还没有标好的 Hook"):
        hookcut.run(base)


def test_run_hands_off_to_pv2_and_reads_progress_back(tmp_path: Path, fake_pv2: Path) -> None:
    base = project(tmp_path, [("我每个月花四百", 1.4, 4.0)])
    seen: list[str] = []
    qa = hookcut.run(base, captions_burned_in=False, progress=seen.append)
    assert seen == ["对词级时间", "切 h1"] and qa["clips"][0]["id"] == "h1"
    assert json.loads(fake_pv2.read_text().splitlines()[0]) == ["hook", str(base), "--no-burned-captions"]
    (tmp_path / "FAIL").write_text("1")
    with pytest.raises(hookcut.HookCutError, match="h2「花四百」在逐字稿里找不到"):
        hookcut.run(base)


# -- 页面上的按钮 --------------------------------------------------------------------------------------

def hook_topic(client, tmp_path: Path, hooks, *, motion: bool = False) -> tuple[int, Path]:  # noqa: F811
    root = tmp_path / "projects"
    root.mkdir()
    client.put("/api/settings", json={"video_projects_root": str(root)})
    tid = client.post("/api/topics", json={"title": "切钩子", "formats": "video"}).json()["id"]
    base = project(root, hooks)
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    assert client.post(f"/api/topics/{tid}/video-project/plan/start", json={"hook": True, "motion": motion}).status_code == 200
    return tid, base


def wait_idle(client, tid: int) -> dict:  # noqa: F811
    for _ in range(300):
        state = client.get(f"/api/topics/{tid}/video-project/hook-clips").json()
        if not state["running"]:
            return state
        time.sleep(0.02)
    raise AssertionError("还在切")


def test_the_button_cuts_in_the_background_and_the_clips_block_turns_done(client, tmp_path: Path, fake_pv2: Path) -> None:  # noqa: F811
    tid, base = hook_topic(client, tmp_path, [("我每个月花四百", 1.4, 4.0)])
    before = {b["key"]: b["state"] for b in client.get(f"/api/topics/{tid}/video-project/plan").json()["blocks"]}
    assert before["pick"] == "done" and before["clips"] == "current"
    assert client.post(f"/api/topics/{tid}/video-project/hook-clips").status_code == 200
    state = wait_idle(client, tid)
    assert state["error"] is None and state["flags"][0]["id"] == "h1"
    after = {b["key"]: b["state"] for b in client.get(f"/api/topics/{tid}/video-project/plan").json()["blocks"]}
    assert after["clips"] == "done" and after["final"] == "current"


def test_hook_plus_motion_cuts_hooks_first_then_motion(client, tmp_path: Path, fake_pv2: Path) -> None:  # noqa: F811
    """10/21：剪 Hook + 加动效不再跑 ask-park-video 14 步：先标表、切片，剪映里拼好，再做动效。"""
    tid, base = hook_topic(client, tmp_path, [("我每个月花四百", 1.4, 4.0)], motion=True)
    assert not (base / "project.json").exists()
    blocks = [b["key"] for b in client.get(f"/api/topics/{tid}/video-project/plan").json()["blocks"]]
    assert blocks == ["words", "pick", "clips", "motion", "final"]
    assert client.post(f"/api/topics/{tid}/video-project/hook-clips").status_code == 200
    assert wait_idle(client, tid)["error"] is None


def test_the_button_refuses_without_marked_hooks_and_while_already_cutting(client, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    tid, base = hook_topic(client, tmp_path, [("我每个月花四百", 1.4, 4.0)])
    gate = threading.Event()
    monkeypatch.setattr(hookcut, "run", lambda *_a, **_kw: gate.wait(5) and {"clips": [], "flags": []})
    assert client.post(f"/api/topics/{tid}/video-project/hook-clips").status_code == 200
    assert client.post(f"/api/topics/{tid}/video-project/hook-clips").status_code == 409
    gate.set()
    (base / "analysis" / "worktable.json").write_text(json.dumps({"hooks": []}), encoding="utf-8")
    wait_idle(client, tid)
    r = client.post(f"/api/topics/{tid}/video-project/hook-clips")
    assert r.status_code == 400 and "没有标 Hook" in r.text
