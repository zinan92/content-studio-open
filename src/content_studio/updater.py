"""「检查更新」：客户在设置页一点，从 GitHub 拉新版本，再安全重启。

作者 9/28：装机他到场，之后不每月见面，新功能靠客户自己点更新拉下来。规矩：

- **只更新工作台自己**（这个仓库）。deploy.json 里的其他依赖只报告装没装，不动。
  作者 这台电脑上的 content-ops、研习室都有正在做的改动，绝不能被拉。
- **只快进**：当前分支得是配置的更新分支（作者 默认 main；客户装机时填 stable），
  而且没有没提交的改动。否则一律跳过——那是开发机。
- 依赖（pyproject.toml）变了：只在装机脚本建的虚拟环境里装；作者 用的是全机共用的 python，
  不碰，只提示。
- 重启走 restart 脚本（有发布、写作、转写在跑就不重启），另起会话调用，
  免得 launchd 杀服务时把更新进程一起带走。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable

from . import conf

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "deploy.json"
VENV_MARKER = ".content-studio-managed"  # 装机脚本建的虚拟环境里放这个文件

Runner = Callable[[list[str]], tuple[int, str]]


class UpdateError(RuntimeError):
    """Shown to 作者 / the customer as-is."""


def _run(args: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout or done.stderr or "").strip()


def _git(run: Runner, *args: str) -> str:
    code, out = run(["git", *args])
    if code != 0:
        raise UpdateError(f"git {args[0]} 失败：{out[:200]}")
    return out


def deps() -> list[dict[str, Any]]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = []
    for d in data.get("deps") or []:
        path = Path(d.get("path") or "").expanduser()
        rows.append({"name": d.get("name"), "feature": d.get("feature"), "access": d.get("access"),
                     "required": bool(d.get("required")), "installed": bool(d.get("path")) and path.exists()})
    return rows


def status(*, run: Runner | None = None, fetch: bool = True) -> dict[str, Any]:
    run = run or _run
    want, remote = conf.value("update.branch"), conf.value("update.remote")
    branch = _git(run, "rev-parse", "--abbrev-ref", "HEAD")
    head_hash, head_date, head_subject = (_git(run, "log", "-1", "--format=%h%x1f%cI%x1f%s").split("\x1f") + ["", ""])[:3]
    dirty = bool(_git(run, "status", "--porcelain", "--untracked-files=no"))
    out: dict[str, Any] = {
        "branch": branch, "want": want, "head": {"hash": head_hash, "date": head_date, "subject": head_subject},
        "dirty": dirty, "behind": 0, "commits": [], "deps": deps(), "reason": None,
    }
    if branch != want:
        out["reason"] = f"这台是开发机：现在在 {branch} 分支，不是更新用的 {want}，不自动更新"
    elif dirty:
        out["reason"] = "本地有没提交的改动，不自动更新"
    if fetch:
        code, msg = run(["git", "fetch", "--quiet", remote, want])
        if code != 0:
            out["reason"] = out["reason"] or f"连不上 GitHub：{msg[:120]}"
            out["can_update"] = False
            return out
    code, behind = run(["git", "rev-list", "--count", f"HEAD..{remote}/{want}"])
    out["behind"] = int(behind) if code == 0 and behind.isdigit() else 0
    if out["behind"]:
        log = _git(run, "log", "--format=%h%x1f%cI%x1f%s", "-n", "20", f"HEAD..{remote}/{want}")
        out["commits"] = [dict(zip(("hash", "date", "subject"), line.split("\x1f"))) for line in log.splitlines() if line]
    out["can_update"] = out["reason"] is None and out["behind"] > 0
    return out


def _pyproject_hash() -> str:
    try:
        return hashlib.sha256((REPO / "pyproject.toml").read_bytes()).hexdigest()
    except OSError:
        return ""


def managed_venv() -> Path | None:
    venv = REPO / ".venv"
    return venv if (venv / VENV_MARKER).is_file() and (venv / "bin" / "pip").is_file() else None


def restart_later(delay: float = 1.5) -> None:
    """响应先回给页面，再另起会话调重启脚本；脚本自己会看有没有活在跑。"""
    cmd = str(Path(conf.value("service.restart")).expanduser())

    def go() -> None:
        try:
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    threading.Timer(delay, go).start()


def apply(*, run: Runner | None = None, restart: Callable[[], None] | None = None) -> dict[str, Any]:
    run = run or _run
    st = status(run=run, fetch=True)
    if st["reason"]:
        raise UpdateError(st["reason"])
    if not st["behind"]:
        return {"updated": False, "message": "已经是最新版"}
    before = _pyproject_hash()
    _git(run, "merge", "--ff-only", f"{conf.value('update.remote')}/{st['want']}")
    notes = []
    if _pyproject_hash() != before:
        venv = managed_venv()
        if venv:
            code, msg = run([str(venv / "bin" / "pip"), "install", "--quiet", "-e", str(REPO)])
            if code != 0:
                raise UpdateError(f"新版本需要的依赖没装上：{msg[:200]}")
            notes.append("装好了新依赖")
        else:
            notes.append("新版本的依赖有变化，这台电脑的 Python 不是装机脚本建的，没有自动装")
    if os.environ.get("CONTENT_STUDIO_NO_RESTART"):
        notes.append("没有重启（测试）")
    else:
        (restart or restart_later)()
        notes.append("正在重启，稍等十几秒刷新页面；有发布或写作在跑会等它们结束再重启")
    return {"updated": True, "count": st["behind"], "commits": st["commits"], "message": "；".join(notes)}
