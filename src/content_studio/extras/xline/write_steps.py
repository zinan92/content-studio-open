"""已经配好图、加好 summary 的文章，怎么拆开、怎么放回去（修改清单是对正文的修改，summary 和配图要先让开）。"""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from . import write_gates as gates


def now_iso(now: datetime | None = None) -> str:
    from .x_daily import now_bj

    return now_bj(now).isoformat(timespec="seconds")


def split_article(text: str, *, summary: bool) -> dict[str, Any]:
    """拆成：标题行、summary 段（如果有）、正文段落（含小标题）、配图（每张记着它前面那一段）。"""
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    title = paras.pop(0) if paras and paras[0].lstrip().startswith("# ") else ""
    head = paras.pop(0) if summary and paras else None
    body: list[str] = []
    images: list[tuple[str, str]] = []
    for p in paras:
        if gates.IMAGE.match(p):
            images.append((body[-1] if body else "", p.strip()))
        else:
            body.append(p.strip())
    return {"title": title.strip(), "summary": head.strip() if head else None, "body": body, "images": images}


def working_text(parts: dict[str, Any]) -> str:
    return "\n\n".join([parts["title"], *parts["body"]]).strip() + "\n"


def join_article(parts: dict[str, Any], new_text: str) -> str:
    """改好的正文放回去：标题和 summary 照旧，每张图放到最像它原来那一段的后面，找不到的放文末。"""
    new_body = [p for p in re.split(r"\n\s*\n", new_text.strip()) if p.strip() and not p.lstrip().startswith("# ")]
    after: dict[int, list[str]] = {}
    tail: list[str] = []
    front: list[str] = []
    for anchor, image in parts["images"]:
        if not anchor:
            front.append(image)  # 在第一段正文前面的图
            continue
        best, score = -1, 0.0
        for i, p in enumerate(new_body):
            ratio = 1.0 if anchor.strip() == p.strip() else SequenceMatcher(None, anchor[:200], p[:200]).ratio()
            if ratio > score:
                best, score = i, ratio
        (after.setdefault(best, []) if best >= 0 and score >= 0.6 else tail).append(image)
    out = [parts["title"]]
    if parts["summary"]:
        out.append(parts["summary"])
    out.extend(front)
    for i, p in enumerate(new_body):
        out.append(p)
        out.extend(after.get(i, []))
    out.extend(tail)
    return "\n\n".join(out).strip() + "\n"
