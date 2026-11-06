"""抖音作品列表：接口被拒时，用本机真的 Chrome 打开主页，读页面自己拿到的列表。

9/27 起抖音拒绝了 /aweme/v1/web/aweme/post/ 的签名请求（403，资料接口还通）。页面自己的
请求能过，所以这里不签名：开一个独立的 Chrome 配置（不碰 作者 平时用的 Chrome），带上
登录 cookies 打开主页，把页面收到的作品列表原样收下来；往下滚一次就是下一页。

没装 Google Chrome 的电脑（销售的 Trial 机器）就用 playwright 自带的 Chromium，同样能拿到列表。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from .paths import config_dir

POSTS_PATH = "/aweme/v1/web/aweme/post/"
PROFILE_DIRNAME = "douyin-chrome"
CHROMIUM_PROFILE_DIRNAME = "douyin-chromium"  # 两种浏览器的配置文件不通用
LAUNCH_ARGS = {
    "headless": True, "locale": "zh-CN", "viewport": {"width": 1280, "height": 900},
    "args": ["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
    "ignore_default_args": ["--enable-automation"],
}
INSTALL_HINT = "终端里在工作台目录运行 .venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium"
_LOCK = threading.Lock()  # 一个 Chrome 配置同一时间只能开一次


class BrowserUnavailable(RuntimeError):
    """这台电脑开不了读作品用的浏览器；消息就是给人看的修法。"""


class Pages:
    """把页面收到的每一页作品攒起来，按 aweme_id 去重。"""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.pages = 0
        self.has_more = True
        self._seen: set[str] = set()

    def add(self, body: dict[str, Any]) -> None:
        self.pages += 1
        for post in body.get("aweme_list") or []:
            aid = str(post.get("aweme_id") or "")
            if aid and aid not in self._seen:
                self._seen.add(aid)
                self.posts.append(post)
        self.has_more = bool(body.get("has_more"))


def _cookie_list(cookies: dict[str, str]) -> list[dict[str, Any]]:
    return [{"name": k, "value": v, "domain": ".douyin.com", "path": "/"} for k, v in cookies.items() if k and v]


async def _launch(pw: Any) -> Any:
    """先用本机 Google Chrome；没装就退到 playwright 自带的 Chromium。"""
    try:
        return await pw.chromium.launch_persistent_context(
            str(config_dir() / PROFILE_DIRNAME), channel="chrome", **LAUNCH_ARGS)
    except Exception:  # noqa: BLE001 - 没装 Chrome 时 playwright 报的是普通 Error
        pass
    try:
        return await pw.chromium.launch_persistent_context(str(config_dir() / CHROMIUM_PROFILE_DIRNAME), **LAUNCH_ARGS)
    except Exception as exc:  # noqa: BLE001
        raise BrowserUnavailable(f"没有能用的浏览器（Google Chrome 和自带 Chromium 都打不开）：{INSTALL_HINT}") from exc


async def user_posts(sec_uid: str, cookies: dict[str, str], *, pages: int, settle: float = 4.0,
                     timeout: float = 90.0, first_wait: float = 40.0) -> Pages:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BrowserUnavailable(f"这台电脑没装浏览器组件 playwright：{INSTALL_HINT}") from exc

    got = Pages()
    arrived = asyncio.Event()

    async def on_response(response: Any) -> None:
        if POSTS_PATH not in response.url or response.status != 200:
            return
        try:
            body = await response.json()
        except Exception:  # noqa: BLE001 - a non-JSON answer is just not a page
            return
        got.add(body)
        arrived.set()

    async with async_playwright() as pw:
        ctx = await _launch(pw)
        try:
            await ctx.add_cookies(_cookie_list(cookies))
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.on("response", on_response)
            await page.goto(f"https://www.douyin.com/user/{sec_uid}", wait_until="domcontentloaded", timeout=timeout * 1000)
            # 第一页：新开的 Chrome 配置第一次加载会慢，多等一会儿
            try:
                await asyncio.wait_for(arrived.wait(), timeout=first_wait)
            except asyncio.TimeoutError:
                return got
            idle = 0
            while got.pages < pages and got.has_more and idle < 4:
                arrived.clear()
                # 滚到底才会要下一页；页面有时还没排好，滚轮和 End 键都来一下，没来就再滚
                await page.mouse.move(640, 600)
                await page.mouse.wheel(0, 20000)
                await page.keyboard.press("End")
                try:
                    await asyncio.wait_for(arrived.wait(), timeout=settle * 3)
                    idle = 0
                except asyncio.TimeoutError:
                    idle += 1
        finally:
            await ctx.close()
    return got


def fetch_user_posts(sec_uid: str, cookies: dict[str, str], *, pages: int, tries: int = 2) -> Pages:
    """同步入口（在已有事件循环外调用）。第一次没拿到就再开一次。"""
    with _LOCK:
        got = Pages()
        for _ in range(tries):
            got = asyncio.run(user_posts(sec_uid, cookies, pages=pages))
            if got.posts:
                break
        return got
