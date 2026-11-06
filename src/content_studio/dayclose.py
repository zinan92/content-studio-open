"""日结：每天结束时，把概览上那一天的数字冻结存档，以后不再改。

10/3 作者：「每天 at the end of the day, take a snapshot and save it somewhere……需要留档」。
以前只存了每条内容的原始读数，概览是每次打开现算的——那一天概览长什么样（各平台触达、近 7 天日均、
每条内容在各平台的累计、出没出摊）没有任何冻结下来的记录。

一天 = 本地（北京）0 点到 24 点（reach.local_day）。每晚 23:55 工作台自己读一次自己的号和各平台
（不碰对标、不开读数小 App），读完马上冻结（kind=live）。错过了（Mac 睡着、服务没开），下次启动时补存
（kind=late）：触达照样准（那天的读数都在），但「各平台累计」是补存那一刻的，不是那天的，所以不存。
上线以前的日子从原始读数重算（kind=rebuilt），同样没有各平台累计。存过的不覆盖。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

CLOSE_AT = time(23, 55)
# 从这天起的日子，错过了算「补存」；更早的是上线前从原始读数重算的
SINCE = date(2026, 10, 3)
KIND_LABEL = {"live": "当天收尾时存的", "late": "补存（当天没赶上收尾）", "rebuilt": "事后从原始读数重算"}


def plan(now: datetime) -> tuple[datetime, date]:
    """下一次收尾什么时候跑、收哪一天：今天 23:55 还没到就是今天，过了就是明天。

    收哪一天在排的时候就定下来——Mac 睡过了半夜再醒，date.today() 已经是第二天，不能拿它当要收的那天。"""
    target = now.date() if now.time() < CLOSE_AT else now.date() + timedelta(days=1)
    return datetime.combine(target, CLOSE_AT, tzinfo=now.tzinfo), target


def on_time(now: datetime, target: date) -> bool:
    """醒来（或等到点）时还在要收的那一天里：能读一次再冻结。过了半夜就不读了——那时的读数算新的一天。"""
    return now.date() == target


def kind_for(day: date, today: date) -> str:
    """不是当天收尾时存的：上线以前的日子是重算，以后的是补存。"""
    return "rebuilt" if day < SINCE else "late"


def hhmm(stamp: str | None) -> str | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return None


def folder(home: Path) -> Path:
    return home / "day-close"


def write_file(home: Path, data: dict[str, Any]) -> Path:
    """另存一份文件：库坏了、换电脑了也还在。一天一个 JSON。"""
    out = folder(home)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{data['day']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
