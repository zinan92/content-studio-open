"""小红书：用 作者自己的 Chrome 打开「笔记数据」页，截这个窗口，让模型认出每篇的「观看」。

视频号试过不行（9/26）：视频号助手的登录只活在登录的那个标签页里，新开标签页、甚至刷新一下就跳回
登录页，没法每天读，继续手填。

9/26 作者 问截图会不会触发小红书风控。截图发生在浏览器外面，网站看不到；会被看出来的是
自动化浏览器（Playwright 这类）。所以这里不用自动化浏览器，也不碰登录：只让 Chrome 打开一个
网址（和点书签一样），等它加载完，截它的窗口，然后关掉我们开的那个标签页。

每一步都可能拿到垃圾（屏幕锁着、Chrome 没在最前、跳到登录页、没有录屏权限时截出来只有桌面），
所以写之前先核对：标签页还是我们开的那个、网址没跳走、图里是「我的账号」的「笔记数据」。
任何一步不对就什么都不写，记一条「没截到」。截图用完就删，不留盘。

表格默认只列近 30 天首发的笔记、每页 10 条。一篇笔记掉出表格，只是不再有新快照，
不会被当成观看数下降（reach.daily_views 只看有快照的日子）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

from .platform_stats import NotConnected, Post, StatsError
from . import llm

XHS_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
ACCOUNT = "我的账号"
CLAUDE = shutil.which("claude") or str(Path("~/.local/bin/claude").expanduser())
TMP_ROOT = Path("~/.config/content-studio/tmp").expanduser()
LOAD_WAIT = 20
SETTLE = 4

Run = Callable[..., subprocess.CompletedProcess]


def _osa(script: str, run: Run) -> str:
    try:
        done = run(["osascript", "-e", script], capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        # 第一次从后台控制 Chrome，系统会弹框问要不要允许；没人点就一直等。
        raise StatsError("控制 Chrome 没反应：可能在等你点「允许」（系统设置 → 隐私与安全性 → 自动化）") from None
    if done.returncode != 0:
        detail = (done.stderr or "").strip()
        if "-1743" in detail or "Not authorized" in detail:
            raise StatsError("没有控制 Chrome 的权限：系统设置 → 隐私与安全性 → 自动化，允许它控制 Google Chrome")
        raise StatsError(f"控制 Chrome 出错：{detail[-160:]}")
    return (done.stdout or "").strip()


def screen_locked(run: Run = subprocess.run) -> bool:
    out = run(["ioreg", "-n", "Root", "-d1"], capture_output=True, text=True, timeout=10, check=False).stdout or ""
    return bool(re.search(r'"CGSSessionScreenIsLocked"\s*=\s*Yes', out))


def front_app(run: Run = subprocess.run) -> str:
    front = (run(["lsappinfo", "front"], capture_output=True, text=True, timeout=10, check=False).stdout or "").strip()
    info = run(["lsappinfo", "info", "-only", "name", front], capture_output=True, text=True, timeout=10, check=False).stdout or ""
    match = re.search(r'"(?:LSDisplayName|name)"\s*=\s*"([^"]+)"', info)
    return match.group(1) if match else ""


def capture_page(url: str, out: Path, *, run: Run = subprocess.run, sleep: Callable[[float], None] = time.sleep) -> None:
    """打开 → 等加载 → 核对还是我们的标签页在最前 → 只截 Chrome 窗口 → 关掉我们开的标签页。"""
    if screen_locked(run):
        raise StatsError("屏幕锁着，今天没截")
    ids = _osa(f'''tell application "Google Chrome"
  activate
  if (count of windows) = 0 then make new window
  set w to front window
  set t to make new tab at end of tabs of w with properties {{URL:"{url}"}}
  return (id of t as text) & "," & (id of w as text)
end tell''', run)
    try:
        tab, win = (int(x) for x in ids.split(","))
    except ValueError:
        raise StatsError(f"Chrome 没告诉我开的是哪个标签页：{ids[:60]}") from None
    def ask(expr: str) -> str:
        # Chrome 的 id 超过 AppleScript 整数上限，写成字面量会变成小数、找不到；按文字比对找回来。
        return _osa(f'''tell application "Google Chrome"
  set w to missing value
  set t to missing value
  repeat with ww in windows
    if (id of ww as text) is "{win}" then
      set w to ww
      repeat with tt in tabs of ww
        if (id of tt as text) is "{tab}" then set t to tt
      end repeat
    end if
  end repeat
  if t is missing value then return "gone"
  {expr}
end tell''', run)

    try:
        for _ in range(LOAD_WAIT):
            sleep(1)
            if ask("return (loading of t) as text") == "false":
                break
        sleep(SETTLE)  # 表格是加载完再画的
        landed = ask("return URL of t")
        if not landed.startswith(url):
            raise NotConnected(f"Chrome 里没登录，打开后跳到了 {landed[:60]}")
        active = ask("return (id of active tab of w as text) & \",\" & (index of w as text)")
        if active != f"{tab},1" or front_app(run) != "Google Chrome":
            raise StatsError("截图那一刻 Chrome 不在最前（你可能正在用电脑），今天跳过")
        bounds = ask("return bounds of w")
        x1, y1, x2, y2 = (int(v) for v in bounds.split(", "))
        done = run(["screencapture", "-x", "-R", f"{x1},{y1},{x2 - x1},{y2 - y1}", str(out)], capture_output=True, text=True, timeout=30, check=False)
        if done.returncode != 0 or not out.is_file():
            raise StatsError("截图失败：系统设置 → 隐私与安全性 → 录屏，允许它截屏")
    finally:
        try:
            ask("close t")
        except StatsError:
            pass


PROMPT = """读这张截图：{path}

