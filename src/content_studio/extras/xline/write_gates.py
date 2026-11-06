"""写作步骤产出之后的关卡：代码检查，不是提示词里的请求。过不了，这一步的产出作废、原文照旧。

对比的永远是整个流程开始时他自己的原文（base），不是上一步的结果：四步各改一点点，加起来也不能超过上限。
标题行（# 开头）和配图行不算。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ... import writer

IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
SENT_END = re.compile(r"(?<=[。！？!?])|\n+")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?%?")
LATIN = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
ALLOW_OPENING_NEW = 90      # 开头「直接说」那一句，skill 里最多 90 字
ALLOW_BRIDGE_NEW = 120      # 衔接句，一两句


def body_of(text: str) -> str:
    """正文：去掉标题行和配图行。"""
    return "\n".join(l for l in (text or "").splitlines() if not l.lstrip().startswith("#") and not IMAGE.match(l)).strip()


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body_of(text)) if p.strip()]


def sentences(text: str) -> list[str]:
    return [re.sub(r"\s+", "", s) for s in SENT_END.split(body_of(text)) if s and re.sub(r"\s+", "", s)]


def diff_stats(before: str, after: str) -> tuple[int, int]:
    """(从原文里去掉或换掉的字数, 新出现的字数)。先按段落对齐，没对上的段落再逐字比。"""
    a, b = paragraphs(before), paragraphs(after)
    deleted = inserted = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        left, right = "\n".join(a[i1:i2]), "\n".join(b[j1:j2])
        if not left or not right:
            deleted += len(left)
            inserted += len(right)
            continue
        matcher = SequenceMatcher(None, left, right, autojunk=len(left) + len(right) > 8000)
        matched = sum(m.size for m in matcher.get_matching_blocks())
        deleted += len(left) - matched
        inserted += len(right) - matched
    return deleted, inserted


def order_breaks(before: str, after: str) -> tuple[int, list[int]]:
    """挪了位置的整句：两边都有、但对不进同一个先后顺序的。返回 (句数, 它们在新稿里的位置)。
    先按整句求最长公共顺序，剩下的里两边都有的就是挪过的；删掉的、改过的不算挪。"""
    a, b = sentences(before), sentences(after)
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    in_a = {i for blk in blocks for i in range(blk.a, blk.a + blk.size)}
    in_b = {j for blk in blocks for j in range(blk.b, blk.b + blk.size)}
    loose_b: dict[str, list[int]] = {}
    for j, sent in enumerate(b):
        if j not in in_b:
            loose_b.setdefault(sent, []).append(j)
    moved: list[int] = []
    for i, sent in enumerate(a):
        if i not in in_a and loose_b.get(sent):
            moved.append(loose_b[sent].pop(0))
    return len(moved), moved


def new_facts(before: str, after: str) -> list[str]:
    """新稿里出现、原文里没有的数字和英文词。"""
    old = body_of(before)
    old_numbers = set(NUMBER.findall(old))
    old_words = {w.lower() for w in LATIN.findall(old)}
    found = [n for n in dict.fromkeys(NUMBER.findall(body_of(after))) if n not in old_numbers]
    found += [w for w in dict.fromkeys(LATIN.findall(body_of(after))) if w.lower() not in old_words]
    return found


INVISIBLE_REF = re.compile(r"放这个视频|你可以看到|大家可以看到|刚才(?:那|这)|下面这个画面|这个画面|我的屏幕|屏幕上|等一下给大家展示|这里需要素材")
FILLER_MAX = 40   # 口癖、复读：一条不超过这么多字


def _neighbours(base: str, start: int, end: int) -> list[str]:
    before = [s for s in re.split(r"(?<=[。！？!?])|\n+", base[:start]) if s.strip()][-2:]
    after = [s for s in re.split(r"(?<=[。！？!?])|\n+", base[end:]) if s.strip()][:2]
    return [re.sub(r"\s+", "", x) for x in (*before, *after)]


def deletable(base: str, start: int, end: int) -> str | None:
    """能删的只有三种：口癖复读（短）、紧挨着重复的句子、读者看不到的指代。是哪一种返回名字，不是返回 None。"""
    part = base[start:end]
    plain = re.sub(r"\s+", "", part)
    if not plain:
        return None
    if INVISIBLE_REF.search(part):
        return "读者看不到的指代"
    if any(plain and SequenceMatcher(None, plain, n).ratio() >= 0.8 for n in _neighbours(base, start, end) if n):
        return "重复"
    if len(plain) <= FILLER_MAX:
        return "口癖"
    return None


def check(base: str, after: str, *, constraints: dict[str, Any], may_move: str | None = None, may_add: str | None = None,
          opening: bool = False, allow_new: int | None = None) -> list[str]:
    """返回没过的关卡，一条一句人话；空表示全过。base 是整个流程开始时他自己的原文。"""
    failures: list[str] = []
    if not after.lstrip().startswith("#"):
        return ["新稿第一行不是标题"]
    size = max(len(body_of(base)), 1)
    deleted, inserted = diff_stats(base, after)
    cap = int(constraints.get("max-change-pct", 20))
    if allow_new is None:
        allow_new = (ALLOW_OPENING_NEW if opening else 0) + (ALLOW_BRIDGE_NEW if may_add else 0)
    pct = max(deleted, max(inserted - allow_new, 0)) * 100 / size
    if pct > cap:
        failures.append(f"改动 {pct:.0f}%，超过上限 {cap}%（去掉或换掉 {deleted} 字，新写 {inserted} 字）")
    if constraints.get("keep-order", True):
        breaks, positions = order_breaks(base, after)
        allowed = 1 if may_move == "first-sentence" else 0
        if breaks > allowed:
            failures.append(f"有 {breaks} 句挪了位置，只允许{'开头挪一句' if allowed else '不挪'}")
        elif breaks and any(p > 1 for p in positions):
            failures.append("只允许把一句挪到最前面，挪到了别的地方")
    if constraints.get("original-words", True):
        score = writer.fidelity(body_of(after), body_of(base))
        floor = 1 - cap / 100 - allow_new / max(len(body_of(after)), 1)
        if score < floor:
            failures.append(f"只有 {score:.0%} 的话能在原文里找到，要求至少 {max(floor, 0):.0%}：不换说法")
    if constraints.get("no-new-facts", True):
        facts = new_facts(base, after)
        if facts:
            failures.append("出现了原文里没有的数字或英文词：" + "、".join(facts[:5]))
    return failures
