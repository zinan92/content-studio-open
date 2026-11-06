"""送出去的鸡蛋：每条视频结尾送的东西，回复评论区的那段话术（10/14 作者）。

话术原样放在他的 Obsidian：`005_我发出的内容/鸡蛋/<日期> <名字>.md`，正文就是回复的原话（链接、怎么用都在里面）。
开头的属性里写 `source: 抖音视频链接` 就是这条鸡蛋在哪条视频后面送的（几条视频送同一份，就多写几行链接）；没写就不挂在任何一条上。
工作台只读它，不改它：汇总那张表给每条视频加一列，点开在 Obsidian 里看、复制。
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

FOLDER = "005_我发出的内容/鸡蛋"
VIDEO_ID = re.compile(r"douyin\.com/video/(\d+)")


def _frontmatter(text: str) -> dict[str, str]:
    """只认开头 `---` 之间的 `key: value` 行；不是属性的行不管。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "-")):
            meta[key.strip()] = value.strip()
    return meta


def load(vault: Path) -> list[dict[str, Any]]:
    """文件夹里每一份话术：名字、发出的日子、挂在哪几条视频上、Obsidian 里打开的链接。新的在前。"""
    root = vault / FOLDER
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.md"), reverse=True):
        if path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _frontmatter(text)
        out.append({"title": meta.get("title") or re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", path.stem), "sent": meta.get("sent") or path.stem[:10],
                    "videos": VIDEO_ID.findall(text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""),
                    "file": path.name, "open_url": f"obsidian://open?path={quote(str(path.resolve()), safe='')}"})
    return out


def by_video(vault: Path) -> dict[str, dict[str, Any]]:
    """视频 id → 它后面送的那份鸡蛋（一条视频送了好几份，取最新的；列表里新的在前，所以先到的算）。"""
    found: dict[str, dict[str, Any]] = {}
    for egg in load(vault):
        for vid in egg["videos"]:
            found.setdefault(vid, {k: egg[k] for k in ("title", "sent", "file", "open_url")})
    return found