它应该是小红书「创作服务平台」的「笔记数据」页，右上角账号是「{account}」。
只根据图里看得到的字回答，看不清就说看不清，不要猜数字。

只输出一行 JSON，不要别的：
{{"page_ok": true/false, "account": "右上角的账号名", "tab": "当前选中的标签名", "notes": [{{"title": "笔记标题（图里显示的样子）", "published": "发布于后面的时间，如 2026-09-24 14:53", "views": 「观看」那一列的整数}}]}}
不是这个页面、没登录、页面还在加载，page_ok 就是 false，notes 为空。"""


def _ask_model(prompt: str, image: Path, run: Run) -> dict[str, Any]:
    argv = [CLAUDE, "-p", "--model", "sonnet", "--output-format", "text", "--allowedTools", "Read",
            "--disallowedTools", "Bash Edit Write WebFetch WebSearch NotebookEdit"]
    if run is subprocess.run:  # 真跑：按后台设置走 Codex 或 Claude；测试注入的 run 原样调用
        done = llm.run(argv, input=prompt, timeout=300, cwd=str(image.parent))
    else:
        done = run(argv, input=prompt, capture_output=True, text=True, timeout=300, check=False, cwd=str(image.parent))
    match = re.search(r"\{.*\}", done.stdout or "", re.S)
    if done.returncode != 0 or not match:
        raise StatsError(f"模型没认出来：{(done.stderr or done.stdout or '').strip()[-160:]}")
    try:
        return json.loads(match.group(0))
    except ValueError:
        raise StatsError("模型返回的不是 JSON") from None


def read_numbers(image: Path, *, run: Run = subprocess.run, account: str = ACCOUNT) -> list[Post]:
    data = _ask_model(PROMPT.format(path=image, account=account), image, run)
    if not data.get("page_ok") or data.get("account") != account or data.get("tab") != "笔记数据":
        raise StatsError(f"截到的不是笔记数据页（账号：{data.get('account')}，标签：{data.get('tab')}）")
    posts = []
    for note in data.get("notes") or []:
        title, published, views = str(note.get("title") or "").strip(), str(note.get("published") or "").strip(), note.get("views")
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", published) or not isinstance(views, int) or views < 0:
            raise StatsError(f"有一行没认清：{title[:20]}")
        # 表格里没有笔记 id、标题会被截断：用发布时间 + 标题开头当 id。
        posts.append({"post_id": f"{published}|{title.rstrip('.…')[:12]}", "title": title, "published_at": published.replace(" ", "T") + ":00+08:00", "views": views})
    return posts


def _with_screenshot(url: str, name: str, read: Callable[[Path], Any], run: Run, capture: Callable[[str, Path], None] | None) -> Any:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(TMP_ROOT, 0o700)
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmp:
        image = Path(tmp) / name
        (capture or (lambda u, out: capture_page(u, out, run=run)))(url, image)
        return read(image)  # 出了 with，截图连目录一起删


def xiaohongshu_posts(*, run: Run = subprocess.run, capture: Callable[[str, Path], None] | None = None,
                      read: Callable[[Path], list[Post]] | None = None, account: str | None = None) -> list[Post]:
    return _with_screenshot(XHS_URL, "xhs.png", read or (lambda p: read_numbers(p, run=run, account=account or ACCOUNT)), run, capture)


xiaohongshu_posts.retry = False  # 每试一次就弹一次 Chrome：失败了当天不再试
