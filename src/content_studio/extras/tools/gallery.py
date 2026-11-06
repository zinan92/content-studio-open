"""风格画廊和打磨台（10/10 作者：几百种风格，每种先看到样子；他逐张点「通过 / 重做」，通过的才上公开站）。

样图在 styles/samples/<id>.webp（scripts/style-samples.py 批量出）；预览时可以用 CONTENT_STUDIO_STYLE_SAMPLES 指到别的文件夹。
他的「通过 / 重做」记在本机 ~/.config/content-studio/style-reviews.json，不进仓库。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from typing import Any

from ...paths import config_dir
from . import styles

HERE = Path(__file__).resolve().parent
VERDICTS = ("approve", "redo", "")  # 空 = 撤回，回到待看
PROMPT_CAP = 1200
_lock = threading.Lock()


def samples_dir() -> Path:
    """样图是生成出来的东西（几百张、几十 MB），放本机，不进仓库：~/.config/content-studio/style-samples。"""
    return Path(os.environ.get("CONTENT_STUDIO_STYLE_SAMPLES") or config_dir() / "style-samples")


def reviews_path() -> Path:
    return config_dir() / "style-reviews.json"


def reviews() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(reviews_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def review(style_id: str, verdict: str, note: str = "") -> dict[str, Any] | None:
    if styles.get(style_id) is None:
        raise KeyError(style_id)
    if verdict not in VERDICTS:
        raise ValueError(verdict)
    with _lock:
        data = reviews()
        if verdict:
            data[style_id] = {"verdict": verdict, "note": note.strip()[:500],
                              "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        else:
            data.pop(style_id, None)
        path = reviews_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    return data.get(style_id)


def sample_path(style_id: str) -> Path | None:
    if not re.fullmatch(r"[a-z0-9-]+", style_id or ""):
        return None
    path = samples_dir() / f"{style_id}.webp"
    return path if path.is_file() else None


_SOURCES: dict[str, dict[str, Any]] = {}


def source_of(style_id: str) -> dict[str, Any]:
    """来源记在每个文件的最外层（styles.load_all 不带），这里按文件建一张 id → 来源的表。"""
    if not _SOURCES:
        for path in sorted((HERE / "styles").glob("*.json")):
            if path.name == "index.json":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for s in [*data.get("styles", []), *data.get("grammars", [])]:
                _SOURCES[s["id"]] = data.get("source") or {}
    return _SOURCES.get(style_id, {})


def catalog(*, approved_only: bool = False) -> dict[str, Any]:
    """画廊要的：上架的风格（不含提示词全文以外的东西），带有没有样图、他看过没有。approved_only：公开站只要他通过的。"""
    have = {p.stem for p in samples_dir().glob("*.webp")} if samples_dir().is_dir() else set()
    marks = reviews()
    out = []
    for s in styles.load_all():
        if not s.get("listed"):
            continue
        mark = marks.get(s["id"])
        if approved_only and not (mark and mark["verdict"] == "approve" and s["id"] in have):
            continue
        out.append({"id": s["id"], "fn": s["function"], "cat": s["category"], "name": s["name"], "en": s.get("name_en") or "",
                    "sum": s.get("summary") or "", "prompt": (s.get("prompt") or "")[:PROMPT_CAP],
                    "src": {"repo": source_of(s["id"]).get("repo", ""), "license": source_of(s["id"]).get("license", ""),
                            "by": s.get("attribution") or source_of(s["id"]).get("attribution") or ""},
                    "sample": s["id"] in have, "review": None if approved_only else mark})
    return {"styles": out, "topic": "一个人用 AI 做自媒体，像同时指挥一支小乐队"}
