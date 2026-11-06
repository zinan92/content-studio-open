"""真去问平台「现在还能不能用」，而不是看 cookie 文件的日期猜。

2026-09-21 的教训：B 站的 cookie 四个月没更新，按 mtime 判断是「早该过期了」，
实际一问 valid。把能用的通道报成坏的，作者 会跑去做一次毫无必要的扫码登录。

探测要开浏览器或走网络，慢且有频率成本，所以结果缓存 6 小时。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from .paths import config_dir
import subprocess
from typing import Any

CACHE_PATH = config_dir() / "channel-probes.json"
CACHE_SECONDS = 6 * 3600
TIMEOUT_SECONDS = 90


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no cache yet
        return {}


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError:
        pass


def probe(key: str, spec: dict[str, Any], *, force: bool = False, now: datetime | None = None,
          cache_path: Path | None = None, runner: Any = None) -> dict[str, Any] | None:
    """{"ok": bool, "checked_at": str} — 没有配探测命令的通道返回 None。"""
    command = spec.get("probe")
    if not command:
        return None
    cache_file = cache_path or CACHE_PATH
    now = now or datetime.now(timezone.utc)
    cache = _read_cache(cache_file)
    hit = cache.get(key)
    if not force and hit:
        try:
            if now - datetime.fromisoformat(hit["checked_at"]) < timedelta(seconds=CACHE_SECONDS):
                return {**hit, "cached": True}
        except Exception:  # noqa: BLE001 - malformed entry
            pass
    run = runner or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False))
    try:
        done = run(command)
        blob = f"{done.stdout}\n{done.stderr}"
        ok = done.returncode == 0 and str(spec.get("probe_ok", "")) in blob
    except Exception:  # noqa: BLE001 - a probe that cannot run tells us nothing new
        return {**(hit or {"ok": None}), "checked_at": (hit or {}).get("checked_at", now.isoformat(timespec="seconds")), "cached": True, "stale_probe": True}
    result = {"ok": ok, "checked_at": now.isoformat(timespec="seconds")}
    cache[key] = result
    _write_cache(cache_file, cache)
    return {**result, "cached": False}
