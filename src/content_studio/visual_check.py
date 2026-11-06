"""视觉规格的算术检查：在叫评审之前，先把机器能判的错挑掉。

来历：一份 9 镜头的 visual-plan 连着两轮被独立评审打回，6 条问题里有 4 条是算术或
核对——镜头对错了 12 秒、动画时长 ×3 超出窗口、引用的代码约定没核对、验收帧漏掉了
核心那一段。这些不该占用一次模型往返。

作者 的原话：「让一个大学生做很多基础算术题，然后做完之后要让另一个大学生来检查，
it's not supposed to happen。」对。所以算术交给脚本，评审只看判断题
（比如「这个图会不会被人读成反义」——那个机器查不出来）。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

# 一句话说完的时间和镜头开点差这么多秒，就算对错地方了。
ANCHOR_TOLERANCE = 2.0
CARD_DURATION = re.compile(r"^时长:\s*.*?([\d.]+)\s*s", re.MULTILINE)


class Finding(dict):
    """一条问题。字段跟独立评审的 findings 对齐，方便两边一起看。"""

    def __init__(self, shot_id: str, kind: str, detail: str, fix: str) -> None:
        super().__init__(shot_id=shot_id, kind=kind, severity="error", detail=detail, fix=fix)


def card_seconds(shots_root: Path, name: str) -> float | None:
    """从 ShotCraft 卡片的 frontmatter 读它自己声明的时长。"""
    for path in shots_root.rglob(f"{name}.md"):
        match = CARD_DURATION.search(path.read_text(encoding="utf-8"))
        return float(match.group(1)) if match else None
    return None


def check_anchor(shot: dict[str, Any], words: list[dict[str, Any]]) -> Finding | None:
    """镜头钉的那句话，真的是这个时间说的吗。

    这一条只有拿到词级时间才查得了——插值出来的 start_hint 本身就是猜的，
    拿猜的去校验猜的没有意义。
    """
    from . import koubo

    quote = (shot.get("quote") or "").strip()
    if not quote or not words:
        return None
    found = koubo.find_quote(words, quote)
    if found is None:
        return Finding(shot.get("id", "?"), "anchor-missing",
                       f"引用的原话在转写里找不到：「{quote[:30]}」",
                       "核对 quote 是不是照抄的转写原文")
    drift = abs(found["start"] - float(shot.get("start", 0)))
    if drift <= ANCHOR_TOLERANCE:
        return None
    return Finding(shot.get("id", "?"), "anchor-drift",
                   f"镜头开在 {shot.get('start')}s，但这句话真正是 {found['start']:.1f}s 说的，差 {drift:.1f} 秒",
                   f"把 start/end 和 cue_points 整体挪到 {found['start']:.1f}–{found['end']:.1f}s")


def check_budget(shot: dict[str, Any], shots_root: Path) -> Finding | None:
    """动画放得下吗：卡片自己声明的时长 × 段数 vs 窗口长度。"""
    recipe = shot.get("recipe") or {}
    name = recipe.get("name")
    if not name:
        return None
    need_one = card_seconds(shots_root, name)
    if need_one is None:
        return None
    # 段数只认结构化字段。从 motion 那段散文里数数字试过，在真实 plan 上误报成 10 段——
    # 「一份会误报的检查」比「没有检查」更糟，它会浪费 agent 一轮去修一个不存在的问题。
    # 数不清有几段就只查最保守的那种：一遍都放不下。
    stages = max(1, len(shot.get("relabel_stages") or []))
    window = float(shot.get("end", 0)) - float(shot.get("start", 0))
    need = need_one * stages
    if need <= window:
        return None
    return Finding(shot.get("id", "?"), "over-budget",
                   f"{name} 一遍要 {need_one:g} 秒 × {stages} 段 = {need:g} 秒，窗口只有 {window:.1f} 秒",
                   "给每段分配帧预算，或者换一张更短的卡，或者把窗口拉长")


def check_card_exists(shot: dict[str, Any], shots_root: Path) -> Finding | None:
    name = (shot.get("recipe") or {}).get("name")
    if not name or any(shots_root.rglob(f"{name}.md")):
        return None
    return Finding(shot.get("id", "?"), "card-missing",
                   f"引用的卡片在 ShotCraft 库里不存在：{name}",
                   "换成库里真实存在的卡；名字对不上的话它根本没被读过")


def check_verification(shot: dict[str, Any]) -> Finding | None:
    """定量镜头要写清楚「渲染出来怎么验」，否则画错了没人会发现。"""
    if not shot.get("quantitative"):
        return None
    chart = shot.get("chart") or {}
    frames = (chart.get("rendered_verification") or shot.get("rendered_verification") or {})
    at = frames.get("frames") or frames.get("at") or []
    if not at:
        return Finding(shot.get("id", "?"), "no-verification",
                       "定量镜头没写渲染后怎么验：抽第几帧、量什么、期望值多少",
                       "补 rendered_verification：帧号 + 测量对象 + 由数据算出的期望值")
    stages = [float(x) for x in (shot.get("relabel_stages") or []) if isinstance(x, (int, float))]
    if stages and not any(min(at) <= s <= max(at) for s in stages):
        return Finding(shot.get("id", "?"), "verification-gap",
                       f"验收帧只覆盖 {min(at)}–{max(at)}s，漏掉了这个镜头的关键阶段 {stages}",
                       "把每个 relabel_stage 都抽一帧")
    return None


def run(plan_path: Path, *, shots_root: Path, words_path: Path | None = None) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    words: list[dict[str, Any]] = []
    if words_path and words_path.is_file():
        words = json.loads(words_path.read_text(encoding="utf-8")).get("words") or []
    findings: list[Finding] = []
    for shot in plan.get("shots") or []:
        for found in (
            check_card_exists(shot, shots_root),
            check_anchor(shot, words) if words else None,
            check_budget(shot, shots_root),
            check_verification(shot),
        ):
            if found:
                findings.append(found)
    return {
        "status": "fail" if findings else "pass",
        "checked": len(plan.get("shots") or []),
        "had_word_timings": bool(words),
        "findings": findings,
    }
