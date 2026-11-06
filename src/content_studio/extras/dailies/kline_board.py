"""K 线日报 tab: every watchlist asset as one compact card with a daily chart.

作者, 2026-09-28: 「就在 AI 日报的右边放一个 K 线日报，放得紧凑一点，同一行放 5 个甚至更多，
稍微往下 scroll 一点，100 多个很快就看完了。」

Data is read-only and local:
  - daily bars from the datafeed store (kline.db, refreshed 08:15)
  - the watchlist manifest for names, markets and sectors
  - today's K 线日报 markdown for the one-line verdict on each macro asset
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

HOME = Path.home()
KLINE_DB = Path(os.environ.get("CS_KLINE_DB", HOME / "park-data" / "market" / "kline.db"))
MANIFEST = Path(os.environ.get("CS_KLINE_MANIFEST", HOME / "park-runtime" / "datafeed" / "configs" / "watchlist_registry_manifest.json"))
KLINE_DIR = Path(os.environ.get("CS_KLINE_DIR", HOME / "notes" / "007_kline daily newsletter"))

# A line needs only closes, so the window can be twice as long for the same payload.
BARS = 120


def session_day(timestamp: str) -> str:
    """Trading-session date of a stored daily bar.

    Asian markets are stored as "session date at local midnight", i.e. the
    previous day 15:00/16:00 UTC, so the raw UTC date is one day early
    (2026-09-30: every A-share card read 09-28 for the 09-29 session).
    """
    text = str(timestamp)
    day = text[:10]
    try:
        hour = int(text[11:13])
    except ValueError:
        return day
    if hour >= 12:
        from datetime import date, timedelta
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    return day

MACRO_ORDER = ["DXY", "SPX", "NDX", "SCHD", "VIX", "GOLD", "SILVER", "WTI", "BTC", "ETH", "HYPE", "SHCOMP", "STAR50", "DIVIDEND", "N225", "KOSPI"]
MACRO_NAMES = {
    "DXY": "美元", "SPX": "标普 500", "NDX": "纳指 100", "SCHD": "美股红利", "VIX": "VIX",
    "GOLD": "黄金", "SILVER": "白银", "WTI": "原油", "BTC": "比特币", "ETH": "以太坊", "HYPE": "HYPE",
    "SHCOMP": "上证指数", "STAR50": "科创 50", "DIVIDEND": "中证红利", "N225": "日经 225", "KOSPI": "KOSPI",
}
# Order matters: 「中证红利」 must win over the bare 「红利」 that means SCHD.
MACRO_KEYWORDS = [
    ("黄金", "GOLD"), ("白银", "SILVER"), ("原油", "WTI"), ("WTI", "WTI"), ("上证红利", "DIVIDEND"), ("中证红利", "DIVIDEND"),
    ("SCHD", "SCHD"), ("红利", "SCHD"), ("上证", "SHCOMP"), ("科创", "STAR50"), ("日经", "N225"), ("KOSPI", "KOSPI"),
    ("比特", "BTC"), ("BTC", "BTC"), ("以太", "ETH"), ("ETH", "ETH"), ("HYPE", "HYPE"), ("美元", "DXY"), ("UUP", "DXY"),
    ("标普", "SPX"), ("SPY", "SPX"), ("纳斯达克", "NDX"), ("纳指", "NDX"), ("QQQ", "NDX"), ("VIX", "VIX"),
]
MARKETS = [("CN", "A 股"), ("HK", "港股"), ("US", "美股"), ("KR", "韩股")]


def macro_key(name: str) -> str | None:
    for kw, key in MACRO_KEYWORDS:
        if kw in name:
            return key
    return None


def load_bars(db: Path, instrument_id: str, limit: int = BARS) -> list[list[float]]:
    """[[open, high, low, close], ...] oldest first, plus the last date via bars_with_date."""
    rows = bars_with_date(db, instrument_id, limit)
    return [r[1:] for r in rows]


def bars_with_date(db: Path, instrument_id: str, limit: int = BARS) -> list[list[Any]]:  # single-instrument helper
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select timestamp, open, high, low, close from mvp_candles "
            "where instrument_id=? and timeframe='1d' order by timestamp desc limit ?",
            (instrument_id, limit),
        ).fetchall()
    finally:
        con.close()
    rows.reverse()
    return [[session_day(t), *(round(float(v), 6) for v in (o, h, l, c))] for t, o, h, l, c in rows if None not in (o, h, l, c)]


def latest_kline_md(folder: Path = KLINE_DIR) -> Path | None:
    if not folder.is_dir():
        return None
    files = [p for p in folder.glob("*-kline-daily-newsletter*.md") if "unavailable" not in p.name]
    return max(files, key=lambda p: (p.name[:10], p.stat().st_mtime)) if files else None


def parse_kline_md(text: str) -> dict[str, Any]:
    """Today's verdict line and per-macro {位置, 结构, 结论} keyed by macro key."""
    out: dict[str, Any] = {"conclusion": "", "assets": {}}
    m = re.search(r"^## 今日结论\s*\n+(.+?)(?:\n\n|\n##|\Z)", text, flags=re.M | re.S)
    if m:
        out["conclusion"] = re.sub(r"\*\*", "", m.group(1)).strip().splitlines()[0]
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        key = macro_key(head)
        if not key or key in out["assets"]:
            continue
        fields = {}
        for label in ("位置", "结构", "综合结论"):
            fm = re.search(rf"\*\*{label}\*\*[:：]\s*(?:{label}[:：])?\s*(.+)", body)
            if fm:
                fields[label] = fm.group(1).strip()
        out["assets"][key] = fields
    return out


