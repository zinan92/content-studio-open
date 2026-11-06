"""第一轮：给文章打分，再在他的原文上提「修改清单」（像 Word 的修订），不重写整篇。

模型只输出一份清单，每一条是对原文某一句话的一处修改：改 / 删 / 加 / 挪，带原因。没有评论（10/12 作者：全部直接改，缺他经历的地方就不出现）。
这里用代码核对每一条（原文里找得到、没有重叠、只用他的原词、没有新数字、每个原因只能做它被允许的事）、算改动预算
（对原文，默认 20%，他在页面上能改；超过的放进「没放进来」，调高预算就放进来），再应用到原文上。
他在页面上逐条接受、改一改、不要；最终的文字 = 原文 + 他接受的修改。
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Callable

from ... import writer
from . import write_gates as gates
from .write_module import Module, Step

JSON_BLOCK = re.compile(r"<<<JSON>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)
# 步骤 id → 它在修改清单里的原因
STEP_REASON = {"opening": "开头", "density": "高密度", "scarcity": "稀缺", "ending": "结尾", "style": "风格",
               "check-pain": "痛点", "check-benefit": "利他", "check-resonance": "共鸣", "check-complete": "完整度"}
SCORE_REASONS = ("高密度", "痛点", "利他", "完整度", "共鸣", "稀缺")      # 打分的六项（10/12 作者 点名的）
FRESH_REASONS = ("痛点", "利他", "共鸣", "稀缺", "结尾", "导语")        # 允许新写一句衔接的原因
OPS = ("replace", "delete", "insert", "move", "comment")
FRESH_EACH = 50
MAX_CHANGES, MAX_COMMENTS, MAX_BOLD, MAX_OVERFLOW = 40, 10, 6, 30


class PatchError(RuntimeError):
    """模型没按格式给清单：message 给 作者 看。"""


def score_names(module: Module, steps: list[Step]) -> list[str]:
    """这一次要打分的项。清单有 review（10/13 作者 的 9 项）就按清单来；老版本没有，退回原来的六项。"""
    if module.review:
        return [item.title for item in module.review_items(steps)]
    return [r for r in SCORE_REASONS if any(STEP_REASON.get(s.id) == r for s in steps)]


def score_rule_steps(module: Module, steps: list[Step]) -> list[Step]:
    """打分要看哪几步的规则。"""
    if module.review:
        wanted = {sid for item in module.review_items(steps) for sid in item.steps}
        return [s for s in steps if s.id in wanted]
    return [s for s in steps if STEP_REASON.get(s.id) in SCORE_REASONS]


def round_steps(module: Module, ids: list[str]) -> list[Step]:
    return [s for s in module.round_steps(ids, 1) if s.output == "changes"]


def reason_modes(steps: list[Step]) -> dict[str, str]:
    return {STEP_REASON[s.id]: s.fix for s in steps if s.id in STEP_REASON}


def step_may_add(step: Step) -> bool:
    """能不能新写一句衔接：清单写了 may-add；清单没写的老版本里，高密度也可以加（他定的：高密度只加不删）。"""
    return bool(step.may_add) or step.id == "density"


def step_may_delete(step: Step) -> bool:
    """能不能删口癖、重复、读者看不到的指代：清单写了听清单的；没写只有「风格」可以。"""
    return step.may_delete if step.may_delete is not None else step.id == "style"


def reason_perms(steps: list[Step]) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for s in steps:
        if s.id not in STEP_REASON:
            continue
        out[STEP_REASON[s.id]] = {"edit": s.fix == "edit", "add": step_may_add(s) and s.fix == "edit",
                                  "delete": step_may_delete(s) and s.fix == "edit", "move": s.may_move == "first-sentence" and s.fix == "edit"}
    return out


def build_prompt(module: Module, steps: list[Step], base: str, *, error: str | None = None) -> str:
    cap = module.constraints["max-change-pct"]
    perms = reason_perms(steps)
    seen: dict[str, str] = {}
    blocks = []
    for s in steps:
        text = module.step_text(s.id)
        same = seen.get(text)
        seen.setdefault(text, s.title)
        body = f"（规则同「{same}」，不重复）" if same else text
        blocks.append(f"### {s.title}（原因：{STEP_REASON.get(s.id, s.title)}）\n{s.does}\n\n{body}")
    rules = "\n\n".join(blocks)
    names = score_names(module, steps)
    scored = "、".join(names)
    example = names[0] if names else "高密度"
    add_only = [r for r, p in perms.items() if p["add"] and not p["delete"]]
    can_delete = [r for r, p in perms.items() if p["delete"]]
    can_move = [r for r, p in perms.items() if p["move"]]
    score_only = [r for r, p in perms.items() if not p["edit"]]
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    who = []
    if add_only:
        who.append(f"- **只能加**（原因：{'、'.join(add_only)}）：在某句话后面 insert 一句 text，最多 {FRESH_EACH} 字，只概括文中已经说过的意思，尽量用他文中的词。不能删、不能换他的字。")
    if can_delete:
        who.append(f"- **能删**（原因：{'、'.join(can_delete)}）：只删口癖和复读（单条不超过 {gates.FILLER_MAX} 字）、紧挨着重复的句子、读者看不到的指代（「放这个视频」「你可以看到我的屏幕」）；用 delete，或者 replace 成去掉口癖后的同一句。别的内容一律不删。")
    if can_move:
        who.append(f"- **能挪**（原因：{'、'.join(can_move)}）：把一句话挪到全文最前面（op: move），全篇最多一条。")
    if score_only:
        who.append(f"- **只打分、不写修改**（原因：{'、'.join(score_only)}）：这几项给分就行，清单里不要出现它们。")
    return f"""你在帮 作者 改他自己的一篇长文。按下面 park-writing 模块的几个步骤：先给这篇文章打分，再在他的原文上提具体的修改清单。你不重写整篇，只输出清单。

