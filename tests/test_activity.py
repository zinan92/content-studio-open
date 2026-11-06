from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from content_studio import activity

NOW = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)


def _project(tmp_path: Path) -> Path:
    base = tmp_path / "2026-09-22_9月22日"
    (base / "part-b-body" / "remotion" / "node_modules" / "x").mkdir(parents=True)
    return base


def _touch(p: Path, at: datetime) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    os.utime(p, (at.timestamp(), at.timestamp()))


def _ps(*lines: str):
    return lambda: "\n".join(lines)


def test_whoever_is_running_shows_up_even_outside_the_workbench(tmp_path: Path) -> None:
    """9/22 作者 问了约 14 次「怎么样了」：Codex 在跑，工作台完全看不见。"""
    base = _project(tmp_path)
    _touch(base / "final" / "covers" / "subject-cutout.png", NOW - timedelta(minutes=2))
    ps = _ps(
        f"  101 05:17 /bin/zsh -c cat {base.parent}/park-koubo-workflow/scripts/release_guard.py",  # 不在项目里
        f"  102 00:12 /opt/homebrew/bin/ffmpeg -i {base}/final/x.mp4 -frames:v 1 out.png",
        f"  103 25:01 claude -p --model opus --add-dir {base}",
        f"  104 00:01 rg -n release.json {base}",
    )
    a = activity.activity(base, current=11, ps=ps, now=NOW)
    assert a["state"] == "working"
    assert [w["kind"] for w in a["workers"]] == ["ffmpeg", "claude", "命令行"]
    assert a["last_write"] == {"path": "final/covers/subject-cutout.png", "at": (NOW - timedelta(minutes=2)).isoformat(timespec="seconds"), "seconds_ago": 120}


def test_the_folder_name_never_decides_the_kind() -> None:
    """项目在 .../Codex/Workspaces/ 下；按整行找关键词，一个普通的 rg 也会被标成 codex。"""
    assert activity.classify("rg -n x /Users/me/Documents/Codex/Workspaces/video-lab-use/p") == "命令行"
    assert activity.classify("node /x/node_modules/@remotion/cli/remotion-cli.js render") == "remotion"
    assert activity.classify("/usr/local/bin/python3 -m mlx_whisper a.mp4") == "转写"


def test_node_modules_writes_do_not_count(tmp_path: Path) -> None:
    base = _project(tmp_path)
    _touch(base / "project.json", NOW - timedelta(minutes=40))
    _touch(base / "part-b-body" / "remotion" / "node_modules" / "x" / "cache.js", NOW)
    assert activity.latest_write(base)["path"] == "project.json"


def test_quiet_with_nobody_running_is_called_out(tmp_path: Path) -> None:
    base = _project(tmp_path)
    _touch(base / "project.json", NOW - timedelta(minutes=40))
    a = activity.activity(base, current=11, ps=_ps(), now=NOW)
    assert a["state"] == "stalled" and "40 分钟没有任何写入" in a["say"]


def test_a_gate_is_waiting_not_stalled(tmp_path: Path) -> None:
    """停在审批门不是卡住，是在等人。"""
    base = _project(tmp_path)
    _touch(base / "project.json", NOW - timedelta(hours=5))
    a = activity.activity(base, current=11, gate={"key": "H2"}, ps=_ps(), now=NOW)
    assert a["state"] == "waiting" and "H2" in a["say"]


def test_step_duration_comes_from_the_previous_step(tmp_path: Path) -> None:
    base = _project(tmp_path)
    contract = {"step_status": {
        "9": {"status": "pass", "at": "2026-09-23T15:04:50+08:00"},
        "10": {"status": "pass", "at": "2026-09-23T15:52:10+08:00"},
    }}
    a = activity.activity(base, contract=contract, current=11, ps=_ps(), now=NOW)
    assert a["step_minutes"] == 97  # 07:52:10Z → 09:30Z
    # 旧写法没有时间，算不了就不瞎报
    assert activity.step_started({"step_status": {"10": "pass"}}, 11) is None
