"""「你说一遍」：复刻的第一步。

10/4 作者 定的：拆完的爆款进选题池，在选题池里点了才开做。哪怕复刻，也一定要先变成他自己的原始输出。
10/5 作者 改的：不要「完全复刻 / 借他的结构」两个按钮，进去是同一个页面；也不要一段一段的填空底稿，
太限制。现在只有一个「复刻」：左边是那份拆解报告，右边一个空白大框，他用电脑的语音输入法直接口播。
「删口水话」可点可不点；存进 Obsidian 的原始输出，后面的骨架、付息稿只读他说的话。

「只删口水话、不改写」不靠提示词保证，靠代码：
- 句子由代码切（句号问号、换行；语音输入常一长串逗号，超过 60 字再在逗号处切）；
- 模型只回「这句删掉哪几个口水词」；
- 删的词必须在白名单里、必须真在那句话里；结果由代码从原句删出来，顺序、换行都照他说的。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FILE = "replicate.json"
# 10/5 起只有一个「复刻」。structure 是 10/4 那一天的旧数据，读得出来就行。
MODES = {"copy": "复刻", "structure": "复刻", "series": "说这集", "oral": "口述"}  # series：系列里的一集（series.py），没有拆解；oral：别人的材料（日报、收藏、Clippings），没有拆解、不借结构

SPEAK_COMMAND_ENV = "CONTENT_STUDIO_SPEAK_CMD"
DEFAULT_SPEAK_COMMAND = (
    "claude -p --model sonnet --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)

# 只删这些。宁可少删：「那个视频」「就是这样」里的「那个」「就是」不是口水话，所以只认带停顿的写法。
FILLERS = (
    "嗯", "呃", "额", "唔",
    "那个，", "那个,", "那个那个", "这个这个", "就是说，", "就是说,", "就是说",
    "然后呢，", "然后呢,", "怎么说呢，", "怎么说呢,", "怎么说呢", "你知道吗，", "你知道吗,", "对吧，", "对吧,",
    "其实吧，", "其实吧,", "反正就是，", "反正就是,",
)
LONG = 60

class SpeakError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(folder: Path) -> Path:
    return folder / FILE


def load(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(folder: Path, data: dict[str, Any]) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{FILE}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path(folder))
    return data


def from_report(report: dict[str, Any]) -> dict[str, Any]:
    """拆完的爆款进选题池时记下来的：出处、为什么爆、哪里会掉人，和每一段（不含跑题段）。"""
    facts = report.get("facts") or {}
    segments = [
        {"label": s.get("label") or "", "start": s.get("start"), "end": s.get("end"),
         "summary": s.get("summary") or "", "said": (s.get("text") or "").strip()}
        for s in report.get("segments") or [] if not s.get("drift")
    ]
    return {
        "video_id": str(report.get("content_id") or ""), "title": report.get("title") or "", "author": report.get("author") or "",
        "url": report.get("source_url") or "", "multiple": facts.get("multiple_of_median"),
        "thesis": (report.get("thesis") or {}).get("text") or "",
        "why_boom": [w.get("text") for w in report.get("why_boom") or [] if w.get("text")],
        "why_scatter": [w.get("text") for w in report.get("why_scatter") or [] if w.get("text")],
        "segments": segments, "mode": None, "dictation": "", "result": None,
        "state": "idle", "error": None, "note_path": None, "created_at": now(),
    }


def split_sentences(text: str) -> list[str]:
    """按句号、问号、叹号、分号、换行切；一句超过 LONG 字（语音输入常一串逗号）再在逗号处切。"""
    out: list[str] = []
    for line in re.split(r"\n+", text or ""):
        for piece in re.findall(r"[^。！？；!?;]+[。！？；!?;]*", line):
            piece = piece.strip()
            if not piece:
                continue
            if len(piece) <= LONG:
                out.append(piece)
                continue
            buf = ""
            for part in re.findall(r"[^，,]+[，,]?", piece):
                if buf and len(buf) + len(part) > LONG:
                    out.append(buf.strip())
                    buf = ""
                buf += part
            if buf.strip():
                out.append(buf.strip())
    return out


def prompt(sentences: list[str]) -> str:
    sents = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    return f"""你在帮一位口播博主整理他刚刚用语音输入说的一段话。

你只做一件事：指出每句里可以删掉的口水词。只能从这个清单里选，而且必须原样出现在那句话里；
拿不准是不是口水话的（比如「额度」「金额」里的「额」）就不要删。不许改写任何一个字。
清单：{"、".join(FILLERS)}

他说的话（已经按句编号）：
{sents}