## 步骤和规则
{rules}

## 打分
给这几项各打 0 到 100 分，每项一句理由：{scored}。80 分是目标：改到大约 80 分就够，不要为了满分多改。

## 修改清单怎么写
**每一条都是直接修改，没有评论。**字段：
- reason：原因，只能是 {'、'.join(STEP_REASON[s.id] for s in steps if s.id in STEP_REASON and perms[STEP_REASON[s.id]]['edit'])}
- op：replace（把 anchor 换成 text）、delete（删掉 anchor）、insert（在 anchor 后面加一句 text）{'、move（把 anchor 这一整句挪到全文最前面）' if can_move else ''}
- anchor：从原文里逐字复制的一段话，**在全文里只出现一次**（口头禅这类重复的话，带上前后的字让它唯一），不能跨段，不能是标题
- text：replace / insert 的新内容
- note：一句话说为什么
每个原因能做什么（代码会逐条检查，做不到的会被丢掉）：
{chr(10).join(who)}
改动按重要程度排序，最要紧的放前面；总改动不超过原文的 {cap}%，放不下的后面的会被收起来。
**文中缺他自己的数字或经历、写不出来的地方，就不要写这一条**，也不要用占位或评论，那一项就空着。
加粗用 **…**，只加符号、不动字，只给「风格」用，全篇最多 {MAX_BOLD} 处；别为了有改动而只加粗，没什么要改的就不写。

## 约束
- 只用他的原词：replace 的 text 要么来自原文，要么是原文里已有的意思的最少改动；不换同义词，不把口语改成书面语，不润色。
- 段落和句子的顺序不动{'，唯一例外是「开头」可以把一句话挪到最前面' if can_move else ''}。
- 不加原文里没有的数字、经历、人名、英文词、比喻、例子、观点。
- 不出现抖音、视频号、小红书、B 站等平台名；不要开场白、「关注我」，也不要另起一段总结。结尾钩子（原因「结尾」）是例外：可以在最后一句话后面 insert 一句回扣开头的话，只用文中的词，不超过 {FRESH_EACH} 字。

