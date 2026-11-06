"""拍后批注（10/13 作者）：录完、字幕放进项目后，用 park-writing 的 9 项清单给成片打分、写批注，一个字不改。

规则（打分看什么、批注怎么写）在 park-writing 里：module.yaml 的 post-shoot 指到 references/视频框架.md#评判，
评判清单是 review。这里只做三件事：把规则和字幕拼成提示、用代码核对模型的回答、存下来。
代码核对：
- 只认清单里的 9 项，分数是 0–10 的整数；
- 每项引用的原话必须真在字幕里，对不上的引用丢掉（理由留着，标「没引到原话」）；
- 「下一条要注意的」最多 5 条；模型要是给了改稿、改写之类的字段，一概不收，也不存。
"""
from __future__ import annotations

import json
import re
from hashlib import sha1
from pathlib import Path
from typing import Any

from . import write_patch
from .topic_script import _atomic, folder

FILE = "review.json"
MIN_CHARS = 200
MAX_NEXT = 5
MAX_QUOTE = 60


class ReviewError(RuntimeError):
    """给 作者 看的话。"""


def transcript_hash(text: str) -> str:
    return sha1(re.sub(r"\s+", "", text).encode("utf-8")).hexdigest()[:12]


def read(drafts_root: Path, topic_id: int) -> dict[str, Any] | None:
    try:
        data = json.loads((folder(drafts_root, topic_id) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("scores"), dict) else None


def save(drafts_root: Path, topic_id: int, record: dict[str, Any]) -> dict[str, Any]:
    _atomic(folder(drafts_root, topic_id) / FILE, json.dumps(record, ensure_ascii=False, indent=2))
    return record


def latest(drafts_root: Path, exclude: int | None = None) -> dict[str, Any] | None:
    """最近一条有「下一条要注意的」的批注（下一条口述前提醒他）；跳过正在做的这条。"""
    best: tuple[str, dict[str, Any]] | None = None
    root = drafts_root.expanduser()
    for path in root.glob(f"topic-*/{FILE}"):
        m = re.fullmatch(r"topic-(\d+)", path.parent.name)
        if not m or int(m.group(1)) == exclude:
            continue
        rec = read(root, int(m.group(1)))
        if rec and rec.get("next") and (best is None or str(rec.get("created_at") or "") > best[0]):
            best = (str(rec.get("created_at") or ""), {**rec, "topic_id": int(m.group(1))})
    return best[1] if best else None


def build_prompt(module: Any, transcript: str, *, error: str | None = None) -> str:
    items = list(module.review)
    names = "、".join(i.title for i in items)
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""你在给 作者 刚拍完的一条视频打分、写批注。这条已经拍完了：**只打分、只批注，一个字都不改，也不要写改稿、不要让他补拍**。
下面的字幕就是他说的话。

## 规则（park-writing）
{module.post_shoot_text()}

## 这一次要打分的项
{names}。每项 0 到 10 的整数，一句理由（说为什么），再从字幕里**逐字复制**一句最能说明问题的原话放进 quote（不超过 {MAX_QUOTE} 字，找不到合适的就留空，不要编）。
「错字通顺和导语」：拍视频没有导语，导语部分不扣分；错字和不通顺照常看。
最后写 1 到 {MAX_NEXT} 条「下一条要注意的」：每条一句话，写成他下一条要做的事，不是这一条的改稿。

## 字幕
{transcript}

## 输出
整份放在单独一行的 <<<JSON>>> 和单独一行的 <<<END>>> 之间：
{{"scores": {{"{items[0].title if items else '留人'}": {{"score": 7, "why": "…", "quote": "字幕里的原话"}}, …}}, "next": ["…", "…"]}}{retry}"""


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate(module: Any, transcript: str, data: dict[str, Any]) -> dict[str, Any]:
    """核对模型的回答。返回 {scores, next, dropped_quotes}；只认清单里的项，其余字段一概不收。"""
    blob = _squash(transcript)
    scores: dict[str, dict[str, Any]] = {}
    dropped = 0
    given = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    for item in module.review:
        raw = given.get(item.title)
        if not isinstance(raw, dict) or not isinstance(raw.get("score"), (int, float)) or isinstance(raw.get("score"), bool):
            continue
        quote = str(raw.get("quote") or "").strip()
        if quote and _squash(quote)[:MAX_QUOTE] not in blob:
            quote, dropped = "", dropped + 1
        scores[item.title] = {"id": item.id, "score": max(0, min(10, int(round(raw["score"])))),
                              "why": str(raw.get("why") or "")[:160], "quote": quote[:MAX_QUOTE]}
    notes = [str(n).strip()[:120] for n in (data.get("next") if isinstance(data.get("next"), list) else []) if str(n).strip()]
    if len(scores) < 3:
        raise ReviewError("模型只给了不到三项的分，不算数")
    return {"scores": scores, "next": notes[:MAX_NEXT], "dropped_quotes": dropped}


def run(module: Any, transcript: str, *, write_fn: Any, attempts: int = 2) -> dict[str, Any]:
    if not module.post_shoot or not module.review:
        raise ReviewError("这台机器的 park-writing 清单里还没有评判清单和拍后批注，先更新它")
    if len(_squash(transcript)) < MIN_CHARS:
        raise ReviewError(f"字幕太短，不到 {MIN_CHARS} 字")
    error = None
    for _ in range(attempts):
        try:
            data = write_patch.parse(str(write_fn(build_prompt(module, transcript, error=error)) or ""))
            return validate(module, transcript, data)
        except (write_patch.PatchError, ReviewError) as exc:
            error = str(exc)
    raise ReviewError(error or "没有结果")
