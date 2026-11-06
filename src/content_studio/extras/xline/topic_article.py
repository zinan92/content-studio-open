"""「标题和封面」那篇 X 图文文章的「润色」（10/13 作者）：不再让模型整篇重写，走和口播稿、X 长文同一个第一轮
（打分 + 修改清单），他在批注视图里逐条接受、改一改或不要。

- 原文就是现在的 article.md。拍了视频的，它是照视频字幕（SRT）整理的——10/13 作者 定：录完以后，他实际说的话是 baseline，
  录之前的口播稿只管录之前。
- 插图先拆出来，只改正文；article.md 永远等于「原文 + 他接受的修改」，插图放回最像它原来那一段的后面（write_steps）。
- 清单存在 article.trk.json，里面记着最后一次写出去的文字。article.md 在别处被改过（重写、手动编辑），清单就作废，要重新润色——
  不拿旧清单去改一篇已经不一样的文章。
- 开始润色前原文备份成 article.before-polish-<时间>.md。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from . import write_patch, write_steps

TRK = "article.trk.json"
LOCK = threading.RLock()
MIN_CHARS = 200


class ArticleError(RuntimeError):
    """给 作者 看的话。"""


def _atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def trk_path(article: Path) -> Path:
    return article.with_name(TRK)


def split(text: str) -> tuple[str, dict[str, Any]]:
    """拆出正文（第一轮的原文）和要让开的部分（标题、插图）。"""
    parts = write_steps.split_article(text, summary=False)
    return write_steps.working_text(parts), {"title": parts["title"], "summary": None, "images": parts["images"]}


def _paras(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip() and not p.lstrip().startswith("# ")]


def render_text(trk: dict[str, Any]) -> str:
    """原文 + 他接受的修改，插图放回去：先找一模一样的那段；改过了就找最像的，像的程度差不多时选离原来位置最近的
    （几段开头都差不多时，光比像不像会把图放到别的段后面）。找不到的放文末。"""
    old_body, new_body = _paras(trk["base"]), _paras(write_patch.render(trk["base"], trk["changes"]))
    front: list[str] = []
    after: dict[int, list[str]] = {}
    tail: list[str] = []
    for anchor, image in (tuple(x) for x in trk["parts"]["images"]):
        if not anchor:
            front.append(image)
            continue
        if anchor.strip() in new_body:
            after.setdefault(new_body.index(anchor.strip()), []).append(image)
            continue
        was = old_body.index(anchor.strip()) if anchor.strip() in old_body else None
        best, score = -1, float("-inf")
        for i, para in enumerate(new_body):
            ratio = SequenceMatcher(None, anchor[:200], para[:200]).ratio()
            fit = ratio - (0.05 * abs(i - was) if was is not None else 0)
            if ratio >= 0.6 and fit > score:
                best, score = i, fit
        (after.setdefault(best, []) if best >= 0 else tail).append(image)
    out = [trk["parts"]["title"], *front]
    for i, para in enumerate(new_body):
        out.append(para)
        out.extend(after.get(i, []))
    out.extend(tail)
    return "\n\n".join(out).strip() + "\n"


def read(article: Path) -> dict[str, Any] | None:
    """有清单、而且 article.md 还是清单最后写出去的那一版，才算在润色中。"""
    tp = trk_path(article)
    if not article.is_file() or not tp.is_file():
        return None
    with LOCK:
        try:
            trk = json.loads(tp.read_text(encoding="utf-8"))
            text = article.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
    if trk.get("rendered") != text:
        return None
    return {"text": text, "trk": trk, "updated_at": datetime.fromtimestamp(article.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}


def _write(article: Path, trk: dict[str, Any]) -> None:
    text = render_text(trk)
    trk["rendered"] = text
    _atomic(article, text)
    _atomic(trk_path(article), json.dumps(trk, ensure_ascii=False, indent=1))


def save_new(article: Path, trk: dict[str, Any], *, original: str, now: datetime | None = None) -> dict[str, Any]:
    """第一轮做完：原文备份一份，再写回（这时还没有接受任何修改，文字和原文一样，只是插图按段落重新摆过）。"""
    with LOCK:
        if article.read_text(encoding="utf-8") != original:
            raise ArticleError("润色的时候文章被改过了（重写或手动编辑），这一轮作废，再点一次润色")
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        article.with_name(f"{article.stem}.before-polish-{stamp}{article.suffix}").write_text(original, encoding="utf-8")
        _write(article, trk)
    return read(article) or {}


def update(article: Path, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
    """处理一处修改（接受、改一改、不要、全部接受、撤销、改预算…）：改清单，article.md 跟着重新算。"""
    with LOCK:
        cur = read(article)
        if cur is None:
            raise ArticleError("这篇文章没有在润色，或者润色之后被改过了，再点一次润色")
        trk = cur["trk"]
        try:
            write_patch.mutate(trk, fn, label)
        except write_patch.PatchError as exc:
            raise ArticleError(str(exc)) from exc
        if render_text(trk) != cur["text"] and (trk.get("scores") or {}).get("after"):
            trk["scores"]["stale"] = True  # 改后的分是上一版文字打的
        _write(article, trk)
    return read(article) or {}
