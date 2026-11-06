"""这次怎么剪（10/19 作者）：视频放进来以后，他自己勾这一条走哪几块。

流程没有固定下来：有时要剪 Hook、有时不要；有时加动效、有时不加。所以不让机器猜，
也不再把选择散在四个地方（Hook 下拉、「这条不剪 Hook」、「做动效 / 不加动效」、版式），
一张卡、两个开关，后面的进度只列勾上的块。

两个开关落到哪个后台（后台本身不动）：

| Hook | 动效 | 走哪条                                                        |
|------|------|---------------------------------------------------------------|
| 不剪 | 不加 | 粗剪就是成片（koubo.mark_external all）                        |
| 不剪 | 加   | park-video-v2（video_v2.init）                                 |
| 剪   | 加   | 先和「只剪 Hook」一样标表、切片，剪映里拼好放回来，再走 park-video-v2（10/21 起不再跑 ask-park-video 14 步） |
| 剪   | 不加 | 只剪 Hook：工作台标 Hook → 页面上点「切 Hook」（pv2.py hook）→ 剪映里拼 |

选择存在项目目录的 cut-plan.json；上一次选的存进设置，下一条默认照它。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLAN_FILE = "cut-plan.json"

# 只有「剪 Hook + 加动效」走 14 步时，字幕 / 版式 / 背景音乐才由机器做；其余路线这几项不出现。
OPTIONS: dict[str, tuple[str, ...]] = {
    "captions": ("burned_in", "generate"),
    "layout": ("split-4x3", "vertical-full-overlay"),
    "bgm": ("none", "light"),
}
DEFAULT: dict[str, Any] = {"hook": False, "motion": False, "captions": "burned_in", "layout": "split-4x3", "bgm": "none"}


class CutPlanError(ValueError):
    """说给 作者 看的一句话。"""


def clean(raw: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """只留认得的键；值不对就报错，不悄悄改。"""
    out = {**DEFAULT, **(base or {})}
    for key, value in (raw or {}).items():
        if key in ("hook", "motion"):
            if not isinstance(value, bool):
                raise CutPlanError(f"{'Hook' if key == 'hook' else '动效'} 只能是开或关")
            out[key] = value
        elif key in OPTIONS:
            if value not in OPTIONS[key]:
                raise CutPlanError(f"不认识的选项：{key} = {value}")
            out[key] = value
    return {k: out[k] for k in DEFAULT}


def route(plan: dict[str, Any]) -> str:
    return {(False, False): "plain", (False, True): "motion", (True, True): "full", (True, False): "hook"}[(bool(plan["hook"]), bool(plan["motion"]))]


def read(base: Path) -> dict[str, Any] | None:
    path = base / PLAN_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(base: Path, plan: dict[str, Any], *, started: bool) -> dict[str, Any]:
    data = {**plan, "started": started}
    (base / PLAN_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def from_project(info: dict[str, Any], saved: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """已经走上某条路的项目：选择从项目本身读出来（今天以前做的项目没有 cut-plan.json）。返回 (选择, 是否锁定)。"""
    layout = info.get("layout")
    if saved and saved.get("started"):
        return clean({k: saved[k] for k in DEFAULT if k in saved}), True
    if layout == "v2":
        return clean({"hook": False, "motion": True}), True
    if layout == "v2.6":
        spec = info.get("spec") or {}
        hook = spec.get("hook") != "no" and not info.get("hook_skipped")
        extra = {k: spec[k] for k in OPTIONS if spec.get(k) in OPTIONS[k]}
        return clean({"hook": hook, "motion": True, **extra}), True
    if info.get("delivered"):
        return clean({"hook": False, "motion": False}), True
    return (clean({k: saved[k] for k in DEFAULT if k in saved}) if saved else None), False


def _has_hook_clips(base: Path) -> bool:
    folder = base / "part-a-hook" / "individual"
    return folder.is_dir() and any(p.suffix.lower() == ".mp4" for p in folder.iterdir())


def blocks(info: dict[str, Any], plan: dict[str, Any] | None, base: Path, *, has_srt: bool) -> list[dict[str, Any]]:
    """进度条：只列这一条勾上的块。state = done / current / todo，第一个没做完的是 current。"""
    if plan is None:
        return []
    r = route(plan)
    rows: list[tuple[str, str, bool]] = [("words", "逐字稿", has_srt)]
    if info.get("layout") == "v2.6":
        steps = {s["step"]: s["done"] for s in info.get("steps") or []}
        done = lambda numbers: all(steps.get(n) for n in numbers)  # noqa: E731
        if plan["hook"]:
            rows.append(("hook", "Hook", done((5, 7, 8, 9))))
        rows.append(("motion", "动效", done((6, 10, 11, 12, 13))))
    elif info.get("layout") == "v2":
        if plan["hook"]:
            rows.append(("hook", "Hook", _has_hook_clips(base)))
        rows.append(("motion", "动效", bool(info.get("delivered"))))
    elif r in ("hook", "full"):
        rows.append(("pick", "选 Hook", (base / "analysis" / "worktable.json").is_file()))
        rows.append(("clips", "剪 Hook 片段", _has_hook_clips(base)))
        if r == "full":
            rows.append(("motion", "动效", False))
    elif r == "motion":
        rows.append(("motion", "动效", bool(info.get("delivered"))))
    rows.append(("final", "成片", bool(info.get("delivered") or info.get("final_video"))))
    # 10/20：成片已经在了（多半在外面剪完的），中间没走完的块不再标成「现在这步」，不然看着像还要回去剪
    out, current = [], rows[-1][2]
    for key, label, ok in rows:
        state = "done" if ok else ("todo" if current else "current")
        current = current or not ok
        out.append({"key": key, "label": label, "state": state})
    return out
