"""作者's positioning: who he is, how he finds customers, what he sells.

The file is 作者's own (`~/.claude/skills/content-qa/positioning.md`, next to
`principles.md`); he hand-edits it and both the 定位 page and Anna's soul read it on
every turn. The workbench never rewrites his words. The one thing it writes is a
dated proposal line inside its own marker block at the end (「待拍板」): Anna suggests
a sentence as an `[动作]` line, 作者 sees the exact text on the button and clicks,
and he later moves it into the body himself or deletes it.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from ...qa import DEFAULT_GUIDE, QA_GUIDE_ENV

FILE_NAME = "positioning.md"
DATA_NAME = "positioning.json"
BLOCK_START = "<!-- 工作台维护：Anna 提议 · 开始 -->"
BLOCK_END = "<!-- 工作台维护：Anna 提议 · 结束 -->"
HEADING = "## 待拍板（Anna 提议）"
INTRO = "Anna 在定位页提的建议，作者 点「记进定位」才写进来。采纳的挪进上面正文，不采纳的删掉。"
LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2})(?: · ([^｜]*))?｜(.+)$")
MAX_CHARS = 300
MAX_FILE_CHARS = 40000


class PositioningError(RuntimeError):
    """The positioning file could not be read or changed; the message is shown to 作者."""


def positioning_path(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser()
    guide = Path(os.environ.get(QA_GUIDE_ENV) or DEFAULT_GUIDE).expanduser()
    return guide.parent / FILE_NAME


def data_path(path: Path | None = None) -> Path:
    """The structured one pager (company, three questions, flywheel, pricing…), kept
    beside positioning.md so it never enters the public repo. The 定位 page draws it
    with the workbench's own components."""
    return positioning_path(path).with_name(DATA_NAME)


def read_data(path: Path | None = None) -> dict | None:
    target = data_path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PositioningError(f"读不到定位数据：{exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PositioningError(f"positioning.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict) or "company" not in data or "questions" not in data:
        raise PositioningError("positioning.json 缺 company 或 questions")
    return data


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def read(path: Path | None = None) -> dict:
    """What the 定位 page shows. A missing file is a state, not an error: 作者 has not
    written his positioning yet, and the page says so."""
    target = positioning_path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"path": str(target), "data": read_data(path), "exists": False, "markdown": "", "updated": None, "proposals": []}
    except OSError as exc:
        raise PositioningError(f"读不到定位文件：{exc}") from exc
    updated = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "path": str(target),
        "data": read_data(path),
        "exists": True,
        "markdown": _strip_frontmatter(text)[:MAX_FILE_CHARS],
        "updated": updated,
        "proposals": proposals(target),
    }


def proposal_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]


def _split(body: str) -> tuple[str, list[str], str]:
    start, end = body.find(BLOCK_START), body.find(BLOCK_END)
    if start < 0 or end < 0 or end < start:
        return body, [], ""
    inner = body[start + len(BLOCK_START):end]
    lines = [ln for ln in inner.splitlines() if ln.strip()]
    return body[:start], lines, body[end + len(BLOCK_END):]


def proposals(path: Path | None = None) -> list[dict]:
    target = positioning_path(path)
    try:
        body = target.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in _split(body)[1]:
        m = LINE_RE.match(ln)
        if m:
            out.append({"id": proposal_id(m.group(3)), "at": m.group(1), "source": (m.group(2) or "").strip(), "text": m.group(3).strip()})
    return out


def _write(target: Path, text: str) -> None:
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".positioning-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise PositioningError(f"写不进定位文件：{exc}") from exc


def add_proposal(text: str, *, source: str = "", path: Path | None = None, today: date | None = None) -> dict:
    """Append one dated line inside the marker block. The block is created at the end
    of the file if 作者's copy does not have one yet; everything above it is his."""
    text = " ".join(text.split())
    if not text:
        raise PositioningError("这一句是空的")
    if len(text) > MAX_CHARS:
        raise PositioningError(f"一句最多 {MAX_CHARS} 字")
    if "｜" in text or "\n" in text:
        raise PositioningError("这一句里不能有「｜」")
    target = positioning_path(path)
    try:
        body = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PositioningError("还没有定位文件；先在编辑器里写下三问再让 Anna 提议") from exc
    except OSError as exc:
        raise PositioningError(f"读不到定位文件：{exc}") from exc
    before, lines, after = _split(body)
    if any(proposal_id(LINE_RE.match(ln).group(3)) == proposal_id(text) for ln in lines if LINE_RE.match(ln)):
        raise PositioningError("这一句已经在待拍板里了")
    source = " ".join(source.split()).replace("｜", " ")
    stamp = (today or date.today()).isoformat()
    lines.append(f"- {stamp}{' · ' + source if source else ''}｜{text}")
    block = BLOCK_START + "\n" + "\n".join(lines) + "\n" + BLOCK_END
    if BLOCK_START in body:
        new = before + block + after
    else:
        new = body.rstrip() + f"\n\n---\n\n{HEADING}\n\n{INTRO}\n\n{block}\n"
    _write(target, new)
    return {"id": proposal_id(text), "at": stamp, "source": source, "text": text}


def remove_proposal(proposal_id_: str, path: Path | None = None) -> bool:
    target = positioning_path(path)
    try:
        body = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PositioningError(f"读不到定位文件：{exc}") from exc
    before, lines, after = _split(body)
    kept = [ln for ln in lines if not (LINE_RE.match(ln) and proposal_id(LINE_RE.match(ln).group(3)) == proposal_id_)]
    if len(kept) == len(lines):
        return False
    _write(target, before + BLOCK_START + "\n" + "\n".join(kept) + ("\n" if kept else "\n") + BLOCK_END + after)
    return True
