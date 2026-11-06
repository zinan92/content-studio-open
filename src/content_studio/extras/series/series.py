"""系列：一组讲同一件事的视频（10/5 作者：「系列1 工作台」整个系列都讲工作台）。

10/5 作者 定的：
- 系列就是 Obsidian 里 003_原始输出 下面的一个文件夹，名字以「系列」开头；
- 建系列时先写好每集标题，存在文件夹里的 系列.md（一行一集，都是他自己定的标题），
  在 Obsidian 里改了，选题池跟着变——Obsidian 是正本，工作台不另存一份；
- 每集是选题池里的一条选题；说完存进同一个文件夹，文件名「编号 标题」。

003 只放 作者自己的话：系列.md 里只有他写的名字和标题，不写 AI 的大纲。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ...vault import SERIES_INDEX as INDEX, parse_frontmatter

PREFIX = "系列"
_ITEM = re.compile(r"^\s*(?:\d+\s*[.、)）]\s*|[-*]\s+)(.+?)\s*$")
_UNSAFE = re.compile(r'[\\/:*?"<>|#]')


class SeriesError(RuntimeError):
    """Shown to 作者 as-is."""


def parse(text: str) -> list[str]:
    """系列.md 里一行一集：「1. 标题」或「- 标题」；其他行（标题、说明）不算。"""
    titles: list[str] = []
    for line in parse_frontmatter(text)[1].splitlines():
        m = _ITEM.match(line)
        if m and (title := m.group(1).strip()) and title not in titles:
            titles.append(title[:60])
    return titles


def all_series(raw_root: Path) -> list[dict[str, Any]]:
    """003 下每个「系列…」文件夹，按名字排（系列1、系列2…）。没有 系列.md 的文件夹不算。"""
    if not raw_root.is_dir():
        return []
    out = []
    for folder in sorted(p for p in raw_root.iterdir() if p.is_dir() and p.name.startswith(PREFIX)):
        index = folder / INDEX
        if not index.is_file():
            continue
        titles = parse(index.read_text(encoding="utf-8", errors="replace"))
        out.append({"folder": folder.name, "name": folder.name,
                    "episodes": [{"n": i, "title": t} for i, t in enumerate(titles, 1)]})
    return out


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _UNSAFE.sub("", text or "")).strip()


def create(raw_root: Path, name: str, titles: list[str]) -> dict[str, Any]:
    """建一个系列：003 下一个文件夹 + 系列.md。名字没以「系列」开头就排个号：「系列2 名字」。不覆盖已有的。"""
    if not raw_root.is_dir():
        raise SeriesError(f"Obsidian 里没有 {raw_root.name}")
    name = _clean(name)[:40]
    if not name:
        raise SeriesError("系列要有个名字")
    clean = [t for t in dict.fromkeys(_clean(t)[:60] for t in titles) if t]
    if not clean:
        raise SeriesError("至少写一集的标题")
    if not name.startswith(PREFIX):
        taken = sum(1 for p in raw_root.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
        name = f"{PREFIX}{taken + 1} {name}"
    folder = raw_root / name
    if folder.exists():
        raise SeriesError(f"已经有「{name}」了")
    folder.mkdir()
    lines = ["---", "type: 系列", f"created: {datetime.now().isoformat(timespec='minutes')}", "---", "",
             f"# {name}", "", "一行一集，标题是我（作者）自己定的。顺序就是拍的顺序；在这里改了，工作台的选题池跟着变。", ""]
    lines += [f"{i}. {t}" for i, t in enumerate(clean, 1)]
    (folder / INDEX).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return next(s for s in all_series(raw_root) if s["folder"] == name)


def episode_note_name(n: int, title: str) -> str:
    """说完存进系列文件夹的文件名（不带 .md）：「02 今天页只盯出摊」。"""
    return f"{n:02d} {_clean(title)}"[:64]
