"""素材页（10/18 作者：选题工作台的「素材」那页也要放在 Studio）：别人的好东西放一处看，看中了直接加入选题。

只读、不另存：
- 素材卡：素材 Agent 里点了「留下」的卡（<config>/materials/cards/*.json）；
- 爆款视频：vault 002_对标内容 下的拆解笔记（标题、作者、链接、点赞、倍数，「为什么爆」那几条当备注）；
- 好网站：example.com/goodproduct 的公开清单（和选题工作台同一份，一小时取一次）。
视频样片、风格两个画廊在单点功能里（/tools/videos.json、/tools/styles.json），页面直接读那边。
选题工作台的「好仓库」是在它后台手动加的，本机没有，这里不放。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

VIDEO_FOLDER = "002_对标内容"
SITES_MANIFEST = "https://example.com/goodproduct/manifest.json"
SITES_BASE = "https://example.com/goodproduct/"
SITES_TTL = 3600
KINDS = [("card", "素材卡"), ("video", "爆款视频"), ("site", "好网站")]

_sites: dict[str, Any] = {"at": 0.0, "items": [], "why": ""}
_lock = threading.Lock()


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    head, sep, body = text[3:].partition("\n---")
    if not sep:
        return {}, text
    meta = {}
    for line in head.strip().splitlines():
        k, _, v = line.partition(":")
        if k.strip() and v.strip():
            meta[k.strip()] = v.strip().strip('"')
    return meta, body


def _section(body: str, name: str) -> str:
    m = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else ""


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def videos(vault: Path | None) -> list[dict[str, Any]]:
    folder = vault / VIDEO_FOLDER if vault else None
    if not folder or not folder.is_dir():
        return []
    out = []
    for p in folder.glob("*.md"):
        try:
            meta, body = frontmatter(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        url = meta.get("source") or meta.get("url") or ""
        if not url.startswith("http"):
            continue
        why = [re.sub(r"^[-*]\s*", "", x).strip() for x in _section(body, "为什么爆").splitlines() if x.strip()]
        likes, mult = _num(meta.get("likes")), _num(meta.get("multiple_of_median"))
        out.append({"id": "video:" + p.stem, "kind": "video", "title": re.sub(r"\s*#\S+", "", meta.get("title") or p.stem).strip() or p.stem,
                    "url": url, "author": meta.get("author", ""), "excerpt": _section(body, "主线")[:300], "note": why[0][:300] if why else "",
                    "when": meta.get("published") or "", "stats": {k: v for k, v in (("likes", likes), ("multiple", mult)) if v is not None}})
    return out


def parse_sites(manifest: list[dict]) -> list[dict[str, Any]]:
    out = []
    for e in manifest or []:
        if not isinstance(e, dict) or not e.get("title") or not e.get("source_url"):
            continue
        out.append({"id": "site:" + str(e.get("id") or e["source_url"]), "kind": "site", "title": e["title"], "url": e["source_url"],
                    "author": "", "excerpt": str(e.get("note") or "").strip()[:300], "note": "",
                    "image": SITES_BASE + e["image"] if e.get("image") else None, "when": e.get("collected_at") or ""})
    return out


def _fetch(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "content-studio"})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 —— 写死的公开地址
        return json.loads(r.read().decode("utf-8"))


def sites(fetch: Callable[[str], Any] = _fetch, now: Callable[[], float] = time.time) -> tuple[list[dict[str, Any]], str]:
    """取不到就用上一次的（没有就空着，说一句为什么），不拖慢页面。"""
    with _lock:
        if _sites["at"] and now() - _sites["at"] < SITES_TTL:
            return _sites["items"], _sites["why"]
        try:
            _sites.update(items=parse_sites(fetch(SITES_MANIFEST)), why="")
        except Exception as exc:  # noqa: BLE001
            _sites["why"] = f"好网站清单这次没取到：{str(exc)[:80]}"
        _sites["at"] = now()
        return _sites["items"], _sites["why"]


def cards(decks: list[dict]) -> list[dict[str, Any]]:
    """素材 Agent 里留下的卡。图和样片走 /materials/media/<来源>/<文件>。"""
    out = []
    for deck in decks:
        src = deck.get("source") or {}
        sid = src.get("id")
        for c in deck.get("cards") or []:
            if c.get("status") != "kept" or not sid:
                continue
            media = lambda f: f"/materials/media/{sid}/{f}" if f else None  # noqa: E731
            # 这是什么（what）当摘录，什么时候用（when）当备注
            out.append({"id": f"card:{sid}/{c.get('name')}", "kind": "card", "title": c.get("title") or c.get("name") or "",
                        "url": c.get("source_url") or src.get("url") or "", "author": src.get("author") or src.get("title") or "",
                        "excerpt": c.get("what") or "", "note": c.get("when") or "", "category": c.get("category") or "",
                        "image": media(c.get("poster")), "video": media(c.get("sample")),
                        "when": c.get("pushed_at") or src.get("learned_at") or ""})
    return out


def listing(kind: str, *, decks: list[dict], vault: Path | None, site_fetch: Callable[[str], Any] = _fetch) -> dict[str, Any]:
    site_items, why = sites(site_fetch) if kind in ("all", "site") else ([], "")
    groups = {"card": cards(decks) if kind in ("all", "card") else [], "video": videos(vault) if kind in ("all", "video") else [],
              "site": site_items}
    items = [x for k in ("card", "video", "site") for x in groups[k]]
    items.sort(key=lambda x: str(x.get("when") or ""), reverse=True)
    counts = {"card": len(cards(decks)), "video": len(videos(vault)), "site": len(sites(site_fetch)[0])}
    return {"kind": kind, "items": items, "kinds": [{"key": k, "name": n, "count": counts[k]} for k, n in KINDS], "why": why}
