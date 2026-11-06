"""写作流程：每一步在每篇文章上跑没跑、什么时候跑的、用的哪一版规则（10/12 作者：「我问了你才知道没跑过」）。

只读：状态从文章上已经存的字段推出来，不改文章。每一步的状态：
  ran     跑了（带时间、规则版本、结果一句话）
  bundled 规则写在 park-writing 里，但整理时和别的塞在同一个提示词里，没有单独一步
  none    这一步还没做出来
  never   应该跑、没跑过（老文章，或还在排队）
  failed / running / skipped  照实说
stale：这一步用的规则文件后来改过，或检查的版本比现在旧，页面给「用新规则重跑」。
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any

from ... import writing_rules

# (id, 组, 名字)。顺序就是流程的顺序，不能调（10/9 定的：只开关，不调顺序）。
STEPS: tuple[tuple[str, str, str], ...] = (
    ("opening", "写", "开头"),
    ("density", "写", "高密度骨架"),
    ("scarcity", "写", "稀缺"),
    ("ending", "写", "结尾钩子"),
    ("style", "风格", "11 条风格（整理）"),
    ("check-pain", "查", "有没有真痛点"),
    ("check-benefit", "查", "够不够利他"),
    ("check-resonance", "查", "共鸣面够不够大"),
    ("check-complete", "查", "完整度五项"),
    ("check-typo", "查", "错字通顺和导语"),
)
QA_STEPS = ("check-pain", "check-benefit", "check-complete", "check-typo")


def skill_version() -> str | None:
    """park-writing 的 SKILL.md 现在的版本（内容的短哈希）；这台机器没装就是 None。"""
    root = writing_rules.skill_dir()
    if root is None:
        return None
    try:
        return sha1((root / "SKILL.md").read_bytes()).hexdigest()[:10]
    except OSError:
        return None


def current(qa_rules_hash: str | None, qa_version: int, module: Any = None, pct: int = 20) -> dict[str, Any]:
    """现在的规则版本，一次请求算一次。有清单就带上每一步现在的版本和清单里的步骤表。"""
    now: dict[str, Any] = {"qa_rules": qa_rules_hash, "qa_v": qa_version, "skill": skill_version(), "pct": pct}
    if module is not None:
        now["spec"] = [(s.id, s.group, s.title, s.status) for s in module.ordered()]
        now["step_versions"] = {s.id: module.step_version(s.id) for s in module.ordered() if s.runnable}
    return now


def _qa_stale(post: dict[str, Any], now: dict[str, Any]) -> bool:
    if post.get("qa") not in ("ready", "skipped"):
        return False
    if (post.get("qa_v") or 1) < int(now.get("qa_v") or 0):
        return True
    return bool(now.get("qa_rules") and post.get("qa_rules") and post["qa_rules"] != now["qa_rules"])


def _spec(now: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """步骤表：有清单就用清单的（名字、分组、顺序、哪些还没做），没有用写死的老表。"""
    if now.get("spec"):
        return list(now["spec"])
    return [(i, g, t, "planned" if i in ("scarcity", "check-resonance") else "whole") for i, g, t in STEPS]


REASON = {"opening": "开头", "density": "高密度", "scarcity": "稀缺", "ending": "结尾", "style": "风格", "check-pain": "痛点",
          "check-benefit": "利他", "check-resonance": "共鸣", "check-complete": "完整度"}
SCORED = {"density": "高密度", "check-pain": "痛点", "check-benefit": "利他", "check-complete": "完整度", "check-resonance": "共鸣",
          "scarcity": "稀缺"}


def _trk_note(trk: dict[str, Any], sid: str) -> str:
    """修改清单里这一步的结果：几处修改、处理到哪、几条评论、分数。"""
    reason = REASON.get(sid)
    mine = [c for c in trk["changes"] if c["reason"] == reason and c.get("source") != "qa"]
    edits = [c for c in mine if c["op"] != "comment"]
    comments = [c for c in mine if c["op"] == "comment"]
    bits = []
    if edits:
        done = sum(1 for c in edits if c["status"] in ("accepted", "edited"))
        left = sum(1 for c in edits if c["status"] == "pending")
        bits.append(f"改了 {len(edits)} 处" + (f"（接受 {done}" + (f"，待处理 {left}" if left else "") + "）" if done or left else ""))
    if comments:
        bits.append(f"评论 {len(comments)} 条")
    scores = trk.get("scores") or {}
    name = SCORED.get(sid)
    before = ((scores.get("before") or {}).get(name) or {}).get("score") if name else None
    after = ((scores.get("after") or {}).get(name) or {}).get("score") if name and scores.get("after") else None
    if before is not None:
        bits.append(f"分数 {before}" + (f" → {after}" if after is not None else ""))
    return " · ".join(bits) or "没有要改的"


def steps(post: dict[str, Any], now: dict[str, Any]) -> list[dict[str, Any]]:
    """长文长帖每一步的记录。短帖只过错字通顺，不列。"""
    if not post.get("long"):
        return []
    prepped = post.get("prep") == "ready"
    compiled = bool(post.get("compiled"))
    trk = post.get("trk") or None
    run = post.get("flow_run") or None
    in_flow = set(trk.get("ids") or ()) if trk else (set(run.get("ids") or ()) if run else None)
    flow_name = (trk or {}).get("flow") or (run or {}).get("flow") or ""
    versions = now.get("step_versions") or {}
    qa = post.get("qa")
    qa_stale = _qa_stale(post, now)
    at, rules = post.get("qa_at"), post.get("qa_rules")
    value = post.get("qa_value") or {}
    out: list[dict[str, Any]] = []
    for sid, group, title, status in _spec(now):
        def row(state: str, note: str = "", **kw: Any) -> None:
            out.append({"id": sid, "group": group, "title": title, "status": state, "at": kw.get("at"), "rules": kw.get("rules"),
                        "note": note, "stale": kw.get("stale", False), "gate_failures": kw.get("gate_failures") or [],
                        "report": kw.get("report"), "runnable": status != "planned"})
        if status == "planned":
            row("none", "这一步还没做出来")
        elif in_flow is not None and sid not in in_flow:
            row("off", f"这篇走的「{flow_name}」没有这一步")
        elif not trk and run and sid in (run.get("steps") or {}):  # #647 做的：一步一次调用，每一步当时的结果照实说
            rec = run["steps"][sid]
            row(rec.get("status") or "never", rec.get("note") or "", at=rec.get("at"), rules=rec.get("version"),
                stale=bool(rec.get("version") and versions.get(sid) and rec["version"] != versions[sid]),
                gate_failures=rec.get("gate_failures"), report=rec.get("report"))
        elif trk and sid in (trk.get("steps") or ()):  # 第一轮：一次调用打分 + 修改清单，这一步的结果从清单里读
            note = _trk_note(trk, sid)
            if sid == "check-complete" and qa == "ready":
                issues = post.get("qa_issues") or []
                note += " · QA：" + ("完整" if post.get("qa_complete") is not False else "不完整：" + (issues[0] if issues else "没写原因"))
            rules_v = (trk.get("rules") or {}).get(sid)
            row("ran", note, at=trk.get("round1_at"), rules=rules_v,
                stale=bool(rules_v and versions.get(sid) and rules_v != versions[sid]))
        elif sid == "check-typo" or (not trk and group == "查"):  # 第二轮 / 老文章：发前 QA 跑的
            if not trk and sid in ("check-pain", "check-benefit") and qa == "ready" and post.get("qa_value_ok") is not None:
                keys = ("痛点",) if sid == "check-pain" else ("解法", "收藏")
                bad = [k for k in keys if (value.get(k) or {}).get("ok") is False]
                row("ran", ("不过：" + "、".join(f"{k}：{(value.get(k) or {}).get('why', '')}" for k in bad)) if bad else "过",
                    at=at, rules=rules, stale=qa_stale)
            elif sid == "check-complete" and qa == "ready":
                issues = post.get("qa_issues") or []
                row("ran", "完整" if post.get("qa_complete") is not False else "不完整：" + (issues[0] if issues else "没写原因"),
                    at=at, rules=rules, stale=qa_stale)
            elif sid == "check-typo" and qa == "ready":
                n = sum(1 for c in (trk or {}).get("changes", []) if c.get("source") == "qa") if trk else len(post.get("qa_changes") or [])
                row("ran", f"{'提了' if trk else '改了'} {n} 处" if n else "没有要改的", at=at, rules=rules, stale=qa_stale)
            else:
                row(*_qa_gap(post))
        elif compiled:
            row("none", "合集：你的话按编号排好，没有改写")
        elif prepped:  # 老文章：整理那一步是 11 条风格，其余写作步骤没单独跑
            if sid == "style":
                skill = (post.get("flow_prep") or {}).get("skill")
                row("ran", "改写 + 开头 summary" if skill else "做的时候没记规则版本", at=post.get("prep_at"), rules=skill,
                    stale=bool(skill and now.get("skill") and skill != now["skill"]))
            else:
                row("bundled", "跟整理一起做的，没单独跑，没留结果")
        else:
            row("never", "还没做" if post.get("prep") in (None, "running") else "没做成")
    return out


def _qa_gap(post: dict[str, Any]) -> tuple[str, str]:
    """QA 没出结果时这一步的状态和说明。"""
    qa = post.get("qa")
    if qa == "running":
        return "running", "在跑"
    if qa == "failed":
        return "failed", post.get("qa_error") or "没跑成"
    if qa == "skipped":
        return "skipped", post.get("qa_error") or "QA 做的时候你改了字，没动"
    return "never", "QA 没跑过（QA 是 10/11 才上线的，这篇比它早）" if post.get("prep") == "ready" else "还没到 QA"


def attach(post: dict[str, Any], now: dict[str, Any]) -> None:
    rows = steps(post, now)
    if rows:
        post["flow"] = rows
        post["flow_stale"] = [r["id"] for r in rows if r["stale"]]