## 文章
{base}

## 输出
整份放在单独一行的 <<<JSON>>> 和单独一行的 <<<END>>> 之间，是一个 JSON 对象（字符串里的引号要转义）：
{{"scores": {{"{example}": {{"score": 62, "why": "…"}}, …}}, "changes": [{{"reason": "开头", "op": "move", "anchor": "…", "text": "", "note": "…"}}, …]}}{retry}"""


def parse(raw: str) -> dict[str, Any]:
    match = JSON_BLOCK.search(raw) or re.search(r"(\{.*\})", raw, re.S)
    if not match:
        raise PatchError("没按格式返回（要在 <<<JSON>>> 和 <<<END>>> 之间）")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PatchError(f"返回的 JSON 读不懂：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("changes", []), list):
        raise PatchError("返回里没有 changes 列表")
    return data


def _scores(data: dict[str, Any], names: tuple[str, ...] | list[str] = SCORE_REASONS) -> dict[str, dict[str, Any]]:
    out = {}
    for name in names:
        item = (data.get("scores") or {}).get(name)
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            out[name] = {"score": max(0, min(100, int(item["score"]))), "why": str(item.get("why") or "")[:120]}
    return out


def _title_end(base: str) -> int:
    """标题段（# 开头的第一段）结束的位置。"""
    m = re.match(r"\s*#[^\n]*", base)
    return m.end() if m else 0


def _is_sentence(base: str, start: int, end: int) -> bool:
    before = base[:start].rstrip(" ")
    return (not before or before.endswith(("\n", "。", "！", "？", "!", "?"))) and base[start:end].rstrip().endswith(("。", "！", "？", "!", "?"))


def _cost(c: dict[str, Any]) -> tuple[int, int]:
    """(去掉或换掉的字, 新写的字)。"""
    if c["op"] == "comment":
        return 0, 0
    if c["op"] == "move":
        return len(c["anchor"]), len(c["anchor"])
    new = c.get("edit") if c.get("edit") is not None else c.get("text") or ""
    if c["op"] == "replace":  # 只加粗、只改标点的，算真正变了的字，不是整句
        matched = sum(m.size for m in SequenceMatcher(None, c["anchor"], new, autojunk=False).get_matching_blocks())
        return len(c["anchor"]) - matched, len(new) - matched
    return (len(c["anchor"]) if c["op"] == "delete" else 0), len(new)


def budget_pct(base: str, changes: list[dict[str, Any]]) -> float:
    size = max(len(gates.body_of(base)), 1)
    live = [c for c in changes if c["status"] != "rejected" and c["op"] != "comment"]
    dele = sum(_cost(c)[0] for c in live)
    ins = sum(_cost(c)[1] for c in live)
    return round(max(dele, ins) * 100 / size, 2)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _span(c: dict[str, Any]) -> tuple[int, int]:
    return (c["start"], c["end"])


def _overlap_problem(c: dict[str, Any], changes: list[dict[str, Any]]) -> str | None:
    if c["op"] in ("replace", "delete", "move"):
        if any(x["op"] in ("replace", "delete", "move") and _overlaps(_span(c), _span(x)) for x in changes):
            return "和前面的修改重叠了"
    if c["op"] == "insert":
        at = c["end"] if c.get("pos") == "after" else c["start"]
        if any(x["op"] in ("replace", "delete", "move") and x["start"] < at < x["end"] for x in changes):
            return "加的位置落在前面一处修改的中间"
    return None


