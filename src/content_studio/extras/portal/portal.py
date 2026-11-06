"""门户：GitHub 和个人网站现在长什么样，能不能当好门户（10/6 作者）。

作者：「工作台的 objective 是触达。GitHub 和网站都是为了触达，它不像视频一样需要定期去发，
大部分时候 stationary，就是放在那儿。但我需要长期、经常地看到它现在长什么样，能否扮演好一个门户的角色。」
他要截图，也要帮他判断。

- 截什么：无头浏览器、不带任何登录，打开 profile 里的 me.github / me.site——就是陌生人点开简介链接看到的。
  电脑和手机各截第一屏（从抖音、X 点进来的人大多在手机上）。
- 什么时候截：每天第一次打开那一页时截一次；链接改了也重截；页面上能手动「重新截」。今天截失败了不自动重试，等他点。
- 判断：AI 当一个第一次点进来的陌生人，只看这两张图答五件事（知道是谁、做什么、有没有证据、下一步去哪、是不是活着的），
  再给一句总评和一处最该改的。只根据图里看得到的字，不猜。
- 存哪：<config>/portal/<key>/<日期>/ 下 desktop.png、mobile.png、meta.json、judge.json；留 30 天，能翻以前的样子。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Any, Callable

from ... import conf, llm
from ...paths import config_dir

KEYS = {"github": "GitHub", "site": "网站"}
VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
KEEP_DAYS = 30
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHECKS = (("who", "知道你是谁"), ("what", "知道你做什么"), ("proof", "看到证据"), ("next", "知道下一步去哪"), ("alive", "像是活着的"))
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.0 Mobile/15E148 Safari/604.1")
CLAUDE = "claude"

Capture = Callable[[str, Path], None]
Judge = Callable[[Path, str, str], dict[str, Any]]

_lock = threading.Lock()
_running: set[str] = set()


class PortalError(RuntimeError):
    """Shown to 作者 as-is."""


def root() -> Path:
    return config_dir() / "portal"


def url_for(key: str) -> str:
    links = conf.me_links()
    return links["github"] if key == "github" else links["site"]


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def days(key: str) -> list[str]:
    folder = root() / key
    if not folder.is_dir():
        return []
    return sorted((p.name for p in folder.iterdir() if p.is_dir() and DAY.match(p.name)), reverse=True)


def shot_path(key: str, day: str, variant: str) -> Path | None:
    if key not in KEYS or not DAY.match(day) or variant not in VIEWPORTS:
        return None
    path = root() / key / day / f"{variant}.png"
    return path if path.is_file() else None


# -- capture -------------------------------------------------------------------


def capture_page(url: str, folder: Path, variants: tuple[str, ...] = tuple(VIEWPORTS)) -> None:
    """电脑、手机各截第一屏，不带登录。variants：只截哪几种（作品页里小程序只要手机、交易台只要电脑）。"""
    try:
        from playwright.sync_api import Error as PwError, sync_playwright
    except ImportError as exc:
        raise PortalError("这台机器上没有浏览器组件（playwright），截不了图") from exc
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for variant in variants:
                    w, h = VIEWPORTS[variant]
                    mobile = variant == "mobile"
                    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1,
                                              is_mobile=mobile, has_touch=mobile, locale="zh-CN",
                                              **({"user_agent": MOBILE_UA} if mobile else {}))
                    try:
                        page = ctx.new_page()
                        page.goto(url, wait_until="load", timeout=45_000)
                        try:  # 先读数据再画的页面（工作台自己、交易台）：等接口回来，最多 15 秒
                            page.wait_for_load_state("networkidle", timeout=15_000)
                        except PwError:
                            pass
                        page.wait_for_timeout(2500)  # 字体、图片、进场动画
                        page.screenshot(path=str(folder / f"{variant}.png"))
                    finally:
                        ctx.close()
            finally:
                browser.close()
    except PwError as exc:
        raise PortalError(f"打不开 {url}：{str(exc).splitlines()[0][:160]}") from exc


# -- judge ---------------------------------------------------------------------

PROMPT = """你是一个第一次点进来的陌生人：在抖音或 X 上刷到这个人，点开了他简介里的链接（{label}：{url}）。
下面两张图是你看到的第一屏，先读这两个文件：
- 电脑：{desktop}
- 手机：{mobile}（大多数人是从手机点进来的）

只根据图里看得到的东西判断。看不清就说看不清，不要猜，不要凭你对这个网址的了解补。
回答五件事，每件 ok 是 true / false，note 一句话说你看到了什么（尽量引用图里的原字）：
1. who：5 秒内知道这是谁
2. what：知道他做什么、能帮我什么
3. proof：看到证据（作品、数字、客户、成果）
4. next：知道下一步去哪（关注、私信、联系方式、入口按钮）
5. alive：像是活着的（看得出最近有更新），不是荒废的