只输出一个 JSON，不要别的文字：
{{"drop": [[句号, "要删的词"], ...]}}"""


def clean(dictation: str, ask_fn: Callable[[str], Any]) -> dict[str, Any]:
    """删口水话：模型只给出删哪几个词，代码校验后从原句删；顺序、换行都照他说的，一个字不改写。"""
    lines = [line for line in re.split(r"\n+", dictation or "") if line.strip()]
    per_line = [split_sentences(line) for line in lines]
    sentences = [s for group in per_line for s in group]
    if not sentences:
        raise SpeakError("还没说话：先在大框里说一遍")
    raw = ask_fn(prompt(sentences))
    data = raw if isinstance(raw, dict) else _json(raw)
    drops: dict[int, list[str]] = {}
    for pair in data.get("drop") or []:
        try:
            i, word = int(pair[0]), str(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= i < len(sentences) and word in FILLERS and _spot(sentences[i], word) >= 0:
            drops.setdefault(i, []).append(word)
    out, k = [], 0
    for group in per_line:
        kept = "".join(_clean(s, drops.get(k + n, [])) for n, s in enumerate(group))
        k += len(group)
        if kept:
            out.append(kept)
    return {"text": "\n\n".join(out), "dropped": sum(len(v) for v in drops.values()), "at": now()}


# 单字的口水词（嗯、呃、额、唔）后面要跟着停顿才算：「额，我觉得」删，「这个额度」「额度不够」不删。
PAUSE = r"(?=[，,。、…！？!?；;\s]|$)"


def _spot(sentence: str, word: str) -> int:
    if len(word) > 1:
        return sentence.find(word)
    m = re.search(re.escape(word) + PAUSE, sentence)
    return m.start() if m else -1


def _clean(sentence: str, words: list[str]) -> str:
    out = sentence
    for w in sorted(set(words), key=len, reverse=True):
        at = _spot(out, w)
        if at >= 0:
            out = out[:at] + out[at + len(w):]
            # 「干的：嗯，每天」删掉嗯会剩「：，」——前面已经是标点了，跟着的那个逗号也拿掉（10/10）
            if at < len(out) and out[at] in "，,、" and (at == 0 or out[at - 1] in "，,、。：:；;！？!?…"):
                out = out[:at] + out[at + 1:]
    out = re.sub(r"^[，,、\s]+", "", out).strip()
    return out if re.search(r"[\w一-鿿]", out) else ""


def _json(text: str) -> dict[str, Any]:
    start, end = str(text).find("{"), str(text).rfind("}")
    if start < 0 or end <= start:
        raise SpeakError("没删成，再点一次")
    try:
        return json.loads(str(text)[start:end + 1])
    except ValueError as exc:
        raise SpeakError("没删成，再点一次") from exc


def note_markdown(data: dict[str, Any], title: str) -> str:
    """存进原始输出的那一篇：只有他说的话；最上面写清出处。他人的原话不进来——骨架会从这篇挑开头。"""
    # 10/4 第一次走通时，骨架把这篇里 作者自己的经历当成了对标博主的（因为最上面写着「出处：千雪」），全改成了待办。
    # 所以开头要说死：只借了结构，下面每一句都是 作者自己说的。
    labels = " → ".join(s["label"] for s in data.get("segments") or [])
    lines = ["---", "type: 原始输出", "speaker: 作者（下面每一句都是 作者自己说的）",
             f"structure_from: {data.get('author') or ''}《{_clean_title(data.get('title') or '')}》{data.get('url') or ''}",
             "how: 复刻（只借了分段结构）", f"created: {now()}", "---", "",
             f"# {title}", "",
             f"> 下面每一句都是我（作者）自己说的话，是我自己的经历和判断。只借了 {data.get('author') or '对标博主'}"
             f"那条视频的分段结构{f'（{labels}）' if labels else ''}，没有用他的内容。", "",
             (data.get("dictation") or "").strip()]
    return "\n".join(lines).rstrip() + "\n"


def oral_note_markdown(data: dict[str, Any], title: str, source: str = "") -> str:
    """别人的材料（日报、收藏、Clippings）口述：只借了话题，下面每一句都是 作者自己说的。"""
    lines = ["---", "type: 原始输出", "speaker: 作者（下面每一句都是 作者自己说的）",
             f"source: {source}" if source else "source:", "how: 口述（只借了话题，没有用原文的话）" if source else "how: 口述", f"created: {now()}", "---", "",
             f"# {title}", "",
             "> 下面每一句都是我（作者）自己说的话，是我自己的经历和判断。" + ("别人的材料只是话题，里面的话一句都没用。" if source else ""), "",
             (data.get("dictation") or "").strip()]
    return "\n".join(lines).rstrip() + "\n"


def series_note_markdown(data: dict[str, Any], n: int, title: str) -> str:
    """系列里的一集：存进系列文件夹，只有他说的话。没有借谁的结构，所以不写出处。"""
    series = data.get("series") or ""
    lines = ["---", "type: 原始输出", "speaker: 作者（下面每一句都是 作者自己说的）",
             f"series: {series}", f"episode: {n}", f"created: {now()}", "---", "",
             f"# {title}", "", f"> {series} · 第 {n} 集。下面每一句都是我（作者）自己说的话。", "",
             (data.get("dictation") or "").strip()]
    return "\n".join(lines).rstrip() + "\n"


def _clean_title(title: str) -> str:
    return re.sub(r"\s*#\S+", "", title).strip()


def write_note(folder: Path, title: str, markdown: str) -> Path:
    """写进原始输出文件夹；同名不覆盖，后面加 -2、-3。"""
    if not folder.is_dir():
        raise SpeakError(f"Obsidian 里没有 {folder.name}")
    name = re.sub(r'[\\/:*?"<>|#]', "", title).strip()[:60] or "我说的"
    target = folder / f"{name}.md"
    n = 2
    while target.exists():
        target = folder / f"{name}-{n}.md"
        n += 1
    target.write_text(markdown, encoding="utf-8")
    return target


def cli_ask(prompt_text: str) -> str:
    import os
    import shlex
    import subprocess

    command = shlex.split(os.environ.get(SPEAK_COMMAND_ENV) or DEFAULT_SPEAK_COMMAND)
    from . import llm

    done = llm.run(command, input=prompt_text, timeout=300)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-2:]
        raise SpeakError("整理失败：" + " / ".join(tail)[:200])
    return done.stdout
