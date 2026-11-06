"""作品：做过的产品每个一页截图，放在左栏「门户」下面（10/7 作者）。

作者：「把我做的产品截图都放在前端，类似 GitHub 和网站这样。」他列了五个：内容工作台、轻练、天机、知识星球小程序、tradingsystem。

- 清单存在本机：<config>/products/list.json，一条 {key, name, for, url, views}。页面上加、改、删；
  代码里不写任何一个产品（装到别人电脑上是空的，各自加自己的）。
- 有网址的：和门户一样，每天第一次打开那一页时截第一屏，链接改了也重截，能手动「重新截」，留 30 天。
  views 选截哪几种：小程序那种只要手机，交易台只要电脑。
- 没网址的（小程序在微信里，截不到）：他传截图，一张一张留着，能删。
- 只截图，不做 AI 判断（门户那套「陌生人认不认得你」问的是人，不是产品）。
- 存哪：<config>/products/<key>/<日期>/ 下 desktop.png、mobile.png、meta.json；传的图在 <config>/products/<key>/uploads/。
- 10/9 作者（变现流程板）：「作品」拆开，左栏「产品」一组每个一个 tab，每页六段：产品 / 报价 / 收款 / 流量入口 / 投放 / 漏斗。
  报价、收款、落地页、私信关键词、投放计划和预算也存在这份清单里；报价只写他说过的，空着就是「待定」。
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Callable

from ..portal import portal
from ...paths import config_dir

UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD = 15 * 1024 * 1024
KEY = re.compile(r"^p\d{1,4}$")

Capture = Callable[[str, Path, tuple[str, ...]], None]

_lock = threading.Lock()
_running: set[str] = set()


class ProductError(RuntimeError):
    """Shown to 作者 as-is."""


def root() -> Path:
    return config_dir() / "products"


def _list_path() -> Path:
    return root() / "list.json"


STATUSES = ("live", "demo", "off")  # 已上线 / 演示 / 没上线；空 = 没填


def _url(value: Any) -> str:
    url = str(value or "").strip()
    return f"https://{url}" if url and not re.match(r"^https?://", url, re.IGNORECASE) else url


def _text(item: dict[str, Any], key: str, limit: int) -> str:
    return str(item.get(key) or "").strip()[:limit]


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    views = [v for v in portal.VIEWPORTS if v in (item.get("views") or [])]
    try:
        budget = max(0, int(float(item.get("ad_budget") or 0)))
    except (TypeError, ValueError):
        budget = 0
    return {"key": str(item.get("key") or ""), "name": _text(item, "name", 40), "for": _text(item, "for", 60),
            "url": _url(item.get("url")), "views": views or list(portal.VIEWPORTS),
            "status": item.get("status") if item.get("status") in STATUSES else "",
            "price": _text(item, "price", 200), "pay_channel": _text(item, "pay_channel", 40), "pay_link": _url(item.get("pay_link")),
            "landing": _url(item.get("landing")), "keyword": _text(item, "keyword", 20),
            "ad_plan": _text(item, "ad_plan", 300), "ad_budget": budget}


def items() -> list[dict[str, Any]]:
    try:
        data = json.loads(_list_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("products") if isinstance(data, dict) else None
    return [_clean(r) for r in rows or [] if isinstance(r, dict) and KEY.match(str(r.get("key") or ""))]


def _save(rows: list[dict[str, Any]]) -> None:
    root().mkdir(parents=True, exist_ok=True)
    tmp = _list_path().with_name(".list.json.tmp")
    tmp.write_text(json.dumps({"products": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_list_path())


def get(key: str) -> dict[str, Any]:
    for row in items():
        if row["key"] == key:
            return row
    raise ProductError("没有这个作品")


def save(body: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    """加一个（key 为空）或改一个：名字必填，网址可空（空 = 传截图）。"""
    row = _clean({**body, "key": key or ""})
    if not row["name"]:
        raise ProductError("写个名字")
    if row["url"] and not re.match(r"^https?://[^\s/]+\S*$", row["url"]):
        raise ProductError("网址看不懂")
    with _lock:
        rows = items()
        if key is None:
            used = [int(r["key"][1:]) for r in rows]
            row["key"] = f"p{max(used, default=0) + 1}"
            rows.append(row)
        else:
            idx = next((i for i, r in enumerate(rows) if r["key"] == key), None)
            if idx is None:
                raise ProductError("没有这个作品")
            rows[idx] = row
        _save(rows)
    return row


def remove(key: str) -> None:
    """从清单里拿掉；截过、传过的图留在文件夹里不删。"""
    with _lock:
        rows = items()
        if not any(r["key"] == key for r in rows):
            raise ProductError("没有这个作品")
        _save([r for r in rows if r["key"] != key])


# -- 每条内容带哪个产品（10/9 变现流程板，#590）----------------------------------------
# 「标题和封面」① 里选：带某个产品 / 不带。存在 <config>/products/content.json：{"<选题 id>": "p3"}。
# 发出去的时候描述里加一行这个产品的私信关键词或落地页（copypack.with_product）；产品页「流量入口」读它。


def _tags_path() -> Path:
    return root() / "content.json"


def content_tags() -> dict[int, str]:
    try:
        raw = json.loads(_tags_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(k): str(v) for k, v in (raw.items() if isinstance(raw, dict) else []) if str(k).isdigit() and KEY.match(str(v))}


def tag_content(topic_id: int, key: str | None) -> str | None:
    """这条带哪个产品；key 空 = 不带。清单里没有的产品不收。"""
    with _lock:
        if key and not any(r["key"] == key for r in items()):
            raise ProductError("没有这个产品")
        tags = content_tags()
        if key:
            tags[int(topic_id)] = key
        else:
            tags.pop(int(topic_id), None)
        root().mkdir(parents=True, exist_ok=True)
        tmp = _tags_path().with_name(".content.json.tmp")
        tmp.write_text(json.dumps({str(k): v for k, v in sorted(tags.items())}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_tags_path())
    return key or None


def product_for(topic_id: int) -> dict[str, Any] | None:
    """这条带的那个产品（清单里那一行）；没带、或那个产品已经拿掉了，就是 None。"""
    key = content_tags().get(int(topic_id))
    return next((r for r in items() if r["key"] == key), None) if key else None


# -- 有网址的：每天截一次 ----------------------------------------------------------


def days(key: str) -> list[str]:
    folder = root() / key
    if not KEY.match(key) or not folder.is_dir():
        return []
    return sorted((p.name for p in folder.iterdir() if p.is_dir() and portal.DAY.match(p.name)), reverse=True)


def shot_path(key: str, day: str, variant: str) -> Path | None:
    if not KEY.match(key) or not portal.DAY.match(day) or variant not in portal.VIEWPORTS:
        return None
    path = root() / key / day / f"{variant}.png"
    return path if path.is_file() else None


def _prune(key: str, today: str) -> None:
    cutoff = (date.fromisoformat(today) - timedelta(days=portal.KEEP_DAYS)).isoformat()
    for day in days(key):
        if day < cutoff:
            shutil.rmtree(root() / key / day, ignore_errors=True)


def run_once(key: str, *, capture: Capture = portal.capture_page, today: str | None = None) -> dict[str, Any]:
    row = get(key)
    day = today or portal._today()
    folder = root() / key / day
    folder.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"url": row["url"], "views": row["views"], "at": portal._now()}
    try:
        if not row["url"]:
            raise portal.PortalError("这个作品没填网址")
        for v in portal.VIEWPORTS:  # 这次不截的那种别留着上一回的
            (folder / f"{v}.png").unlink(missing_ok=True)
        capture(row["url"], folder, tuple(row["views"]))
    except portal.PortalError as exc:
        meta["error"] = str(exc)
    portal._write_json(folder / "meta.json", meta)
    _prune(key, day)
    return meta


def start(key: str, *, force: bool = False, background: bool = True, **kw: Any) -> bool:
    """今天还没截、或网址 / 截哪几种换了，就开始截；force = 他点了「重新截」。"""
    try:
        row = get(key)
    except ProductError:
        return False
    if not row["url"]:
        return False
    if not force:
        meta = portal._read_json(root() / key / portal._today() / "meta.json")
        if meta is not None and meta.get("url") == row["url"] and meta.get("views") == row["views"]:
            return False
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def work() -> None:
        try:
            run_once(key, **kw)
        finally:
            with _lock:
                _running.discard(key)

    if background:
        threading.Thread(target=work, name=f"product-{key}", daemon=True).start()
    else:
        work()
    return True


# -- 没网址的：他传截图 -------------------------------------------------------------


def _uploads(key: str) -> Path:
    return root() / key / "uploads"


def uploads(key: str) -> list[str]:
    folder = _uploads(key)
    if not KEY.match(key) or not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in UPLOAD_SUFFIXES)


def upload_path(key: str, name: str) -> Path | None:
    if not KEY.match(key) or name not in uploads(key):
        return None
    return _uploads(key) / name


def add_upload(key: str, filename: str, data: bytes) -> str:
    get(key)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        raise ProductError("只收 png、jpg、webp 图片")
    if not data:
        raise ProductError("这张图是空的")
    if len(data) > MAX_UPLOAD:
        raise ProductError("这张图超过 15 MB 了")
    stem = re.sub(r"[^\w\- ·]+", "-", Path(filename).stem).strip("- .")[:60] or "shot"  # 名字就是图下面那行字
    folder = _uploads(key)
    folder.mkdir(parents=True, exist_ok=True)
    name, n = f"{stem}{suffix}", 2
    while (folder / name).exists():
        name, n = f"{stem}-{n}{suffix}", n + 1
    (folder / name).write_bytes(data)
    return name


def remove_upload(key: str, name: str) -> None:
    path = upload_path(key, name)
    if path is None:
        raise ProductError("没有这张图")
    path.unlink()


# -- 页面 ---------------------------------------------------------------------------


def view(key: str | None = None, day: str | None = None) -> dict[str, Any]:
    rows = items()
    pick = next((r for r in rows if r["key"] == key), rows[0] if rows else None)
    out: dict[str, Any] = {"products": rows, "product": None}
    if pick is None:
        return out
    k = pick["key"]
    all_days = days(k)
    shot_day = day if day in all_days else (all_days[0] if all_days else None)
    shot = None
    if shot_day:
        folder = root() / k / shot_day
        meta = portal._read_json(folder / "meta.json") or {}
        shot = {"day": shot_day, "at": meta.get("at"), "url": meta.get("url"), "error": meta.get("error"),
                "variants": [v for v in portal.VIEWPORTS if (folder / f"{v}.png").is_file()]}
    with _lock:
        running = k in _running
    out["product"] = {**pick, "days": all_days, "shot": shot, "uploads": uploads(k), "running": running}
    return out
