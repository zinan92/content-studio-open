"""One AI daily issue, item by item — so 作者 can take a single 快讯 into 选题池.

The daily file in the vault is a digest: every bullet is a two-line summary with a link.
The pipeline that wrote it keeps each item's full text as its own Markdown file (with the
original URL in the front matter) under `<items_root>/<YY-MM-DD>/<source>/…md`. Picking a
bullet finds that file by URL and snapshots its text into the topic's own drafts folder —
a snapshot, not a pointer, because the pipeline only keeps the last couple of days.

Nothing here writes to the Obsidian vault: the vault stays read-only apart from 对标内容.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from ...vault import parse_frontmatter

BULLET = re.compile(r"^- \*\*(?P<src>.+?)\*\*\s*\|\s*(?P<rest>.+)$")
LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)")
HEADING_LINK = re.compile(r"^###\s+\[(?P<text>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)\s*$")
X_STATUS = re.compile(r"/status(?:es)?/(\d+)")
# Sections whose entries are single items 作者 can take. Everything else (产品雷达、名词雷达、覆盖率)
# is shown as plain Markdown.
ITEM_SECTIONS = ("快讯", "视频更新")
DEEP_SECTION = "深读"
MAX_SCAN_BYTES = 4096


def url_key(url: str) -> str:
    """Same link, same key: x.com / twitter.com, trailing slashes and query strings do not matter."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("mobile.")
    if host in ("twitter.com", "x.com"):
        m = X_STATUS.search(parts.path)
        if m:
            return f"x:{m.group(1)}"
        host = "x.com"
    if host in ("youtube.com", "m.youtube.com") and parts.query:
        v = re.search(r"(?:^|&)v=([^&]+)", parts.query)
        if v:
            return f"yt:{v.group(1)}"
    if host == "youtu.be":
        return f"yt:{parts.path.strip('/')}"
    return f"{host}{parts.path.rstrip('/')}"


def item_id(urls: list[str]) -> str:
    return hashlib.sha1((urls[0] if urls else "").encode("utf-8")).hexdigest()[:10]


@dataclass
class Item:
    section: str
    group: str
    source: str
    title: str
    urls: list[str]
    summary: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": item_id(self.urls), "section": self.section, "group": self.group, "source": self.source,
                "title": self.title, "url": self.urls[0] if self.urls else None, "urls": self.urls,
                "summary": "\n".join(self.summary).strip()}


def parse_issue(markdown: str) -> dict[str, Any]:
    """Split a digest into sections. Item sections become lists of items; 深读 becomes a map
    from URL key to its paragraphs (merged into the pick); the rest stays Markdown."""
    title = ""
    sections: list[dict[str, Any]] = []
    deep: dict[str, dict[str, str]] = {}
    current: dict[str, Any] | None = None
    group = ""
    item: Item | None = None
    deep_key: str | None = None

    def close_item() -> None:
        nonlocal item
        if item is not None and current is not None:
            current["items"].append(item.as_dict())
        item = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            close_item()
            name = line[3:].strip()
            base = name.split("·")[0].strip()
            kind = "items" if base in ITEM_SECTIONS else "deep" if base == DEEP_SECTION else "markdown"
            current = {"name": name, "kind": kind, "items": [], "markdown": ""}
            sections.append(current)
            group, deep_key = "", None
            continue
        if current is None:
            continue
        if current["kind"] == "deep":
            m = HEADING_LINK.match(line)
            if m:
                deep_key = url_key(m.group("url"))
                deep[deep_key] = {"title": m.group("text"), "url": m.group("url"), "body": ""}
            elif deep_key and line.strip():
                deep[deep_key]["body"] = (deep[deep_key]["body"] + "\n" + line.strip()).strip()
            continue
        if current["kind"] == "markdown":
            current["markdown"] += raw + "\n"
            continue
        if line.startswith("### "):
            close_item()
            group = line[4:].strip()
            continue
        m = BULLET.match(line)
        if m:
            close_item()
            links = LINK.findall(m.group("rest"))
            item = Item(current["name"], group, m.group("src").strip(), links[0][0] if links else m.group("rest"),
                        [u for _, u in links])
            continue
        if item is not None and line.strip():
            text = line.strip()
            item.summary.append(text)
            item.urls += [u for _, u in LINK.findall(text) if u not in item.urls]
    close_item()
    for s in sections:
        s["markdown"] = s["markdown"].strip()
    return {"title": title, "sections": [s for s in sections if s["kind"] != "deep"], "deep": deep}


def _front_url(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(MAX_SCAN_BYTES)
    except OSError:
        return None
    meta, _ = parse_frontmatter(head if head.count("\n---") else head + "\n---\n")
    url = meta.get("url")
    return str(url) if url else None


def originals_index(items_root: Path | None, day: str) -> dict[str, Path]:
    """URL key → the item file the pipeline kept for that day. Empty when the day is gone."""
    if items_root is None:
        return {}
    folder = items_root.expanduser() / day
    if not folder.is_dir():
        return {}
    index: dict[str, Path] = {}
    for path in folder.rglob("*.md"):
        if path.parent == folder:  # 000-… / deep-… are digests, not items
            continue
        url = _front_url(path)
        if url:
            index.setdefault(url_key(url), path)
    return index


def find_original(item: dict[str, Any], index: dict[str, Path]) -> Path | None:
    # Every link in the bullet counts: some issues carry a broken first link and a 「更正链接」.
    for url in item.get("urls") or []:
        hit = index.get(url_key(url))
        if hit is not None:
            return hit
    return None


def read_original(path: Path) -> dict[str, Any]:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    return {"meta": meta, "body": body.strip()}


def issue_day(file_name: str) -> str | None:
    m = re.search(r"(\d{2})-(\d{2})-(\d{2})", file_name)
    return m.group(0) if m else None


def snapshot_markdown(item: dict[str, Any], *, issue: str, original: dict[str, Any] | None, deep: dict[str, str] | None,
                      now: datetime | None = None) -> str:
    """The text that goes into the topic. The original comes first and is labelled as such;
    when only the summary exists, the note says so instead of passing it off as the source."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    quality = "原文" if original else "只有摘要"
    lines = [
        "---",
        f"source: {item.get('url') or ''}",
        f"from: {issue}",
        f"author: {item.get('source') or ''}",
        f"quality: {quality}",
        f"picked_at: {stamp}",
        "---",
        "",
        f"# {item.get('title') or '日报快讯'}",
        "",
        f"> 来自 {issue} · {item.get('source') or ''}" + ("" if original else " · 只找到摘要，原文已经不在日报管道里了"),
        "",
    ]
    if item.get("summary"):
        lines += ["## 日报摘要", "", item["summary"], ""]
    if deep and deep.get("body"):
        lines += ["## 深读", "", deep["body"], ""]
    if original and original.get("body"):
        lines += ["## 原文", "", original["body"], ""]
    return "\n".join(lines).rstrip() + "\n"


SNAPSHOT_DIR = "sources"


def save_snapshot(drafts_dir: Path, topic_id: int, item: dict[str, Any], markdown: str) -> Path:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}" / SNAPSHOT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"daily-{item['id']}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def attached_sources(drafts_dir: Path, topic_id: int) -> list[dict[str, Any]]:
    """Snapshots stored with the topic, as writer/outline sources."""
    folder = drafts_dir.expanduser() / f"topic-{topic_id}" / SNAPSHOT_DIR
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), path.stem)
        out.append({"path": f"topic-{topic_id}/{SNAPSHOT_DIR}/{path.name}", "title": title, "url": meta.get("source") or None, "body": body.strip()})
    return out
