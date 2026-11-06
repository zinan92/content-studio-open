"""Run ask-park-video in the background until its next human gate, and record 作者's approvals.

The run is a detached process group (a service restart does not kill it). The shell
wrapper writes the exit code next to the log so the result survives restarts too.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from ...paths import config_dir
from ... import llm
import shlex
import signal
import subprocess
from typing import Any

RUNNER_COMMAND_ENV = "CONTENT_STUDIO_WORKFLOW_CMD"
DEFAULT_RUNNER_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "Skill Bash Read Write Edit Glob Grep" '
    '--disallowedTools "WebFetch WebSearch"'
)
DEFAULT_RUNS_DIR = config_dir() / "runs"
GATE_APPROVAL_KEYS = {"H1": "hook", "H2": "visual_spec", "H3": "final"}


def _visual_rule(project_path: Path) -> str:
    try:
        contract = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
        target, top = contract.get("visual_coverage_target"), contract.get("visual_coverage_max")
    except (OSError, ValueError, AttributeError):
        target = top = None
    if not isinstance(target, (int, float)):
        return ""
    lo = round(target * 100)
    hi = round(top * 100) if isinstance(top, (int, float)) and top > target else lo
    text = f"{lo}%" if hi == lo else f"{lo}–{hi}%"
    extra = "" if 30 <= lo and hi <= 40 else f"这个比例不在 30–40%，在 visual-plan.json 里写 coverage_exception：「作者 指定 {text}」。"
    how = "按这个数挑点" if hi == lo else "落在这个范围里就行，按内容需要挑点，不为凑数加镜头"
    return f"\n- 动效占正文的比例 作者 定为 {text}（按时长算）。{how}，不要自己改。{extra}"


SPEC_RULES = {
    ("hook", "no"): "这条不做 Hook（Step 5/7/8/9 已跳过），整条都是正文。",
    ("captions", "burned_in"): "字幕 作者 已经在剪映里加好了：不要再渲染字幕（Step 8/9/13），用 park-caption-burned-in-v1；但要实测字幕带，所有动效避开它。",
    ("layout", "vertical-full-overlay"): "版式是竖屏纯口播：用 park-talking-head-9x16-full-v1 和 park-vertical-director-v2，按 skill 的 references/motion-director.md 当导演，从 motion/ 镜头库逐段挑镜头；胸前卡片为主，隔 1.5–3 分钟全屏挡脸一次（全屏整屏盖满，连字幕一起盖）。什么时候叠动效、什么时候全屏挡脸或用 B-roll，都由你判断，作者 不单独选。H2 给他看 2–3 段成片样片，不给文字镜头表。",
    ("layout", "split-4x3"): "版式是横屏左原右屏（左边原画面、右边屏幕/笔记区）。",
    ("bgm", "none"): "不加背景音乐（Step 12 只做人声响度）。",
    ("bgm", "light"): "加一条轻背景音乐，压在人声下面。",
    ("sfx", "none"): "不加音效。",
    ("sfx", "low"): "音效低档：只在最关键的一两处（最重要的全屏镜头进场、最关键的数字落定）加，轻，压在人声下面。",
    ("sfx", "mid"): "音效中档：每个全屏镜头进出场、关键数字和结论落定处加，压在人声下面，不和人声抢。",
    ("sfx", "high"): "音效高档：全屏镜头进出场、数字滚动锁定、胸前卡片出现都配音效，节奏感强，但仍压在人声下面。",
}


def _spec_rules(project_path: Path) -> str:
    try:
        spec = json.loads((project_path / "project.json").read_text(encoding="utf-8")).get("spec") or {}
    except (OSError, ValueError, AttributeError):
        spec = {}
    lines = [SPEC_RULES[(k, v)] for k, v in spec.items() if (k, v) in SPEC_RULES]
    if not lines:
        return ""
    return "\n- 作者 手动选好的剪辑规格（照做，不要再判断或再问）：" + "".join(f"\n  - {line}" for line in lines)


def build_prompt(project_path: Path) -> str:
    return f"""用 ask-park-video skill 继续这个口播项目：{project_path}

规则：{_visual_rule(project_path)}{_spec_rules(project_path)}
- 按 skill 的 14 步和完成证据，从最早没完成的一步继续，连续执行，直到遇到人工审批门（H1 Hook、H2 视觉规格、H3 终审）、真实阻塞或全部完成就停下。
- 词级时间 subtitles/words.json 只用 mlx-whisper 出：有 subtitles/source.srt 就跑 skill 的
  `python3 scripts/motion/align_srt.py <粗剪> subtitles/source.srt subtitles/words.json`（拿 SRT 文字对齐音频，不重新识别，约 40 秒）；
  没有 SRT 才跑 `scripts/motion/words.py`。**不要用 openai-whisper 命令行（`whisper …`）**——Mac 上只能用 CPU，10 分钟口播要十几分钟。
