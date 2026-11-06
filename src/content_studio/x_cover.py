"""X 图文文章的封面：纯文字、5:2 横幅，不带人脸。

9/24 作者：「X 的封面可能需要单独做一下，不用带人脸的那个。」以前把抖音横版封面（带人像）
塞在正文第一张；X 文章接口其实有单独的 cover_media。这里按文章标题原字出一张：
米白底、左上橙色斜角、特粗斜体标题，最后一行橙色加下划线——和抖音、小红书一个样式。
"""
from __future__ import annotations

import asyncio
import html
from pathlib import Path

from .xhs_cards import ORANGE, title_lines

WIDTH, HEIGHT = 1500, 600


def cover_html(title: str, handle: str = "我的账号") -> str:
    lines = title_lines(title, width=13)
    body = "".join(f'<div class="l{" e" if i == len(lines) - 1 else ""}">{html.escape(line)}</div>' for i, line in enumerate(lines))
    size = 84 if len(lines) <= 2 else 70 if len(lines) == 3 else 60
    return f"""<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}
body{{width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;position:relative;background:linear-gradient(160deg,#fffdf7,#f7f1e3);
  font-family:'Hiragino Sans GB','PingFang SC',sans-serif;color:#141414}}
.c{{position:absolute;left:0;top:0;width:210px;height:170px;background:{ORANGE};clip-path:polygon(0 0,100% 0,0 100%)}}
.c2{{position:absolute;left:0;top:0;width:232px;height:188px;background:linear-gradient(135deg,transparent 0 49%,#fff 49% 51%,transparent 51%)}}
.tail{{position:absolute;right:0;bottom:0;width:190px;height:150px;background:{ORANGE};clip-path:polygon(100% 0,100% 100%,0 100%)}}
.t{{position:absolute;left:150px;right:150px;top:50%;transform:translateY(-50%) skewX(-6deg)}}
.l{{font-size:{size}px;font-weight:900;line-height:1.28;letter-spacing:-1px;white-space:nowrap}}
.l.e{{color:{ORANGE}}}
.u{{height:10px;width:62%;background:{ORANGE};border-radius:6px;margin-top:18px;transform:rotate(-1deg)}}
.h{{position:absolute;left:150px;bottom:40px;font-size:24px;color:#9a9486;letter-spacing:1px}}
</style></head><body><div class="c"></div><div class="c2"></div>
<div class="t">{body}<div class="u"></div></div><div class="h">{html.escape(handle)}</div><div class="tail"></div></body></html>"""


async def _shot(doc: str, out: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            await page.set_content(doc)
            await page.wait_for_timeout(80)
            await page.screenshot(path=str(out), type="jpeg", quality=92)
        finally:
            await browser.close()


def make_cover(title: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_shot(cover_html(title), out))
    return out
