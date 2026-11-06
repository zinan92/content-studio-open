"""X 长文、长帖发之前过一遍 QA：错字、读不通、没讲完的结尾（10/10 作者）。

作者：「我自己的内容有些时候其实不通顺，或者是没有讲完。我知道我跟你说过不要改我的内容，但是如果你只需要
modify just the ending to make it complete，或者是看到一些字体错误……你还是需要做一遍 QA。」

这是「只用他的原话」的一个有边界的例外，边界写在代码里，不只写在提示词里：
- AI 不交整篇，只交一张「改哪几处」的单子：每处是原文里逐字的一小段 → 改成什么、为什么。程序一处一处替换，
  单子以外的字一个都不会动。
- 每处都查：原文里只出现一次、不碰配图行和 summary 段、不跨段、改动小（不是换一句新话）、不带原文没有的数字。
  不合格的那一处丢掉，其余照用；全部加起来改动太大就整份不用。
- 结尾没讲完可以补 1–2 句收尾（不超过 ENDING_MAX 字），只能收拢文中已有的意思，不加新观点、新经历、新数字。
- 改前的原文存着（qa_before），页面上逐条列出改了什么，一键还原。
- 导语（10/10 晚 作者）：站在刷到这条的陌生读者的角度，开头看不出这是什么（给 agent 的 prompt、和 AI 的对话、
  原则清单、预测、自己的思考、录音整理）就在开头加一句第一人称导语直说；已经说清楚了就不加。≤ INTRO_MAX 字，
  不带原文没有的数字、不向读者提问。有 summary 的长文放在 summary 后面（summary 本身也会说清楚是什么）。
- 完整度（10/11）：判断整篇是否讲清楚、讲完；可删不可见指代或口水话，单处 ≤120 字、合计 ≤15%。
  编号由程序去掉或重排；小修后仍不完整的返回问题，由 作者 决定。
"""
from __future__ import annotations

from difflib import SequenceMatcher
from hashlib import sha1
from pathlib import Path
import json
import re
from typing import Any, Callable

from ... import writing_rules

from ... import outline
from ...paths import config_dir

RULES_FILE = "X 发前 QA.md"