def validate(module: Module, steps: list[Step], base: str, data: dict[str, Any]) -> dict[str, Any]:
    """核对模型给的清单。返回 {changes, overflow, scores, dropped, budget, gate_failures}。
    每个原因只能做它被允许的事；不合格的丢掉（记在 dropped），超预算的放进 overflow，不再变成评论。"""
    cap = module.constraints["max-change-pct"]
    perms = reason_perms(steps)
    title_end = _title_end(base)
    changes: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    moved = False

    for raw in data.get("changes", []):
        if not isinstance(raw, dict):
            continue
        reason, op = str(raw.get("reason") or ""), str(raw.get("op") or "")
        anchor, text, note = str(raw.get("anchor") or ""), str(raw.get("text") or ""), str(raw.get("note") or "")[:200]

        def drop(why: str) -> None:
            dropped.append({"reason": reason, "op": op, "anchor": anchor[:60], "why": why})

        perm = perms.get(reason)
        if perm is None:
            drop("原因不在这个流程里")
            continue
        if not perm["edit"]:
            drop("这一项只打分，不写修改")
            continue
        if op == "comment":
            drop("不再有评论，只写修改")
            continue
        if op not in OPS:
            drop("op 不认识")
            continue
        if len(changes) >= MAX_CHANGES:
            drop(f"超过 {MAX_CHANGES} 条")
            continue
        if not anchor.strip():
            drop("没有 anchor")
            continue
        count = base.count(anchor)
        if count != 1:
            drop("原文里找不到这一句" if not count else "这一句在原文里出现了多次，没法定位")
            continue
        start = base.index(anchor)
        end = start + len(anchor)
        if start < title_end or "\n\n" in anchor:
            drop("anchor 不能是标题，也不能跨段")
            continue
        c: dict[str, Any] = {"reason": reason, "op": op, "anchor": anchor, "text": text, "note": note, "start": start, "end": end,
                             "pos": "after" if str(raw.get("pos")) != "before" else "before", "fresh": False, "downgraded": False,
                             "status": "pending", "edit": None, "source": "round1", "inline": True}
        if (c["op"] == "replace" and text.strip() and text != anchor and anchor in text
                and text.replace("**", "") != anchor and text.replace(anchor, "", 1).replace("*", "").strip()):
            # 「把原话换成：原话 + 别的」其实是在原话前后加字（多半是把后面的话复制一份过来），按加字算，走加字的规矩
            extra = text.replace(anchor, "", 1).strip()
            c.update(op="insert", text=extra, pos="after" if text.startswith(anchor) else "before")
            text = extra

        problem = None
        if c["op"] == "move":
            if not perm["move"]:
                problem = "只有「开头」可以挪一句"
            elif moved:
                problem = "挪一句已经用过了"
            elif not _is_sentence(base, start, end):
                problem = "挪的要是完整的一整句"
            elif start == title_end or not base[title_end:start].strip():
                problem = "这一句已经在最前面"
        elif c["op"] == "delete":
            if not perm["delete"]:
                problem = f"「{reason}」这一项不能删字，只能加"
            elif gates.deletable(base, start, end) is None:
                problem = "只能删口癖、重复的句子、读者看不到的指代，这一处不是"
        elif c["op"] == "replace":
            bold_only = bool(text.strip()) and text.replace("**", "") == anchor
            if not perm["delete"]:
                problem = f"「{reason}」这一项不能换字，只能加"
            elif bold_only:
                if reason != "风格" or sum(1 for x in changes if x["op"] == "replace" and x["text"].replace("**", "") == x["anchor"]) >= MAX_BOLD:
                    problem = "只加粗没改字：只有「风格」可以，而且最多 %d 处" % MAX_BOLD
            elif not text.strip():
                c["op"] = "delete"
                if gates.deletable(base, start, end) is None:
                    problem = "只能删口癖、重复的句子、读者看不到的指代，这一处不是"
            elif len(text.replace("**", "")) > len(anchor) or writer.fidelity(text, anchor) < 0.8:
                problem = "换上去的话不是原句去掉口癖后的样子，不是他的原词"
            elif len(anchor) - len(text) > gates.FILLER_MAX and gates.deletable(base, start, end) is None:
                problem = "去掉的字太多，只能去口癖和重复"
        elif c["op"] == "insert":
            if not perm["add"]:
                problem = "这个原因不能新写字"
            elif not text.strip():
                problem = "没有要加的内容"
            elif reason == "结尾" and len(text) >= 8 and writer.fidelity(text, base) < 0.8:
                problem = "结尾钩子要用文中的话，这一句在原文里找不到"
            elif len(text) > FRESH_EACH:
                problem = f"新写的一句超过 {FRESH_EACH} 字"
            c["fresh"] = True
        if not problem and c["op"] in ("replace", "insert") and gates.new_facts(base, text.replace("**", "")):
            problem = "出现了原文里没有的数字或英文词：" + "、".join(gates.new_facts(base, text)[:3])
        if not problem:
            problem = _overlap_problem(c, changes)
        if problem:
            drop(problem)
            continue

        if budget_pct(base, [*changes, c]) > cap:
            if len(overflow) < MAX_OVERFLOW:
                overflow.append({**c, "status": "overflow", "overflow_why": "超出改动预算"})
            else:
                drop("改动预算用完了，没放进来的也满了")
            continue
        if c["op"] == "move":
            moved = True
        changes.append(c)

    result = {"changes": changes, "overflow": overflow, "scores": _scores(data, score_names(module, steps)), "dropped": dropped, "gate_failures": []}
    # 全部接受后整篇再过一遍关卡，当保险；不过就从最后一条往前收进「没放进来」，直到过
    constraints = {**module.constraints}
    may_move = "first-sentence" if any(p["move"] for p in perms.values()) else None
    may_add = "bridge-sentence" if any(p["add"] for p in perms.values()) else None
    while changes:
        failures = gates.check(base, render(base, changes, accept_all=True), constraints=constraints, may_move=may_move,
                               may_add=may_add, allow_new=0)
        if not failures:
            break
        result["gate_failures"] = failures
        last = changes.pop()
        overflow.insert(0, {**last, "status": "overflow", "overflow_why": "整体没过关卡：" + failures[0]})
    for n, c in enumerate(changes, 1):
        c["id"] = f"c{n}"
    for n, c in enumerate(overflow, 1):
        c["id"] = f"o{n}"
    result["budget"] = budget_pct(base, changes)
    return result


