"""一个口播项目此刻的动静：谁在干活、最后写了什么、这一步做了多久。

9/22 那条视频前后 作者 问了大约 14 次「怎么样了」。工作台只看得到它自己启动的任务；
在 Codex 或 Claude App 里跑的，它完全看不见。这里不管是谁在跑，只看项目目录本身：
project.json 说到了哪一步，文件系统说最后动了什么，进程表说谁的命令行里带着这个目录。
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

STALL_SECONDS = 15 * 60
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".cache", ".remotion", ".DS_Store"}
# 命令行里出现这些词就归为这一类。顺序即优先级：一个 claude 调起的 ffmpeg 归 ffmpeg。
KINDS = (("ffmpeg", "ffmpeg"), ("remotion", "remotion"), ("whisper", "转写"), ("claude", "claude"),
         ("codex", "codex"), ("node", "node"), ("python", "python"))

PsFn = Callable[[], str]


def _ps() -> str:
    # 必须带 UTF-8 locale：默认 locale 下 ps 会把中文路径转义成 `9M-fM^\M^H…`，
    # 「2026-09-22_9月22日」这种项目名就永远匹配不上。
    env = {**os.environ, "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
    try:
        return subprocess.run(["ps", "-axww", "-o", "pid=,etime=,args="], capture_output=True, text=True, env=env, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def classify(args: str) -> str:
    """按命令本身归类，不看目录。

    路径只取文件名：项目放在 .../Codex/Workspaces/... 下，按整行找关键词的话，
    一个普通的 `rg` 也会被标成 codex。
    """
    words = [w.rsplit("/", 1)[-1].lower() for w in args.replace("\\012", " ").split()]
    return next((label for key, label in KINDS if any(key in w for w in words)), "命令行")


def workers(base: Path, *, ps: PsFn = _ps) -> list[dict[str, Any]]:
    """命令行里带着这个项目目录的进程。"""
    needle = str(base)
    me = os.getpid()
    out = []
    for line in ps().splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3 or needle not in parts[2]:
            continue
        pid, etime, args = int(parts[0]), parts[1], parts[2]
        if pid == me or args.startswith("ps "):
            continue
        kind = classify(args)
        out.append({"pid": pid, "kind": kind, "elapsed": etime, "command": args[:160]})
    return out


def latest_write(base: Path) -> dict[str, Any] | None:
    best: tuple[float, Path] | None = None
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            p = Path(root) / name
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if best is None or m > best[0]:
                best = (m, p)
    if best is None:
        return None
    return {"path": str(best[1].relative_to(base)), "at": datetime.fromtimestamp(best[0], timezone.utc).isoformat(timespec="seconds")}


def _at(entry: Any) -> datetime | None:
    raw = entry.get("at") if isinstance(entry, dict) else None
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def step_started(contract: dict[str, Any], current: int | None) -> datetime | None:
    """当前这一步从什么时候开始算：上一步完成的时间。旧写法（纯字符串）没有时间，就算不了。"""
    if not current:
        return None
    status = contract.get("step_status") or {}
    for n in range(current - 1, 0, -1):
        found = _at(status.get(str(n)) or status.get(n))
        if found:
            return found
    return None


def activity(base: Path, *, contract: dict[str, Any] | None = None, current: int | None = None,
             gate: dict[str, Any] | None = None, delivered: bool = False,
             ps: PsFn = _ps, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    running = workers(base, ps=ps)
    last = latest_write(base)
    quiet = None
    if last:
        quiet = int((now - datetime.fromisoformat(last["at"])).total_seconds())
    started = step_started(contract or {}, current)
    if delivered:
        state, say = "done", "已交付"
    elif running:
        state, say = "working", "、".join(sorted({w["kind"] for w in running})) + " 正在这个项目里干活"
    elif gate:
        # 停在审批门不是卡住，是在等人。
        state, say = "waiting", f"停在 {gate.get('key', '')}，等你拍板"
    elif quiet is not None and quiet >= STALL_SECONDS:
        state, say = "stalled", f"没有进程在跑，{quiet // 60} 分钟没有任何写入——可能卡住了，或者没人接着跑"
    elif quiet is not None:
        state, say = "idle", f"{max(quiet, 0) // 60} 分钟前还有写入，现在没有进程"
    else:
        state, say = "empty", "项目目录里还没有文件"
    return {
        "state": state,
        "say": say,
        "step": current,
        "step_minutes": int((now - started).total_seconds() // 60) if started else None,
        "last_write": {**last, "seconds_ago": quiet} if last else None,
        "workers": running,
    }
