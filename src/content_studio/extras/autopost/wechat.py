"""公众号官方接口：换令牌，以及「现在到底能不能用」。

只用微信自己的开放接口（appid + secret 换 access_token），不是绕过任何限制。
2026-09-21 排查记录：报 40164 是这台机器的出口 IP 不在后台白名单里，报 40125 是
AppSecret 不对——两者都不是「公众号被封了」，错误码要分清楚，否则会去修错的东西。

令牌每天有获取次数上限，所以状态检测带缓存：工作台每次渲染页面都去问一次微信，
几天就能把配额用光。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import os
from pathlib import Path

from ...paths import config_dir
import time
from typing import Any
import urllib.parse
import urllib.request

SECRETS_PATH = Path(os.environ.get("CONTENT_STUDIO_SECRETS", "~/.config/content-studio/secrets.yaml")).expanduser()
CACHE_PATH = config_dir() / "wechat-state.json"
CACHE_SECONDS = 6 * 3600
TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"

# 微信的错误码说的是完全不同的三件事，混在一起会把人支去修错的地方。
ERRORS = {
    40164: ("ip", "这台机器的 IP 不在公众号后台的白名单里"),
    40125: ("secret", "AppSecret 不对，去后台重置一个"),
    40013: ("appid", "AppID 不对"),
    45009: ("quota", "今天的接口调用次数用完了"),
}


def seen_ip(payload: dict[str, Any]) -> str | None:
    """40164 时微信会说它看到的出口 IP（「invalid ip 1.2.3.4 ipv6 …」），把它交给 作者 去加白名单。"""
    m = re.search(r"invalid ip ([0-9.]+)", str(payload.get("errmsg") or ""))
    return m.group(1) if m else None


def explain(payload: dict[str, Any]) -> tuple[str, str]:
    code = payload.get("errcode")
    reason, note = ERRORS.get(code, ("error", f"微信返回 {code} {payload.get('errmsg')}"))
    ip = seen_ip(payload) if code == 40164 else None
    if ip:
        note = f"{note}：微信看到的是 {ip}，到公众号后台 → 设置与开发 → 开发接口管理 → IP 白名单 里加上它"
    return reason, note


def load_credentials(path: Path | None = None) -> dict[str, str]:
    try:
        import yaml

        data = yaml.safe_load((path or SECRETS_PATH).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - missing or malformed means unconfigured
        return {}
    wx = (data.get("wechat") or {}) if isinstance(data, dict) else {}
    return {k: str(wx[k]).strip() for k in ("appid", "secret") if str(wx.get(k) or "").strip()}


def fetch_token(creds: dict[str, str], *, opener: Any = None) -> dict[str, Any]:
    """{"ok": bool, "reason": str, "note": str} — 不返回令牌本身，调用方不需要它。"""
    if not creds.get("appid") or not creds.get("secret"):
        return {"ok": False, "reason": "unconfigured", "note": "还没有 appid / secret"}
    query = urllib.parse.urlencode({"grant_type": "client_credential", **{"appid": creds["appid"], "secret": creds["secret"]}})
    send = opener or urllib.request.urlopen
    try:
        with send(f"{TOKEN_URL}?{query}", timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 - network problems are not credential problems
        return {"ok": False, "reason": "network", "note": f"连不上微信：{exc}"}
    if payload.get("access_token"):
        return {"ok": True, "reason": "", "note": "官方接口可用"}
    reason, note = explain(payload)
    return {"ok": False, "reason": reason, "note": note}


def state(*, force: bool = False, now: datetime | None = None, opener: Any = None, cache_path: Path | None = None) -> dict[str, Any]:
    cache = cache_path or CACHE_PATH
    now = now or datetime.now(timezone.utc)
    if not force:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            checked = datetime.fromisoformat(cached["checked_at"])
            if now - checked < timedelta(seconds=CACHE_SECONDS):
                return {**cached, "cached": True}
        except Exception:  # noqa: BLE001 - no cache yet, or unreadable
            pass
    result = {**fetch_token(load_credentials(), opener=opener), "checked_at": now.isoformat(timespec="seconds")}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.chmod(cache, 0o600)
    except OSError:
        pass
    return {**result, "cached": False}