def apply_budget(trk: dict[str, Any], pct: Any) -> int:
    """他改了这一篇的预算：把「没放进来」的按顺序放进来，放得下的就放。调低不会动已经有的修改（接受过的不会被撤销），
    只是不再放新的。返回放进来几条。"""
    from .write_module import clamp_pct

    cap = clamp_pct(pct)
    trk["max_pct"] = cap
    base = trk["base"]
    constraints = {"max-change-pct": cap, "keep-order": True, "original-words": True, "no-new-facts": True}
    n = max([int(x["id"][1:]) for x in trk["changes"] if x["id"][:1] in ("c", "r") and x["id"][1:].isdigit()] + [0])
    kept: list[dict[str, Any]] = []
    added = 0
    for item in trk.get("overflow") or []:
        trial = {**item, "status": "pending"}
        live = [x for x in trk["changes"] if x["status"] != "rejected"]
        if (item["op"] == "move" and any(x["op"] == "move" for x in trk["changes"])) or _overlap_problem(trial, live) \
                or budget_pct(base, [*live, trial]) > cap:
            kept.append(item)
            continue
        probe = [*trk["changes"], {**trial, "status": "accepted"}]
        if gates.check(base, render(base, probe), constraints=constraints, may_move="first-sentence", may_add="bridge-sentence", allow_new=0):
            kept.append(item)
            continue
        n += 1
        trial.update(id=f"c{n}", overflow_why=None)
        trk["changes"].append(trial)
        added += 1
    trk["overflow"] = kept
    return added


