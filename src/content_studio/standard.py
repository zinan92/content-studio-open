"""Rules 作者 learned from a teardown, written into his QA standard.

老师 accounts teach 怎么拍. A lesson that only lands as "我看了觉得有道理" changes
nothing; the same lesson written into the three-point standard changes how every
future topic is scored, because `qa.load_guide` and Anna's soul both read that file
on every turn.

The file is 作者's own skill (`~/.claude/skills/content-qa/SKILL.md`), which he
hand-edits and Claude Code loads as a skill. So this module only ever rewrites the
text between its own markers, splices on a literal anchor rather than walking
headings (「## 四、输出格式」 contains `## …` inside a code fence), leaves the
frontmatter byte-for-byte alone, and writes atomically with the original file mode.

Rule text comes from a teardown of someone else's video, so it is untrusted: the
workbench never writes one on its own. Anna proposes it as an [动作] line, 作者 sees
the exact sentence on the button and clicks.
"""
from __future__ import annotations

from datetime import date
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .qa import DEFAULT_GUIDE, MAX_GUIDE_CHARS, QA_GUIDE_ENV

BLOCK_START = "<!-- 工作台维护：从拆解里学来的 · 开始 -->"
BLOCK_END = "<!-- 工作台维护：从拆解里学来的 · 结束 -->"
HEADING = "## 五、从拆解里学来的"
INTRO = "拆解别人的视频学到的方法，作者 点了「记进标准」才写进来。评分时和上面三点一起用。"
ANCHOR = "## 参考与致谢"
RULE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2})(?: · ([^｜]*))?｜(.+)$")
MAX_RULE_CHARS = 200


class StandardError(RuntimeError):
    """The standard could not be changed; the message is shown to 作者."""


def guide_path(path: Path | None = None) -> Path:
    return (path or Path(os.environ.get(QA_GUIDE_ENV) or DEFAULT_GUIDE)).expanduser()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StandardError(f"读不到标准文件：{exc}") from exc


def rule_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]


def _split(body: str) -> tuple[str, list[str], str]:
    """(before, rule lines, after) around the managed block."""
    start, end = body.find(BLOCK_START), body.find(BLOCK_END)
    if start == -1 or end == -1 or end < start:
        return body, [], ""
    inner = body[start + len(BLOCK_START) : end]
    return body[:start], inner.splitlines(), body[end + len(BLOCK_END) :]


def _parse(lines: list[str]) -> list[dict[str, Any]]:
    out = []
    for line in lines:
        m = RULE_RE.match(line.strip())
        if m:
            out.append({"id": rule_id(m.group(3)), "at": m.group(1), "source": (m.group(2) or "").strip(), "text": m.group(3).strip()})
    return out


def rules(path: Path | None = None) -> list[dict[str, Any]]:
    target = guide_path(path)
    if not target.exists():
        return []
    return _parse(_split(_read(target))[1])


def _render(items: list[dict[str, Any]]) -> str:
    lines = ["- {}{}｜{}".format(i["at"], f" · {i['source']}" if i["source"] else "", i["text"]) for i in items]
    return f"{BLOCK_START}\n{HEADING}\n\n{INTRO}\n\n" + "\n".join(lines) + f"\n{BLOCK_END}"


def _frontmatter_len(body: str) -> int:
    m = re.match(r"\A---\n.*?\n---\n", body, flags=re.S)
    return m.end() if m else 0


def _write(path: Path, body: str) -> None:
    """Atomic, keeping the original file mode: a default-umask temp file would widen it."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".standard-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _apply(path: Path, items: list[dict[str, Any]]) -> None:
    body = _read(path)
    before, _, after = _split(body)
    if BLOCK_START in body:
        # Removing the last rule takes the block's blank lines with it, so the file comes
        # back byte-for-byte to what it was before the first rule was ever added.
        rebuilt = before + _render(items) + after if items else before.rstrip("\n") + "\n\n" + after.lstrip("\n")
    else:
        # First rule: splice in above the credits, or append if 作者 removed that section.
        block = _render(items)
        cut = body.find(ANCHOR)
        rebuilt = (body[:cut] + block + "\n\n" + body[cut:]) if cut != -1 else body.rstrip() + "\n\n" + block + "\n"
    size = len(rebuilt) - _frontmatter_len(rebuilt)
    if size > MAX_GUIDE_CHARS:
        raise StandardError(f"标准太长了（{size} 字，评分只读前 {MAX_GUIDE_CHARS} 字），先删掉几条再加")
    _write(path, rebuilt)


def add_rule(text: str, *, source: str = "", path: Path | None = None, today: date | None = None) -> dict[str, Any]:
    text = " ".join(text.split()).strip()
    if not text:
        raise StandardError("要写进标准的话是空的")
    if len(text) > MAX_RULE_CHARS:
        raise StandardError(f"一条标准最多 {MAX_RULE_CHARS} 字，太长了就不是标准了")
    if "｜" in text or "\n" in text:
        text = text.replace("｜", "·")
    target = guide_path(path)
    if not target.exists():
        raise StandardError(f"找不到标准文件：{target}")
    items = rules(target)
    if any(i["id"] == rule_id(text) for i in items):
        raise StandardError("这条已经在标准里了")
    item = {"id": rule_id(text), "at": (today or date.today()).isoformat(), "source": " ".join(source.split()).strip()[:40], "text": text}
    _apply(target, items + [item])
    return item


def remove_rule(rule_id_value: str, path: Path | None = None) -> bool:
    target = guide_path(path)
    items = rules(target)
    kept = [i for i in items if i["id"] != rule_id_value]
    if len(kept) == len(items):
        return False
    _apply(target, kept)
    return True