def _stats(bars: list[list[Any]]) -> dict[str, Any]:
    if not bars:
        return {"close": None, "chg1d": None, "day": None}
    close = bars[-1][4]
    prev = bars[-2][4] if len(bars) > 1 else None
    chg = round((close / prev - 1) * 100, 2) if prev else None
    return {"close": close, "chg1d": chg, "day": bars[-1][0]}


def _short_tag(text: str) -> str:
    # 「日线处于高位，当前收盘位于…」→「高位」; 「日线趋势延续，方向偏多。」→「趋势 · 偏多」
    for word in ("高位", "中位", "低位"):
        if word in text:
            return word
    parts = [w for w in ("趋势", "震荡", "偏多", "偏空") if w in text]
    return " · ".join(parts)


def all_daily_bars(db: Path, ids: list[str], limit: int = BARS) -> dict[str, list[list[Any]]]:
    """Last `limit` daily bars for every id in ONE connection.

    Opening kline.db (~400 MB) once per instrument made the endpoint take ~14s
    for 107 cards; one connection with per-id indexed lookups is well under a
    second.
    """
    out: dict[str, list[list[Any]]] = {iid: [] for iid in ids}
    if not db.exists() or not ids:
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        # Both indexes lead with source_id, so a bare instrument_id filter scans
        # the whole table. Naming the sources lets every lookup use the index.
        sources = [r[0] for r in con.execute("select distinct source_id from mvp_candles")]
        marks = ",".join("?" * len(sources))
        for iid in ids:
            rows = con.execute(
                f"select timestamp, open, high, low, close from mvp_candles "
                f"where source_id in ({marks}) and instrument_id=? and timeframe='1d' "
                f"order by timestamp desc limit ?",
                (*sources, iid, limit * 3),
            ).fetchall()
            by_day: dict[str, list[Any]] = {}
            for t, o, h, l, c in rows:
                day = session_day(t)
                if day not in by_day and None not in (o, h, l, c):
                    by_day[day] = [day, *(round(float(v), 6) for v in (o, h, l, c))]
            out[iid] = sorted(by_day.values())[-limit:]
    finally:
        con.close()
    return out


_CACHE: dict[str, Any] = {}


def _mtime(path: Path | None) -> float:
    try:
        return path.stat().st_mtime if path else 0.0
    except OSError:
        return 0.0


def board(db: Path = KLINE_DB, manifest: Path = MANIFEST, kline_dir: Path = KLINE_DIR) -> dict[str, Any]:
    """Cached until kline.db, the manifest or today's K-line markdown changes."""
    md = latest_kline_md(kline_dir)
    key = (str(db), str(manifest), str(kline_dir), _mtime(db), _mtime(manifest), str(md), _mtime(md))
    if _CACHE.get("key") == key:
        return _CACHE["value"]
    value = _build(db, manifest, kline_dir)
    _CACHE.update(key=key, value=value)
    return value


def _build(db: Path, manifest: Path, kline_dir: Path) -> dict[str, Any]:
    try:
        instruments = json.loads(manifest.read_text(encoding="utf-8")).get("instruments", [])
    except (OSError, json.JSONDecodeError):
        instruments = []
    md_path = latest_kline_md(kline_dir)
    parsed = parse_kline_md(md_path.read_text(encoding="utf-8")) if md_path else {"conclusion": "", "assets": {}}

    macros: dict[str, dict] = {}
    stocks: list[dict] = []
    series = all_daily_bars(db, [inst.get("instrument_id", "") for inst in instruments])
    for inst in instruments:
        iid = inst.get("instrument_id", "")
        rows = series.get(iid, [])
        card = {
            "id": iid,
            "symbol": inst.get("display_symbol") or iid.split(".")[-1],
            # Closes only: at card size the four OHLC points are not readable
            # (作者, 2026-09-30), so the card draws a line.
            "closes": [r[4] for r in rows],
            **_stats(rows),
        }
        if iid.startswith("WATCH.CROSS."):
            key = iid.split(".")[-1]
            fields = parsed["assets"].get(key, {})
            card.update(
                name=MACRO_NAMES.get(key, inst.get("display_name") or key),
                tags=[t for t in (_short_tag(fields.get("位置", "")), _short_tag(fields.get("结构", ""))) if t],
                note=fields.get("综合结论", ""),
            )
            macros[key] = card
        else:
            meta = inst.get("metadata") or {}
            mem = (meta.get("registry_memberships") or [{}])[0] or {}
            card.update(
                name=inst.get("display_name") or card["symbol"],
                market=meta.get("registry_market") or iid.split(".")[1],
                sector=mem.get("sector_name") or "",
                tags=[], note="",
            )
            stocks.append(card)

    groups = []
    macro_cards = [macros[k] for k in MACRO_ORDER if k in macros] + [c for k, c in macros.items() if k not in MACRO_ORDER]
    if macro_cards:
        groups.append({"key": "macro", "label": "宏观", "items": macro_cards})
    for code, label in MARKETS + [(m, m) for m in sorted({s["market"] for s in stocks} - {c for c, _ in MARKETS})]:
        items = sorted((s for s in stocks if s["market"] == code), key=lambda s: (s["sector"], -abs(s["chg1d"] or 0)))
        if items:
            groups.append({"key": code, "label": label, "items": items})

    days = [c["day"] for g in groups for c in g["items"] if c.get("day")]
    newest = max(days) if days else None
    for g in groups:
        g_days = [c["day"] for c in g["items"] if c.get("day")]
        g["day"] = max(g_days) if g_days else None
        for c in g["items"]:
            # behind its own group's newest session = this card missed an update
            c["behind"] = bool(c.get("day") and g["day"] and c["day"] < g["day"])
    return {
        "day": newest,
        "report": md_path.name[:10] if md_path else None,
        "conclusion": parsed["conclusion"],
        "count": sum(len(g["items"]) for g in groups),
        "groups": groups,
    }