def render(base: str, changes: list[dict[str, Any]], *, accept_all: bool = False) -> str:
    """原文 + 接受了（或改过）的修改 = 现在的文字。没处理的、不要的不算。"""
    edits: list[tuple[int, int, str]] = []
    tops: list[str] = []
    moved_top = ""
    title_end = _title_end(base)
    for c in changes:
        st = "accepted" if accept_all else c["status"]
        if c["op"] == "comment" or st not in ("accepted", "edited"):
            continue
        text = c["edit"] if c.get("edit") is not None else c["text"]
        if c["op"] == "move":
            edits.append((c["start"], c["end"], ""))
            moved_top = c["anchor"]
        elif c["op"] in ("replace", "delete"):
            edits.append((c["start"], c["end"], text if c["op"] == "replace" else ""))
        elif c["op"] == "insert" and c["pos"] == "top":
            tops.append(text)
        elif c["op"] == "insert":
            at = c["end"] if c["pos"] == "after" else c["start"]
            edits.append((at, at, text))
    out = base
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        out = out[:start] + text + out[end:]
    lead = [t.strip() for t in (*tops, moved_top) if t.strip()]
    if lead:
        # 标题后面插几段（导语在前，挪上来的那一句在后）；标题段结束的位置在所有改动前面，偏移不变
        out = out[:title_end] + "".join("\n\n" + t for t in lead) + out[title_end:]
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def counts(changes: list[dict[str, Any]]) -> dict[str, int]:
    out = {"pending": 0, "accepted": 0, "rejected": 0, "edited": 0, "resolved": 0}
    for c in changes:
        out[c["status"]] += 1
    return out


def pending_edits(changes: list[dict[str, Any]]) -> int:
    """还没处理的修改（评论不算，评论不拦着他往下走）。"""
    return sum(1 for c in changes if c["op"] != "comment" and c["status"] == "pending")


HISTORY_MAX = 30


def snapshot(trk: dict[str, Any], label: str) -> None:
    """处理之前存一份各条修改的状态和他改的字，「撤销」靠它（最多 30 步）。"""
    hist = trk.setdefault("history", [])
    hist.append({"label": label, "state": {c["id"]: [c["status"], c.get("edit")] for c in trk["changes"]}})
    del hist[:-HISTORY_MAX]


def undo(trk: dict[str, Any]) -> str:
    hist = trk.get("history") or []
    if not hist:
        raise PatchError("没有可以撤销的了")
    last = hist.pop()
    added = set(last.get("added") or ())
    if added:  # 「让 AI 写一版」加进来的修改，撤销时一起拿掉
        trk["changes"] = [c for c in trk["changes"] if c["id"] not in added]
    for c in trk["changes"]:
        if c["id"] in last["state"]:
            c["status"], c["edit"] = last["state"][c["id"]]
    if "overflow" in last:  # 「改预算」这一步：预算和「没放进来」也一起退回去
        trk["overflow"] = last["overflow"]
        if last.get("max_pct") is None:
            trk.pop("max_pct", None)
        else:
            trk["max_pct"] = last["max_pct"]
    return last["label"]


def set_status(changes: list[dict[str, Any]], cid: str, status: str, edit: str | None = None) -> dict[str, Any]:
    c = next((x for x in changes if x["id"] == cid), None)
    if c is None:
        raise PatchError("找不到这一处修改")
    allowed = ("pending", "resolved") if c["op"] == "comment" else ("pending", "accepted", "rejected", "edited")
    if status not in allowed:
        raise PatchError("这一处不能这样处理")
    if status == "edited":
        if c["op"] not in ("replace", "insert") or edit is None:
            raise PatchError("只有改和加的可以「用我改的」")
        c["edit"] = edit
    c["status"] = status
    return c


def set_all(changes: list[dict[str, Any]], status: str) -> None:
    """全部接受 / 全部不要：只动还没处理的修改；评论不碰（它们不改稿，也不挡着你往下走）。
    status 还可以是 reset：全部（包括评论）回到待处理，改的字也清掉。"""
    if status == "reset":
        for c in changes:
            c["status"], c["edit"] = "pending", None
        return
    if status not in ("accepted", "rejected"):
        raise PatchError("只能全部接受、全部不要或全部还原")
    for c in changes:
        if c["op"] != "comment" and c["status"] == "pending":
            c["status"] = status


STATUSES = ("pending", "accepted", "rejected", "edited", "resolved")


