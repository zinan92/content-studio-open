"""K 线日报 tab data: every watchlist asset as one compact daily card."""
import json
import sqlite3
from pathlib import Path

from content_studio.extras.dailies import kline_board as kb


def _db(path: Path, series: dict[str, list[float]]) -> Path:
    con = sqlite3.connect(path)
    con.execute("create table mvp_candles (source_id text default 'yahoo', instrument_id text, timeframe text, timestamp text, open real, high real, low real, close real)")
    for iid, closes in series.items():
        for i, c in enumerate(closes):
            con.execute("insert into mvp_candles (instrument_id,timeframe,timestamp,open,high,low,close) values (?,?,?,?,?,?,?)", (iid, "1d", f"2026-09-{i + 1:02d}T00:00:00+00:00", c, c + 1, c - 1, c))
        con.execute("insert into mvp_candles (instrument_id,timeframe,timestamp,open,high,low,close) values (?,?,?,?,?,?,?)", (iid, "4h", "2026-09-30T00:00:00+00:00", 9, 9, 9, 9))
    con.commit(); con.close()
    return path


def _manifest(path: Path) -> Path:
    path.write_text(json.dumps({"instruments": [
        {"instrument_id": "WATCH.US.NVDA", "display_name": "英伟达", "display_symbol": "NVDA",
         "metadata": {"registry_market": "US", "registry_memberships": [{"sector_name": "算力"}]}},
        {"instrument_id": "WATCH.CN.A.600900", "display_name": "长江电力", "display_symbol": "600900",
         "metadata": {"registry_market": "CN", "registry_memberships": [{"sector_name": "电力"}]}},
        {"instrument_id": "WATCH.CROSS.GOLD", "display_name": "Gold futures", "display_symbol": "GC=F", "metadata": {}},
        {"instrument_id": "WATCH.CROSS.DXY", "display_name": "DXY", "display_symbol": "DXY", "metadata": {}},
    ]}), encoding="utf-8")
    return path


KLINE_MD = """# 宏观 K 线日报

## 今日结论

**等待** · 美元偏强，风险资产分化。

### 黄金期货（GC=F）
**位置**：位置：日线处于中位，当前收盘位于约40%分位。
**结构**：结构：日线趋势延续，方向偏空。
**综合结论**：黄金日线反弹后转弱。

### 中证红利
**综合结论**：红利指数横盘。
"""


def test_board_groups_macro_first_then_markets(tmp_path: Path) -> None:
    db = _db(tmp_path / "k.db", {"WATCH.US.NVDA": [100, 110], "WATCH.CN.A.600900": [20, 19], "WATCH.CROSS.GOLD": [4000, 4100], "WATCH.CROSS.DXY": [28, 28]})
    (tmp_path / "md").mkdir()
    (tmp_path / "md" / "2026-09-28-kline-daily-newsletter.md").write_text(KLINE_MD, encoding="utf-8")
    (tmp_path / "md" / "2026-09-28-kline-daily-newsletter-unavailable.md").write_text("x", encoding="utf-8")
    b = kb.board(db, _manifest(tmp_path / "m.json"), tmp_path / "md")

    assert [g["label"] for g in b["groups"]] == ["宏观", "A 股", "美股"]
    assert b["count"] == 4 and b["report"] == "2026-09-28"
    assert b["conclusion"] == "等待 · 美元偏强，风险资产分化。"
    macro = {c["id"]: c for c in b["groups"][0]["items"]}
    assert [c["id"] for c in b["groups"][0]["items"]] == ["WATCH.CROSS.DXY", "WATCH.CROSS.GOLD"]  # MACRO_ORDER
    gold = macro["WATCH.CROSS.GOLD"]
    assert gold["name"] == "黄金" and gold["tags"] == ["中位", "趋势 · 偏空"] and gold["note"] == "黄金日线反弹后转弱。"
    assert gold["chg1d"] == 2.5 and gold["close"] == 4100
    nvda = b["groups"][2]["items"][0]
    assert nvda["sector"] == "算力" and nvda["chg1d"] == 10.0
    # daily only; the 4h row must not leak into the line
    assert nvda["closes"] == [100, 110] and "bars" not in nvda


def test_macro_keywords_keep_dividend_away_from_schd() -> None:
    assert kb.macro_key("中证红利") == "DIVIDEND"
    assert kb.macro_key("美股红利 ETF（SCHD）") == "SCHD"


def test_board_survives_missing_inputs(tmp_path: Path) -> None:
    b = kb.board(tmp_path / "none.db", tmp_path / "none.json", tmp_path / "none")
    assert b["count"] == 0 and b["groups"] == [] and b["conclusion"] == ""


def test_asian_session_bars_are_dated_by_session_not_utc() -> None:
    # A-share 09-29 session is stored as 09-28 16:00 UTC (local midnight)
    assert kb.session_day("2026-09-28T16:00:00+00:00") == "2026-09-29"
    assert kb.session_day("2026-09-28T15:00:00+00:00") == "2026-09-29"   # Tokyo / Seoul
    assert kb.session_day("2026-09-29T00:00:00+00:00") == "2026-09-29"   # US, UTC midnight
    assert kb.session_day("2026-09-29") == "2026-09-29"


def test_card_that_missed_todays_update_is_flagged(tmp_path: Path) -> None:
    db = _db(tmp_path / "k.db", {"WATCH.US.NVDA": [100, 110, 120], "WATCH.CN.A.600900": [20, 19]})
    con = sqlite3.connect(db)
    con.execute("insert into mvp_candles (instrument_id,timeframe,timestamp,open,high,low,close) values ('WATCH.US.META','1d','2026-09-01T00:00:00+00:00',5,6,4,5)")
    con.execute("insert into mvp_candles (instrument_id,timeframe,timestamp,open,high,low,close) values ('WATCH.US.META','1d','2026-09-02T00:00:00+00:00',5,6,4,5)")
    con.commit(); con.close()
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"instruments": [
        {"instrument_id": "WATCH.US.NVDA", "display_name": "英伟达", "display_symbol": "NVDA", "metadata": {"registry_market": "US"}},
        {"instrument_id": "WATCH.US.META", "display_name": "Meta", "display_symbol": "META", "metadata": {"registry_market": "US"}},
        {"instrument_id": "WATCH.CN.A.600900", "display_name": "长江电力", "display_symbol": "600900", "metadata": {"registry_market": "CN"}},
    ]}), encoding="utf-8")
    b = kb.board(db, m, tmp_path / "none")
    us = next(g for g in b["groups"] if g["key"] == "US")
    by = {c["symbol"]: c for c in us["items"]}
    assert us["day"] == "2026-09-03" and by["NVDA"]["behind"] is False and by["META"]["behind"] is True
    # a market on a different calendar is judged against its own group, not the global newest
    cn = next(g for g in b["groups"] if g["key"] == "CN")
    assert cn["items"][0]["behind"] is False