再给两句：
- verdict：一句话总评，这一屏能不能当好门户，为什么
- fix：最该改的一处，具体到改哪里、往什么方向改，一句话

只输出一行 JSON，不要别的：
{{"checks":[{{"k":"who","ok":true,"note":"…"}},{{"k":"what","ok":true,"note":"…"}},{{"k":"proof","ok":false,"note":"…"}},{{"k":"next","ok":false,"note":"…"}},{{"k":"alive","ok":true,"note":"…"}}],"verdict":"…","fix":"…"}}"""


def parse_judgement(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise PortalError("判断没回成 JSON")
    try:
        data = json.loads(match.group(0))
    except ValueError:
        raise PortalError("判断回的不是合法 JSON") from None
    got = {str(c.get("k")): c for c in data.get("checks") or [] if isinstance(c, dict)}
    checks = []
    for k, label in CHECKS:
        c = got.get(k)
        if c is None:
            raise PortalError(f"判断少了一项：{label}")
        checks.append({"k": k, "label": label, "ok": c.get("ok") is True, "note": str(c.get("note") or "").strip()[:200]})
    return {"checks": checks, "verdict": str(data.get("verdict") or "").strip()[:300], "fix": str(data.get("fix") or "").strip()[:300]}


def judge_shots(folder: Path, url: str, label: str, *, run: Callable[..., subprocess.CompletedProcess] | None = None) -> dict[str, Any]:
    prompt = PROMPT.format(label=label, url=url, desktop=folder / "desktop.png", mobile=folder / "mobile.png")
    argv = [CLAUDE, "-p", "--model", "opus", "--output-format", "text", "--allowedTools", "Read",
            "--disallowedTools", "Bash Edit Write WebFetch WebSearch NotebookEdit"]
    done = (run or llm.run)(argv, input=prompt, timeout=600, cwd=str(folder))
    if done.returncode != 0:
        raise PortalError(f"判断没跑完：{(done.stderr or done.stdout or '').strip()[-160:]}")
    return parse_judgement(done.stdout)


# -- refresh -------------------------------------------------------------------


def _prune(key: str, today: str) -> None:
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    for day in days(key):
        if day < cutoff:
            shutil.rmtree(root() / key / day, ignore_errors=True)


def run_once(key: str, *, capture: Capture = capture_page, judge: Judge = judge_shots, today: str | None = None) -> dict[str, Any]:
    """截一次、判断一次，写进今天的文件夹。出错也记下来（页面上显示，不自动重试）。"""
    url = url_for(key)
    day = today or _today()
    folder = root() / key / day
    folder.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"url": url, "at": _now()}
    try:
        if not url:
            raise PortalError(f"还没填{KEYS[key]}链接")
        (folder / "judge.json").unlink(missing_ok=True)
        capture(url, folder)
        _write_json(folder / "meta.json", meta)
        try:
            _write_json(folder / "judge.json", judge(folder, url, KEYS[key]))
        except (PortalError, subprocess.TimeoutExpired, OSError) as exc:
            meta["judge_error"] = str(exc) if isinstance(exc, PortalError) else "判断超时或没跑起来"
            _write_json(folder / "meta.json", meta)
    except PortalError as exc:
        meta["error"] = str(exc)
        _write_json(folder / "meta.json", meta)
    _prune(key, day)
    return meta


def start(key: str, *, force: bool = False, background: bool = True, **kw: Any) -> bool:
    """需要的话开始截：今天还没截、或链接换了；force = 他点了「重新截」。已经在截就不再开。"""
    if key not in KEYS or not url_for(key):
        return False
    if not force:
        meta = _read_json(root() / key / _today() / "meta.json")
        if meta is not None and meta.get("url") == url_for(key):
            return False  # 今天截过（成功或失败都算）
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
        threading.Thread(target=work, name=f"portal-{key}", daemon=True).start()
    else:
        work()
    return True


def view(key: str, day: str | None = None) -> dict[str, Any]:
    if key not in KEYS:
        raise PortalError("没有这个门户")
    all_days = days(key)
    pick = day if day in all_days else (all_days[0] if all_days else None)
    shot = None
    if pick:
        folder = root() / key / pick
        meta = _read_json(folder / "meta.json") or {}
        shot = {"day": pick, "at": meta.get("at"), "url": meta.get("url"), "error": meta.get("error"),
                "judge_error": meta.get("judge_error"), "judge": _read_json(folder / "judge.json"),
                "variants": [v for v in VIEWPORTS if (folder / f"{v}.png").is_file()]}
    with _lock:
        running = key in _running
    return {"key": key, "label": KEYS[key], "url": url_for(key), "days": all_days, "shot": shot, "running": running}