def restore(trk: dict[str, Any], snap: Any) -> None:
    """批注视图的「不保存，关闭」（10/13 作者）：每一下本来就存了，不保存 = 回到打开时的样子——各条的状态和改的字、
    预算和「没放进来」的；这次打开以后才放进来的修改拿掉。snap 是页面打开时记下的 {state, max_pct, overflow}。"""
    state = snap.get("state") if isinstance(snap, dict) else None
    if not isinstance(state, dict) or not state:
        raise PatchError("没有打开时的样子，退不回去")
    for cid, v in state.items():
        if not (isinstance(v, list) and len(v) == 2 and v[0] in STATUSES and (v[1] is None or isinstance(v[1], str))):
            raise PatchError(f"打开时的样子不对：{cid}")
    trk["changes"] = [c for c in trk["changes"] if c["id"] in state]
    for c in trk["changes"]:
        c["status"], c["edit"] = state[c["id"]]
    if "overflow" in snap and isinstance(snap["overflow"], list):
        trk["overflow"] = snap["overflow"]
    if "max_pct" in snap:
        if snap["max_pct"] is None:
            trk.pop("max_pct", None)
        else:
            trk["max_pct"] = int(snap["max_pct"])


def rescore_prompt(module: Module, steps: list[Step], text: str) -> str:
    names = score_names(module, steps)
    scored = "、".join(names)
    rules = "\n\n".join(f"### {s.title}\n{s.does}\n\n{module.step_text(s.id)}" for s in score_rule_steps(module, steps))
    return f"""给 作者 的这篇长文重新打分（他已经处理完了修改）。只打分，不改稿。

## 规则
{rules}

## 打分
这几项各打 0 到 100 分，每项一句理由：{scored}。

## 文章
{text}

## 输出
整份放在单独一行的 <<<JSON>>> 和单独一行的 <<<END>>> 之间：{{"scores": {{"{names[0] if names else '高密度'}": {{"score": 78, "why": "…"}}, …}}}}"""


def run_round1(module: Module, ids: list[str], base: str, *, write_fn: Callable[[str], str], attempts: int = 2) -> dict[str, Any]:
    """第一轮：一次调用。返回 validate 的结果，另带 steps（用到的步骤 id）和 rules（每步的规则版本）。"""
    steps = round_steps(module, ids)
    if not steps:
        return {"changes": [], "scores": {}, "dropped": [], "gate_failures": [], "budget": 0.0, "steps": [], "rules": {}}
    error = None
    for _ in range(attempts):
        try:
            data = parse(str(write_fn(build_prompt(module, steps, base, error=error)) or ""))
        except PatchError as exc:
            error = str(exc)
            continue
        result = validate(module, steps, base, data)
        return {**result, "steps": [s.id for s in steps], "rules": {s.id: module.step_version(s.id) for s in steps}}
    raise PatchError(error or "没有结果")


def rescore(module: Module, ids: list[str], text: str, *, write_fn: Callable[[str], str]) -> dict[str, dict[str, Any]]:
    steps = round_steps(module, ids)
    data = parse(str(write_fn(rescore_prompt(module, steps, text)) or ""))
    return _scores(data, score_names(module, steps))


QA_REASON = {"错字": "错字", "不通顺": "通顺", "标点": "通顺", "删": "通顺", "补结尾": "结尾", "导语": "导语"}