KINDS = ("错字", "不通顺", "标点", "补结尾", "删")
VERSION = 4              # 10/11：长文长帖价值关，未发的重新检查
MAX_CHANGES = 12
BEFORE_MAX = 60          # 一处最多动原文里 60 个字：是改一个地方，不是改一段
DELETE_MAX = 120         # 只删读者看不到的指代或纯口水话，不改写
GROW_MAX = 20            # 一处最多比原来多 20 个字
ENDING_MAX = 100         # 补的结尾最多 100 个字（1–2 句）
INTRO_MIN, INTRO_MAX = 8, 90
BAIT = re.compile(r"你怎么看|你们怎么看|评论区|留言|告诉我|你觉得呢|欢迎讨论|转发|点赞|关注|[？?]")
EDIT_RATIO_MIN = 0.35    # 「不通顺」改完和原来的相似度下限：低于它就是换了一句新话
BODY_RATIO_MIN = 0.9     # 全文（不算补的结尾、从原文扣掉合法删除）相似度下限
IMAGE = re.compile(r"^!\[[^\]]*\]\([^)\s]+\)$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
NUMBERED = re.compile(r"^\d+[.)、](?!\d)[ \t]*")  # 段首编号：「2. 」「2.」「2、」都算，「2.5 倍」不算
VALUE_CHECKS = ("痛点", "解法", "收藏")
VALUE_KINDS = ("长文", "长帖", "合集", "热点长帖")
CHECKS = ("开头", "递进", "结尾", "编号", "指代")


class QAError(RuntimeError):
    """Shown to 作者 as-is."""


def rules_path() -> Path:
    references = writing_rules.references_dir()
    if references is not None:
        return references / writing_rules.LEGACY[RULES_FILE]
    workflows = outline.workflows_dir()
    # 默认 workflows 就是包内目录，客户保存的配置副本必须优先于它。
    custom = workflows / RULES_FILE
    if workflows.resolve() != outline.DEFAULT_WORKFLOWS.resolve() and custom.is_file():
        return custom
    customer = config_dir() / RULES_FILE
    return customer if customer.is_file() else outline.DEFAULT_WORKFLOWS / RULES_FILE


def save_path() -> Path:
    references = writing_rules.references_dir()
    if references is not None:
        return references / writing_rules.LEGACY[RULES_FILE]
    workflows = outline.workflows_dir()
    root = workflows if workflows.resolve() != outline.DEFAULT_WORKFLOWS.resolve() else config_dir()
    return root / RULES_FILE


def _read_rules(path: Path) -> str:
    try:
        body = re.sub(r"\A---\n.*?\n---(?:\n|\Z)", "", path.read_text(encoding="utf-8"), flags=re.S).strip()
        if body:
            return body
    except (OSError, UnicodeError):
        pass
    raise QAError(f"找不到 X 发前 QA 规则：{path}")


def bundled_rules() -> str:
    return _read_rules(outline.DEFAULT_WORKFLOWS / RULES_FILE)


def load_rules() -> dict[str, Any]:
    path = rules_path()
    bundled = outline.DEFAULT_WORKFLOWS / RULES_FILE
    try:
        text = _read_rules(path)
    except QAError:
        if writing_rules.references_dir() is not None:
            raise
        path = bundled
        text = bundled_rules()
    return {"path": str(path), "text": text, "bundled": path.resolve() == bundled.resolve(), "save_path": str(save_path())}


def rules_hash(text: str) -> str:
    return sha1(text.encode("utf-8")).hexdigest()[:10]


def prompt(text: str, *, kind: str, source: str = "", summary: bool = False, rules: str | None = None, short: bool = False) -> str:
    where = "原文位置（短帖不加导语）" if short else "标题下面那段 summary 后面" if summary else "标题下面第一段"
    rules = load_rules()["text"] if rules is None else rules
    if short:
        rules = "只检查短帖的错字、标点、通顺和意思是否讲完。没有标题和长文结构要求，不做痛点、解法或收藏价值判断。只作小修，不加导语、不调整编号。"
    value_output = ""
    if kind in VALUE_KINDS and not short:
        value_output = ' "value": {"痛点": {"ok": true, "why": "≤40字"}, "解法": {"ok": true, "why": "≤40字"}, "收藏": {"ok": true, "why": "≤40字"}},\n'
        rules += "\n只判断原文的痛点、解法、收藏价值；价值不够不许加内容、补价值或改写。三项分别交 ok 和 ≤40 字的 why。"
    else:
        rules = re.sub(r"(?ms)^## 价值：.*?(?=^## |\Z)", "", rules)
    structure_output = ('"intro": null, "numbering": "keep", "complete": true,' if short else
                        '"intro": {"kind": "prompt|对话|原则|预测|思考|录音整理|其他", "text": "导语那一句"} 或 null,\n'
                        ' "numbering": "keep|remove|renumber",\n'
                        ' "checks": {"开头": {"ok": true, "why": "一句话"}, "递进": {"ok": true, "why": ""}, '
                        '"结尾": {"ok": true, "why": ""}, "编号": {"ok": true, "why": ""}, "指代": {"ok": true, "why": ""}},')
    return f"""下面是 作者自己写 / 说的一篇 X {kind}，马上要发。帮他做一遍发前 QA。
{f"来源：{source}" if source else ""}

## QA 规则（{RULES_FILE}，他可以自己改）
{rules}

## 这次的位置
导语如果要写，放在{where}。

## 硬上限（代码会卡）
- 每处原文最多 {BEFORE_MAX} 字。
- 每处改完最多增加 {GROW_MAX} 字。
- 每处删除最多 {DELETE_MAX} 字。
- 合计删除不超过原文的 15%。
- 补结尾最多 {ENDING_MAX} 字。
- 导语最多 {INTRO_MAX} 字。
- 最多 {MAX_CHANGES} 处改动。
- issues 最多 5 条，每条最多 80 字。
- 不许带原文没有的数字，不碰配图和 summary，不跨段。

## 原文
{text.strip()}

## 输出
只输出一个 JSON，不要别的：
{{{structure_output}
{value_output} "issues": [],
 "changes": [{{"kind": "错字|不通顺|标点|补结尾|删", "before": "原文里逐字的一小段（补结尾时留空）", "after": "改成的样子（删时必须为空）", "why": "一句话"}}]}}
- before 要从原文里逐字复制，够定位就行（通常不超过 {BEFORE_MAX} 个字，删不超过 {DELETE_MAX} 字），在原文里只能出现一次，不能跨段。
"""


def _protected(text: str, summary: bool) -> list[tuple[int, int]]:
    """不许碰的地方：配图行；有 summary 的话第二段（summary）。"""
    blocks = list(re.finditer(r"[^\n]+(?:\n[^\n]+)*", text))  # 空行隔开的段
    return [(m.start(), m.end()) for i, m in enumerate(blocks) if IMAGE.match(m.group(0).strip()) or (summary and i == 1)]


def parse_intro(raw: str) -> dict[str, str] | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        intro = (json.loads(m.group(0)) if m else {}).get("intro")
    except ValueError:
        return None
    if not isinstance(intro, dict) or not str(intro.get("text") or "").strip():
        return None
    return {"kind": str(intro.get("kind") or "").strip(), "text": str(intro["text"]).strip()}


def check_intro(intro: str, text: str) -> str | None:
    if not INTRO_MIN <= len(intro) <= INTRO_MAX:
        return f"导语长度不对（{len(intro)} 字）"
    if "\n" in intro:
        return "导语要一句话"
    if "我" not in intro:
        return "导语要用第一人称"
    if BAIT.search(intro):
        return "导语里不向读者提问、不要关注评论"
    invented = [n for n in NUMBER.findall(intro) if n not in text]
    if invented:
        return f"导语里的数字原文里没有：{'、'.join(invented)}"
    return None


def insert_intro(text: str, intro: str, *, summary: bool) -> str:
    """导语放在标题下面第一段；有 summary 的放在 summary 后面。"""
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    at = 1 if len(blocks) > 1 else 0  # 第一段总是标题（长文是「# 标题」，长帖的第一行也是标题，没有 #）
    if summary:
        at += 1
    blocks.insert(min(at, len(blocks)), intro.strip())
    return "\n\n".join(blocks) + "\n"


def parse(raw: str) -> list[dict[str, str]]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise QAError("QA 没按格式输出")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise QAError("QA 输出的不是 JSON") from exc
    out = []
    for c in (data.get("changes") or [])[: MAX_CHANGES * 2]:
        if isinstance(c, dict):
            change = {k: str(c.get(k) or "").strip() if k != "before" else str(c.get(k) or "")
                      for k in ("kind", "before", "after", "why")}
            if change["kind"] == "删":
                change["after"] = str(c.get("after"))  # 空格、null、缺省都不算空字符串
            out.append(change)
    return out


def check(change: dict[str, str], text: str, protected: list[tuple[int, int]]) -> str | None:
    """这一处能不能用；能用返回 None，不能用返回原因。"""
    kind, before, after = change["kind"], change["before"], change["after"]
    if kind not in KINDS:
        return f"不认识的类型「{kind}」"
    if kind == "删" and after != "":
        return "删的 after 必须是空的"
    if kind != "删" and not after:
        return "改成的是空的"
    if "\n" in after.strip() or "\n" in before:
        return "跨段了"
    invented = [n for n in NUMBER.findall(after) if n not in text]
    if invented:
        return f"数字原文里没有：{'、'.join(invented)}"
    if IMAGE.match(after.strip()) or "![" in after:
        return "不许动配图"
    if kind == "补结尾":
        if len(after) > ENDING_MAX:
            return f"补的结尾太长（{len(after)} 字）"
        return None
    if not before.strip():
        return "没说改原文哪里"
    if len(before) > (DELETE_MAX if kind == "删" else BEFORE_MAX):
        return f"一处动的字太多（{len(before)} 字）"
    n = text.count(before)
    if n != 1:
        return "原文里找不到这一段" if n == 0 else "原文里这一段不止一处"
    if before == after:
        return "没改"
    at = text.index(before)
    if any(a < at + len(before) and at < b for a, b in protected):
        return "碰到了配图或 summary"
    if kind == "删":
        return None
    if len(after) > len(before) + GROW_MAX:
        return "改完长了太多"
    if kind == "不通顺" and SequenceMatcher(None, before, after).ratio() < EDIT_RATIO_MIN:
        return "改成了另一句话"
    return None


def apply(text: str, changes: list[dict[str, str]], *, summary: bool = False) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    """按单子一处一处改。返回（改后的全文，用上的，丢掉的〔带原因〕）。"""
    protected = _protected(text, summary)
    kept, dropped, ending = [], [], None
    new = text
    for c in changes:
        why = check(c, text, protected)
        if not why and c["kind"] != "补结尾" and new.count(c["before"]) != 1:
            why = "和前面改的那处重叠了"
        if not why and c["kind"] == "补结尾" and ending:
            why = "结尾只补一次"
        if not why and len(kept) >= MAX_CHANGES:
            why = f"超过 {MAX_CHANGES} 处"
        if why:
            dropped.append({**c, "reason": why})
            continue
        if c["kind"] == "补结尾":
            ending = c
        else:
            new = new.replace(c["before"], c["after"], 1)
        kept.append(c)
    deleted = [c for c in kept if c["kind"] == "删"]
    if sum(len(c["before"]) for c in deleted) > len(text) * 0.15:
        new, kept, retried = apply(text, [c for c in changes if c["kind"] != "删"], summary=summary)
        return new, kept, [*(c for c in dropped if c["kind"] == "删"), *retried,
                           *({**c, "reason": "删得太多"} for c in deleted)]
    baseline = text
    for c in deleted:
        baseline = baseline.replace(c["before"], "", 1)
    if SequenceMatcher(None, baseline, new).ratio() < BODY_RATIO_MIN:
        return text, [], [*dropped, *({**c, "reason": "加起来改动太大，整份不用"} for c in kept)]
    if deleted:
        # 只收拢删除留下的空白，保护 summary 和配图的原样文本。
        protected_blocks = {text[a:b] for a, b in protected}
        blocks = re.split(r"\n\s*\n", new)
        new = "\n\n".join(b if b in protected_blocks else re.sub(r"[ \t]{2,}", " ", b).strip()
                           for b in blocks if b.strip()) + ("\n" if text.endswith("\n") else "")
    if ending:
        new = _append_ending(new, ending["after"])
    return new, kept, dropped


def _append_ending(text: str, ending: str) -> str:
    """补在最后一段字后面（结尾是配图的话，放在配图前面）。"""
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    last = max((i for i, b in enumerate(blocks) if not IMAGE.match(b.strip())), default=len(blocks) - 1)
    blocks.insert(last + 1, ending.strip())
    return "\n\n".join(blocks) + "\n"


def renumber(text: str, mode: str, *, summary: bool = False) -> str:
    """只处理正文段首编号，标题、配图、summary 和其余空白原样保留。"""
    if mode not in ("remove", "renumber"):
        return text
    parts = re.split(r"(\n[ \t]*\n(?:[ \t]*\n)*)", text)
    block_index, number = 0, 0
    for i in range(0, len(parts), 2):
        block = parts[i]
        if not block.strip():
            continue
        skip = block_index == 0 or (summary and block_index == 1) or IMAGE.match(block.strip())
        block_index += 1
        if skip or not re.match(NUMBERED.pattern, block):
            continue
        number += 1
        parts[i] = re.sub(NUMBERED.pattern, "" if mode == "remove" else f"{number}. ", block, count=1)
    return "".join(parts)


def run(text: str, *, kind: str, write_fn: Callable[[str], str], summary: bool = False, source: str = "",
        has_intro: bool = False, rules: str | None = None, short: bool = False) -> dict[str, Any]:
    """返回改后 text、changes、dropped、intro 及整篇 complete/issues。一处都没改 text 就是原文。
    has_intro：上一轮已经加过导语，这轮不再加。"""
    raw = str(write_fn(prompt(text, kind=kind, source=source, summary=summary, rules=rules, short=short)) or "")
    changes = parse(raw)
    data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    new, kept, dropped = apply(text, changes, summary=summary)
    numbered = new if short else renumber(new, data.get("numbering", "keep"), summary=summary)
    if numbered != new:
        kept.append({"kind": "编号", "before": "", "after": "去掉编号" if data["numbering"] == "remove" else "重新编号",
                     "why": "让编号符合整篇结构并保持连续"})
        new = numbered
    intro = None if has_intro or short else parse_intro(raw)
    if intro:
        why = check_intro(intro["text"], text)
        if why:
            dropped.append({"kind": "导语", "before": "", "after": intro["text"], "why": intro["kind"], "reason": why})
            intro = None
        else:
            new = insert_intro(new, intro["text"], summary=summary)
            kept.insert(0, {"kind": "导语", "before": "", "after": intro["text"], "why": f"读者一眼看不出这是什么（{intro['kind']}）"})
    complete, issues, checks = verdict(data)
    if short:
        from ...x_post import MAX_WEIGHTED, weighted_length

        if weighted_length(new) > MAX_WEIGHTED:
            new, complete = text, False
            dropped.extend({**c, "reason": "改后超过短帖长度上限"} for c in kept)
            kept = []
            issues = ["改后超过短帖长度上限", *issues][:5]
    value = {}
    if kind in VALUE_KINDS and not short:
        ok, value_issues, checks_value = value_verdict(data)
        value = {"value_ok": ok if checks_value else None, "value": checks_value, "value_issues": value_issues}
    return {**value, "text": new, "changes": kept, "dropped": dropped, "intro": intro["text"] if intro else None,
            "complete": complete, "issues": issues, "checks": checks}


def verdict(data: dict[str, Any]) -> tuple[bool, list[str], dict[str, dict[str, Any]]]:
    """完整不完整由代码定：五项（开头、递进、结尾、编号、指代）有一项不过就不完整（10/11 作者：完整度检查要 thorough）。
    模型没给 checks 的（老格式）退回看 complete。"""
    raw = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    checks = {k: {"ok": (raw.get(k) or {}).get("ok") is not False, "why": str((raw.get(k) or {}).get("why") or "")[:80]}
              for k in CHECKS if isinstance(raw.get(k), dict)}
    issues = data.get("issues", [])
    issues = [i[:80] for i in issues if isinstance(i, str) and i.strip()][:5] if isinstance(issues, list) else []
    if checks:
        failed = [f"{k}：{v['why']}" if v["why"] else f"{k}不过" for k, v in checks.items() if not v["ok"]]
        return not failed, (issues or failed)[:5] if failed else [], checks
    complete = data.get("complete", True) is not False
    return complete, issues if not complete else [], checks


def value_verdict(data: dict[str, Any]) -> tuple[bool, list[str], dict]:
    """缺 value 属于没查，不拦旧数据；三项任一明确不过就不过。"""
    raw = data.get("value") if isinstance(data.get("value"), dict) else {}
    checks = {k: {"ok": raw[k].get("ok") is not False, "why": str(raw[k].get("why") or "")[:40]}
              for k in VALUE_CHECKS if isinstance(raw.get(k), dict)}
    issues = [f"{k}：{v['why']}" if v["why"] else f"{k}不过" for k, v in checks.items() if not v["ok"]]
    return not issues, issues, checks
