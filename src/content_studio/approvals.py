"""打包页每一步的「定稿」：作者 看过、点了，这一版就锁住，下一步才开始。

9/29 作者：「每一个步骤做完之后，应该有一个 approve——这一版就是我们 lock in 的 version。锁定之后，
除非我手动去 revisit，否则就相当于我在搭积木，一点点往上搭。」

定稿记的是那一刻这一步产物的指纹（fingerprint）。指纹把它依赖的上一步也算进去：
标题改了，封面的指纹就变；文章改了，插图、排版、小红书、X 的指纹都变。指纹对不上，定稿就作废，
打包页显示「改过了，要重新定稿」——不用在每个改动的地方记得去清定稿。
存在草稿目录的 approvals.json：{key: {"fp": "...", "at": "..."}}。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

FILE = "approvals.json"
KEYS = ("copy", "cover", "article", "figs", "wx")
# 每一步要等哪一步定稿了才开始
# X 图文不单独定稿：它发的就是研习室那篇文章 + 插图，没有自己要改的东西（9/29 作者）。
# 小红书图文（xhs）是可选的一步：小红书在设置里选「图文」才有；选「视频」用的是封面和文案（9/29 作者）。
OPTIONAL = ("xhs",)
DEPENDS = {"cover": "copy", "figs": "article", "wx": "figs", "xhs": "figs"}


class ApprovalError(RuntimeError):
    """说给人听的一句话。"""


def digest(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _files(paths: list[Path]) -> list[tuple[str, float]]:
    return [(p.name, round(p.stat().st_mtime, 3)) for p in paths if p.is_file()]


def fingerprints(*, copy: dict[str, Any] | None, covers: list[Path], article: str | None,
                 figs: list[Path], wx: dict[str, Any], xhs: dict[str, Any] | None = None) -> dict[str, str | None]:
    """每一步现在的指纹；还没做出来的是 None。article 是去掉配图行的正文（配图插进文章不算改文章）。
    xhs 传了才有这一步（小红书选了图文）。"""
    fp: dict[str, str | None] = {k: None for k in KEYS}
    fp["copy"] = digest(copy) if copy else None
    title = next((e.get("title") for e in (copy or {}).values() if isinstance(e, dict) and e.get("title")), "")
    fp["cover"] = digest(_files(covers), title) if covers else None
    fp["article"] = digest(article) if article else None
    fp["figs"] = digest(_files(figs), fp["article"]) if figs and fp["article"] else None
    fp["wx"] = digest(wx.get("generated_at"), fp["figs"]) if fp["article"] and wx.get("has_layout") and not wx.get("stale") else None
    if xhs is not None:
        fp["xhs"] = digest(xhs.get("generated_at"), fp["figs"]) if fp["article"] and xhs.get("images") and not xhs.get("stale") else None
    return fp


def load(folder: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads((folder / FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def status(folder: Path, fps: dict[str, str | None]) -> dict[str, dict[str, Any]]:
    """每一步：made（做出来了没有）、approved（定过稿）、valid（定稿那一版还是现在这一版）、at。"""
    saved = load(folder)
    out = {}
    for key in (*KEYS, *(k for k in OPTIONAL if k in fps)):
        rec = saved.get(key) or {}
        out[key] = {"made": fps.get(key) is not None, "approved": bool(rec),
                    "valid": bool(rec) and rec.get("fp") == fps.get(key), "at": rec.get("at"),
                    # 机器替 作者 定的稿（补发提前打包，9/29 作者 预先授权）：页面上标出来，和他自己点的分开
                    "by": rec.get("by") or "park"}
    return out


def set_approval(folder: Path, key: str, approved: bool, fps: dict[str, str | None], *, now: datetime | None = None,
                 by: str = "park", skip: Any = ()) -> dict[str, dict[str, Any]]:
    """skip：关掉的步骤（10/9 设置 · 流程，比如插图）。依赖它的下一步不等它定稿。"""
    if key not in KEYS and not (key in OPTIONAL and key in fps):
        raise ApprovalError("没有这一步")
    saved = load(folder)
    if approved:
        if fps.get(key) is None:
            raise ApprovalError("这一步还没做好，定不了稿")
        dep = DEPENDS.get(key)
        if dep and dep not in skip:
            st = status(folder, fps)[dep]
            if not (st["approved"] and st["valid"]):
                raise ApprovalError("上一步还没定稿")
        saved[key] = {"fp": fps[key], "at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                      **({"by": by} if by != "park" else {})}
    else:
        saved.pop(key, None)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return status(folder, fps)
