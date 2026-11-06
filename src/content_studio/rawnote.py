"""在工作台里直接新建一篇原始输出（10/5 作者：「新建笔记还要去 Obsidian，再读回来，麻烦」）。

只存他写的字：标题 + 正文原样写进 003_原始输出（根下或已有的主题目录），不改写、不覆盖。
系列文件夹不在这里选——系列里的一集走选题池的「说这集」，编号由 系列.md 决定（series.py）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .extras.series import series as series_mod
from . import speak

SKIP = {"assets", "attachments"}


class RawNoteError(RuntimeError):
    """Shown to 作者 as-is."""


def folders(raw_root: Path) -> list[str]:
    """能放新笔记的地方：003 根下，加上已有的主题目录（不含系列、附件、隐藏目录）。"""
    if not raw_root.is_dir():
        return []
    subs = sorted(p.name for p in raw_root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP and not p.name.startswith(series_mod.PREFIX))
    return [""] + subs


def write(raw_root: Path, folder: str, title: str, body: str) -> Path:
    if not raw_root.is_dir():
        raise RawNoteError(f"Obsidian 里没有 {raw_root.name}")
    title, body = (title or "").strip(), (body or "").strip()
    if not body:
        raise RawNoteError("还没写内容")
    if not title:
        title = body.splitlines()[0][:30]
    folder = (folder or "").strip()
    if folder not in folders(raw_root):
        raise RawNoteError(f"003 里没有「{folder}」这个目录")
    lines = ["---", "type: 原始输出", "speaker: 作者（下面每一句都是 作者自己写的）", "how: 工作台里新建",
             f"created: {datetime.now().isoformat(timespec='minutes')}", "---", "", f"# {title}", "", body]
    try:
        return speak.write_note(raw_root / folder if folder else raw_root, title, "\n".join(lines) + "\n")
    except speak.SpeakError as exc:
        raise RawNoteError(str(exc)) from exc
