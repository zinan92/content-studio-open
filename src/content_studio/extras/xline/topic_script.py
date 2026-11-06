"""加工中的口播稿（逐字稿）：付息稿按 park-writing 的 11 点整理成他说话的样子，再走第一轮「打分 + 修改清单」（10/12 作者）。

- 付息稿（coupon.md）是带时间线、账本的排版稿；这里另出一份口播逐字稿 script.md：一整段连着的口语，没有小标题、
  列表、时间标注，像他说话。付息稿和账本原样留着，当拍摄备注。
- 来源四种：他挂在这条内容上的原话（原始输出里的笔记）/ 付息稿 / 他贴进来的稿子 / 拍完转出来的逐字稿。
  除了付息稿，都是他自己的话：不重写、不压缩，直接走第一轮（10/12 作者：已经有自己的话，就不走骨架、密度）。
- 修改清单的状态存在 script.trk.json；script.md 永远等于「原文 + 他接受的修改」。处理修改走和 X 长文同一套（write_patch）。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ... import writer
from . import write_gates as gates
from . import write_patch

SCRIPT = "script.md"
TRK = "script.trk.json"
LOCK = threading.RLock()
MIN_CHARS = 200
SOURCES = ("note", "coupon", "paste", "transcript")


class ScriptError(RuntimeError):
    """给 作者 看的话。"""


def folder(drafts_root: Path, topic_id: int) -> Path:
    return drafts_root.expanduser() / f"topic-{topic_id}"


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def read(drafts_root: Path, topic_id: int) -> dict[str, Any] | None:
    base = folder(drafts_root, topic_id)
    md, trk_path = base / SCRIPT, base / TRK
    if not md.is_file() or not trk_path.is_file():
        return None
    with LOCK:
        try:
            trk = json.loads(trk_path.read_text(encoding="utf-8"))
            text = md.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
    return {"id": topic_id, "text": text, "trk": trk, "updated_at": datetime.fromtimestamp(md.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}


def render_text(trk: dict[str, Any]) -> str:
    return write_patch.render(trk["base"], trk["changes"])


def save_new(drafts_root: Path, topic_id: int, trk: dict[str, Any]) -> dict[str, Any]:
    with LOCK:
        base = folder(drafts_root, topic_id)
        _atomic(base / SCRIPT, render_text(trk))
        _atomic(base / TRK, json.dumps(trk, ensure_ascii=False, indent=1))
    return read(drafts_root, topic_id) or {}


def update(drafts_root: Path, topic_id: int, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
    """处理一处修改（接受、改一改、不要、全部接受、撤销、改预算…）：改清单，script.md 跟着重新算。"""
    with LOCK:
        cur = read(drafts_root, topic_id)
        if cur is None:
            raise ScriptError("这一条还没有口播稿")
        trk = cur["trk"]
        try:
            write_patch.mutate(trk, fn, label)
        except write_patch.PatchError as exc:
            raise ScriptError(str(exc)) from exc
        text = render_text(trk)
        if text != cur["text"] and (trk.get("scores") or {}).get("after"):
            trk["scores"]["stale"] = True  # 改后的分是上一版文字打的
        base = folder(drafts_root, topic_id)
        _atomic(base / SCRIPT, text)
        _atomic(base / TRK, json.dumps(trk, ensure_ascii=False, indent=1))
    return read(drafts_root, topic_id) or {}


# -- 生成：付息稿 → 口播逐字稿 ----------------------------------------------------------------------

STRUCTURE = re.compile(r"^(?:#{2,}\s|[-*•]\s|\d+[.、)]\s|第[一二三四五六七八九十\d]+[点步条]|\|)|\d{1,2}:\d{2}", re.MULTILINE)


def build_prompt(topic: dict[str, Any], *, coupon: str, skeleton: str, sources: list[dict[str, Any]], style_rules: str,
                 error: str | None = None) -> str:
    material = "\n\n".join(f"### 他的原话 {i + 1}：{s['title']}\n\n{s['body']}" for i, s in enumerate(sources)) or "（没有附带原话，只根据付息稿写。）"
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""你在帮 作者 把一条口播视频的付息稿整理成「口播逐字稿」：就是他对着镜头一口气说出来的话，读出来像他说话。作者是你 本人。

## 先满足 park-writing 的这些点（整理的规矩，按重要程度）
{style_rules}

## 样子（很重要）
- 就是一整篇连着的口语，像他说话：可以有「对吧」「我觉得」「OK」，但一段里别超过两次；可以绕，每一绕都要回到主判断。
- **不要小标题、不要列表、不要「第一、第二」整整齐齐的结构、不要时间标注、不要账本。**付息稿里的时间线只是给你看节奏的。
- 第一句就是判断；每大约 10 秒要给听的人一点东西；结尾落回开头答应的那个东西。
- 用他的原话：能用他原话里的说法就别换；不加他没说过的数字、经历、人名、英文词。
- 不出现抖音、视频号、小红书、B 站等平台名，不说「关注我」。

## 选题
{topic['title']}

## 付息稿（时间线，给你看节奏；口播要照这个节奏说完）
{coupon or '（没有付息稿，只根据骨架写。）'}

## 骨架
{skeleton or '（没有骨架。）'}

## 他的原话
{material}

## 输出
整篇放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间，第一行是「# {topic['title']}」，后面是口播正文，不写解释。{retry}"""


def check_generated(text: str, *, blob: str) -> None:
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("# "))
    if len(re.sub(r"\s+", "", body)) < MIN_CHARS:
        raise ScriptError(f"口播稿太短，不到 {MIN_CHARS} 字")
    bad = STRUCTURE.search(body)
    if bad:
        raise ScriptError("里面有小标题、列表或时间标注，要连着说的一整篇口语")
    facts = gates.new_facts(blob, body)
    if facts:
        raise ScriptError("出现了付息稿、骨架和他原话里都没有的数字或英文词：" + "、".join(facts[:5]))
    if writer.fidelity(body, blob) < 0.5:
        raise ScriptError("和付息稿、他的原话对不上的话太多，要用他的原话")


def generate(topic: dict[str, Any], *, coupon: str, skeleton: str, sources: list[dict[str, Any]], style_rules: str,
             write_fn: Callable[[str], str], attempts: int = 2) -> str:
    blob = "\n".join([coupon, skeleton, *(str(s.get("body") or "") for s in sources)])
    error: str | None = None
    for _ in range(attempts):
        try:
            text = writer.extract_article(str(write_fn(build_prompt(topic, coupon=coupon, skeleton=skeleton, sources=sources,
                                                                    style_rules=style_rules, error=error)) or ""))
            check_generated(text, blob=blob)
            return text.strip() + "\n"
        except (writer.WriterError, ScriptError) as exc:
            error = str(exc)
    raise ScriptError(f"口播稿没写成：{error}")


def base_from(title: str, body: str) -> str:
    """他自己贴进来的 / 拍完转出来的话：不重写，加上标题行就是第一轮的原文。"""
    body = body.strip()
    if re.match(r"\s*#\s", body):
        return body + "\n"
    return f"# {title}\n\n{body}\n"


def parts_for(base: str) -> dict[str, Any]:
    first = base.strip().splitlines()[0] if base.strip() else "#"
    return {"title": first, "summary": None, "images": []}
