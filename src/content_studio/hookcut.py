"""切 Hook（10/19 作者；10/21 起切片本身在 park-video-v2 里：`pv2.py hook`）。

这里只做工作台这头：读他在表里标了哪几个 Hook（没标就当场说），把 iCloud 上的粗剪先下到本机，
再交给 pv2.py 去切 h1…hN，进度一行一行读回来给页面。切法（词级对齐、切在停顿上、再听首尾字）
和产物（part-a-hook/individual/、edit.json、qa.json）都没变，见 park-video-v2 的 scripts/hookcut.py。
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from . import koubo

TIMEOUT = 1800


class HookCutError(RuntimeError):
    """说给 作者 看的一句话。"""


def picked(base: Path) -> list[dict[str, Any]]:
    """表里标好的 Hook（analysis/worktable.json）。没有就当场说，不进后台。"""
    try:
        data = json.loads((base / "analysis" / "worktable.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HookCutError("还没有标好的 Hook：先在表里标好，点「保存到项目」") from None
    hooks = [h for h in data.get("hooks") or [] if str(h.get("text") or "").strip()]
    if not hooks:
        raise HookCutError("表里没有标 Hook")
    return sorted(hooks, key=lambda h: (h.get("order") or h.get("slot") or 0))


def run(base: Path, *, captions_burned_in: bool = True, progress: Callable[[str], None] = lambda _s: None) -> dict[str, Any]:
    """交给 pv2.py hook 切 h1…hN。返回 qa（clips、flags，给页面看要注意的地方）。"""
    from . import icloud
    from .extras.motion import video_v2

    picked(base)
    video = koubo.find_video(base)
    if video is None:
        raise HookCutError("项目里没有粗剪")
    try:
        icloud.ensure_local(video)
    except icloud.NotLocalError as exc:
        raise HookCutError(str(exc)) from None
    script = video_v2.home() / "scripts" / "pv2.py"
    if not script.is_file():
        raise HookCutError(f"找不到 park-video-v2：{script}")
    args = [sys.executable, str(script), "hook", str(base)] + ([] if captions_burned_in else ["--no-burned-captions"])
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(video_v2.home()))
    errors: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        line = line.rstrip("\n")
        if line.startswith("STAGE "):
            progress(line[6:])
        elif line.startswith("ERROR "):
            errors.append(line[6:])
        elif line.strip():
            errors.append(line.strip())
    out = proc.stdout.read() if proc.stdout else ""
    try:
        code = proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise HookCutError("切 Hook 超时了") from None
    if code != 0:
        raise HookCutError(errors[-1] if errors else "切 Hook 失败")
    try:
        return json.loads(out)
    except ValueError:
        raise HookCutError("切 Hook 的结果读不懂") from None
