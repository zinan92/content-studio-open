"""页面和接口里传来的日期。"""
from __future__ import annotations

from datetime import date


def parse_day(raw: str | None) -> date:
    """YYYY-MM-DD；不给就是今天。"""
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("日期格式应为 YYYY-MM-DD") from exc
