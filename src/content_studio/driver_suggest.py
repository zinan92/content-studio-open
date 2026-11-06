"""「我今天不知道拍什么」：作者 点了这个按钮，才从他自己选题池里挑一条给他，说为什么。

9/29 作者：「选题肯定不能要你来决定，肯定是我自己来决定……除非我点一个 button，表示我今天不知道做什么，
然后你再建议我做什么。」所以只在他点的时候跑；只从他已经放进选题池的里面挑，不编新选题。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable


def build_prompt(cards: list[dict[str, Any]], adjustments: list[str]) -> str:
    lines = "\n".join(f"- id {c['id']}｜{c['title']}｜现在：{c['next']['text']}｜放进来：{str(c.get('created_at') or '')[:10]}" for c in cards)
    adj = "\n".join(f"- {a}" for a in adjustments) or "（没有）"
    return f"""作者 今天不知道拍什么，让你从他自己的选题池里挑一条今天拍。
他的 KPI 是每天准时出摊（抖音发一条口播视频），内容的目的是找到客户（私信关键词「动手」）。

## 他的选题池（只能从这里挑）
{lines}

## 最近一次周复盘定下要改的
{adj}

## 要求
挑一条今天最容易拍完、最可能带来私信的。只输出一个 JSON：{{"topic_id": 数字, "why": "一两句为什么，说人话"}}"""


def suggest(cards: list[dict[str, Any]], adjustments: list[str], *, write_fn: Callable[[str], str]) -> dict[str, Any]:
    raw = write_fn(build_prompt(cards, adjustments))
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ValueError("建议没生成出来，再点一次")
    data = json.loads(match.group(0))
    by_id = {c["id"]: c for c in cards}
    pick = by_id.get(int(data.get("topic_id") or 0))
    if pick is None:
        raise ValueError("建议的那条不在你的选题池里，再点一次")
    return {"topic_id": pick["id"], "title": pick["title"], "why": str(data.get("why") or "")[:200]}