def merge_qa(trk: dict[str, Any], base: str, qa_changes: list[dict[str, str]], cap: int) -> int:
    """发前 QA 的改动单（错字、不通顺、标点、读者看不到的指代、补结尾、导语）并进同一份修改清单，一起留痕。
    和已有修改重叠的、预算不够的不并（记在 dropped 里）。返回并进来几条。QA 重跑时先清掉上一轮还没处理的 QA 条。"""
    changes = [c for c in trk["changes"] if not (c.get("source") == "qa" and c["status"] == "pending")]
    n = max([int(c["id"][1:]) for c in changes if c["id"][0] == "q"] + [0])
    added = 0
    for qc in qa_changes:
        kind = qc.get("kind")
        reason = QA_REASON.get(kind)
        if reason is None:
            continue  # 编号这类不在清单里留痕
        before, after = qc.get("before", ""), qc.get("after", "")
        if kind == "导语":
            c = {"op": "insert", "anchor": "", "text": after, "start": 0, "end": 0, "pos": "top", "fresh": True}
        elif kind == "补结尾":
            end = len(base.rstrip())
            c = {"op": "insert", "anchor": "", "text": after, "start": end, "end": end, "pos": "after", "fresh": True}
        else:
            if base.count(before) != 1 or not before:
                trk["dropped"].append({"reason": reason, "op": "qa", "anchor": before[:60], "why": "原文里找不到唯一的一处"})
                continue
            start = base.index(before)
            c = {"op": "replace" if after else "delete", "anchor": before, "text": after, "start": start, "end": start + len(before),
                 "pos": "after", "fresh": False}
        if c["op"] in ("replace", "delete") and any(x["op"] in ("replace", "delete", "move") and _overlaps(_span(c), _span(x)) for x in changes):
            trk["dropped"].append({"reason": reason, "op": "qa", "anchor": before[:60], "why": "和别的修改重叠了"})
            continue
        n += 1
        c.update(id=f"q{n}", reason=reason, note=str(qc.get("why") or "")[:200], status="pending", edit=None, downgraded=False,
                 inline=True, source="qa")
        if budget_pct(base, [*changes, c]) > cap:
            trk.setdefault("overflow", []).append({**c, "status": "overflow", "overflow_why": "超出改动预算"})
            continue
        changes.append(c)
        added += 1
    trk["changes"] = changes
    trk["budget"] = budget_pct(base, changes)
    return added


def build_trk(result: dict[str, Any], base: str, parts: dict[str, Any], *, when: str, pct: int = 20) -> dict[str, Any]:
    """第一轮的结果存成文章上的 trk：原文、拆开的 summary 和配图、修改清单、分数。"""
    return {"v": 1, "base": base, "parts": {"title": parts["title"], "summary": parts["summary"], "images": [list(x) for x in parts["images"]]},
            "changes": result["changes"], "overflow": result.get("overflow", []), "pct": pct,
            "scores": {"before": result["scores"], "after": None, "after_at": None},
            "budget": result["budget"], "dropped": result["dropped"], "gate_failures": result["gate_failures"],
            "steps": result["steps"], "rules": result["rules"], "round1_at": when, "rescoring": False}


def mutate(trk: dict[str, Any], fn: Callable[[dict[str, Any]], None], label: str | None = None) -> None:
    """处理修改的唯一入口（X 的文章、加工中的口播稿共用）：改清单，状态变了（或放进来新的、改了预算）就留一步历史，重算预算。
    调用方负责把文字重新渲染出来、存起来。fn 抛 PatchError 就原样往外抛，这一步什么都不留。"""
    before = {c["id"]: (c["status"], c.get("edit")) for c in trk["changes"]}
    meta_before = {"max_pct": trk.get("max_pct"), "overflow": json.loads(json.dumps(trk.get("overflow") or []))}
    fn(trk)
    after = {c["id"]: (c["status"], c.get("edit")) for c in trk["changes"]}
    meta_changed = meta_before["max_pct"] != trk.get("max_pct") or meta_before["overflow"] != (trk.get("overflow") or [])
    if (after != before or meta_changed) and label:
        hist = trk.setdefault("history", [])
        hist.append({"label": label, "state": {k: [v[0], v[1]] for k, v in before.items()},
                     "added": [k for k in after if k not in before], **meta_before})
        del hist[:-HISTORY_MAX]
    trk["budget"] = budget_pct(trk["base"], trk["changes"])


def handled_count(trk: dict[str, Any] | None) -> int:
    """他已经处理过几处（接受、改过、不要）——重新生成会清掉它们，要先问他。"""
    return sum(1 for c in (trk or {}).get("changes", []) if c["op"] != "comment" and c["status"] in ("accepted", "edited", "rejected"))