- 写完 part-b-body/visual-plan.json 之后，**先跑算术检查再叫独立评审**：
  `python3 -m content_studio check-visual-plan <项目目录>`（在 ~/work/content-studio 下跑）。
  它查的是机器能判的：引用的卡片存不存在、镜头钉的那句话真实时间对不对得上
  （读 subtitles/words.json 的词级时间，不要用 start_hint 插值）、动画时长放不放得下、
  定量镜头有没有写「渲染后怎么验」。有 findings 就先改完再叫评审——
  评审只该看判断题（比如这个图会不会被人读成反义）。
- 这是后台运行，没有人能即时回答问题：需要 作者 决定的事情，把审查产物准备好、写进 process-log.md，然后停下，不要自己替 作者 批准。
- 不删除、不覆盖原始素材和剪映粗剪；所有新产物只写在这个项目目录里。
- 结束时用中文输出四行：当前 Step、当前审批门（没有写「无」）、这次完成了什么、下一步需要 作者 做什么。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start(project_path: Path, *, run_id: int, runs_dir: Path = DEFAULT_RUNS_DIR, command: str | None = None) -> dict[str, Any]:
    folder = runs_dir.expanduser() / f"run-{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    log_path, exit_path, prompt_path = folder / "log.txt", folder / "exit_code", folder / "prompt.txt"
    base = command or os.environ.get(RUNNER_COMMAND_ENV) or DEFAULT_RUNNER_COMMAND
    prompt_path.write_text(llm.prepare_prompt(base, build_prompt(project_path)), encoding="utf-8")
    script = f"{llm.shell_command(base, [str(project_path)])} < {shlex.quote(str(prompt_path))} > {shlex.quote(str(log_path))} 2>&1; echo $? > {shlex.quote(str(exit_path))}"
    process = subprocess.Popen(
        ["/bin/sh", "-c", script],
        cwd=str(project_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"pid": process.pid, "log_path": str(log_path), "exit_path": str(exit_path), "started_at": _now()}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)  # reap our own finished child
        return waited == 0
    except ChildProcessError:
        return True


def status(run: dict[str, Any], tail_lines: int = 40) -> dict[str, Any]:
    log_path = Path(run["log_path"])
    exit_path = Path(run["exit_path"])
    tail = ""
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-tail_lines:])
    exit_code = None
    if exit_path.is_file():
        try:
            exit_code = int(exit_path.read_text().strip() or "-1")
        except ValueError:
            exit_code = -1
    if run.get("state") == "cancelled":
        state = "cancelled"
    elif exit_code is not None:
        state = "done" if exit_code == 0 else "failed"
    elif _alive(run.get("pid")):
        state = "running"
    else:
        state = "failed"
    return {**run, "state": state, "exit_code": exit_code, "log_tail": tail}


def cancel(run: dict[str, Any]) -> None:
    pid = run.get("pid")
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def approve(project_path: Path, gate: str, *, note: str | None = None) -> dict[str, Any]:
    key = GATE_APPROVAL_KEYS.get(gate)
    if key is None:
        raise ValueError("审批门只能是 H1、H2、H3")
    contract_path = project_path / "project.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("项目没有可用的 project.json") from exc
    approvals = contract.setdefault("approvals", {})
    record = {"by": "作者", "at": _now(), "via": "content-studio"}
    if note:
        record["note"] = note[:500]
    approvals[key] = record
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (project_path / "process-log.md").open("a", encoding="utf-8") as log:
        log.write(f"\n## 审批 {gate}（{key}）\n\n- status: approved\n- by: 作者（内容工作台）\n- at: {record['at']}\n" + (f"- note: {note[:500]}\n" if note else ""))
    return record


def gate_review(project_path: Path, gate: str) -> dict[str, Any]:
    """What 作者 should look at before approving a gate."""
    def load(rel: str) -> Any:
        try:
            return json.loads((project_path / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    if gate == "H1":
        candidates = load("analysis/hook-candidates.json")
        worktable = load("analysis/worktable.json") or {}
        hooks = (candidates.get("hooks") if isinstance(candidates, dict) else candidates) or worktable.get("hooks") or []
        return {"gate": "H1", "hooks": [{"order": h.get("order"), "text": h.get("text") or h.get("quote"), "status": h.get("anchor_status") or h.get("status")} for h in hooks if isinstance(h, dict)][:8],
                "from": "analysis/hook-candidates.json" if candidates else "analysis/worktable.json"}
    if gate == "H2":
        plan = load("part-b-body/visual-plan.json") or {}
        shots = plan.get("shots") if isinstance(plan, dict) else plan
        return {"gate": "H2", "coverage": plan.get("coverage") if isinstance(plan, dict) else None,
                "shots": [{"id": s.get("id"), "start": s.get("start"), "end": s.get("end"), "visual_type": s.get("visual_type"), "purpose": s.get("purpose") or s.get("communication_purpose"),
                           "disposition": s.get("disposition")} for s in (shots or []) if isinstance(s, dict)][:40]}
    if gate == "H3":
        return {"gate": "H3", "qa": load("final/qa.json"), "video": "final/video.mp4"}
    raise ValueError("审批门只能是 H1、H2、H3")
