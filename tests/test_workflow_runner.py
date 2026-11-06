from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from content_studio.extras.motion import workflow_runner as wr


def _wait(run, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = wr.status(run)
        if state["state"] != "running":
            return state
        time.sleep(0.05)
    return wr.status(run)


def test_start_records_log_and_exit_code(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    started = wr.start(project, run_id=1, runs_dir=tmp_path / "runs", command="sh -c cat _")
    run = {"id": 1, "state": "running", **started}
    done = _wait(run)
    assert done["state"] == "done" and done["exit_code"] == 0
    assert "ask-park-video" in done["log_tail"] and str(project) in done["log_tail"]


def test_failure_and_cancel(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    failed = _wait({"id": 2, "state": "running", **wr.start(project, run_id=2, runs_dir=tmp_path, command="sh -c 'exit 1' _")})
    assert failed["state"] == "failed" and failed["exit_code"] == 1
    long = {"id": 3, "state": "running", **wr.start(project, run_id=3, runs_dir=tmp_path, command="sh -c 'sleep 30' _")}
    assert wr.status(long)["state"] == "running"
    wr.cancel(long)
    time.sleep(0.3)
    assert wr.status({**long, "state": "cancelled"})["state"] == "cancelled"


def test_approve_writes_contract_and_log(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text(json.dumps({"approvals": {"hook": None}}), encoding="utf-8")
    record = wr.approve(tmp_path, "H1", note="顺序照 worktable")
    data = json.loads((tmp_path / "project.json").read_text())
    assert data["approvals"]["hook"]["by"] == "作者" and record["via"] == "content-studio"
    assert "审批 H1" in (tmp_path / "process-log.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        wr.approve(tmp_path, "H9")


def test_gate_review_reads_artifacts(tmp_path: Path) -> None:
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "worktable.json").write_text(json.dumps({"hooks": [{"order": 1, "text": "第一句", "anchor_status": "ok"}]}), encoding="utf-8")
    assert wr.gate_review(tmp_path, "H1")["hooks"][0]["text"] == "第一句"
    (tmp_path / "part-b-body").mkdir()
    (tmp_path / "part-b-body" / "visual-plan.json").write_text(json.dumps({"coverage": 0.32, "shots": [{"id": "s1", "visual_type": "chart", "disposition": "采纳"}]}), encoding="utf-8")
    review = wr.gate_review(tmp_path, "H2")
    assert review["coverage"] == 0.32 and review["shots"][0]["disposition"] == "采纳"
