"""邀请码（10/10 作者：「给我一个码，现在用这个码可以有 5 刀的额度」）。

每个码一笔余额（存美分），每次运行按 tools.PRICE 扣，失败那次退回。
文件里只存码的 sha256，不存明文：发出去的码只在创建那一刻看得到，丢了就再发一个。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any

from ...paths import config_dir

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 去掉 0 O 1 I，念出来、抄下来不会错


def default_path() -> Path:
    return config_dir() / "tool-codes.json"


def normalize(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def digest(code: str) -> str:
    return hashlib.sha256(normalize(code).encode("utf-8")).hexdigest()


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


class CodeError(RuntimeError):
    """说给人听的一句话。"""


class CodeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def issue(self, name: str, cents: int) -> str:
        if cents <= 0:
            raise CodeError("额度要大于 0")
        name = (name or "").strip()
        if not name:
            raise CodeError("给这个码写个名字（发给谁）")
        with self.lock:
            data = self._load()
            while True:
                raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
                code = f"CS-{raw[:4]}-{raw[4:]}"
                if digest(code) not in data:
                    break
            data[digest(code)] = {"name": name, "balance": cents, "granted": cents, "spent": 0, "runs": 0,
                                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "disabled": False}
            self._save(data)
        return code

    def get(self, code_hash: str) -> dict[str, Any] | None:
        with self.lock:
            entry = self._load().get(code_hash)
        return dict(entry) if entry and not entry.get("disabled") else None

    def lookup(self, code: str) -> tuple[str, dict[str, Any]] | None:
        h = digest(code)
        entry = self.get(h)
        return (h, entry) if entry else None

    def charge(self, code_hash: str, cents: int) -> bool:
        with self.lock:
            data = self._load()
            entry = data.get(code_hash)
            if not entry or entry.get("disabled") or entry["balance"] < cents:
                return False
            entry["balance"] -= cents
            entry["spent"] += cents
            entry["runs"] += 1
            entry["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._save(data)
            return True

    def refund(self, code_hash: str, cents: int) -> None:
        with self.lock:
            data = self._load()
            entry = data.get(code_hash)
            if entry:
                entry["balance"] += cents
                entry["spent"] = max(0, entry["spent"] - cents)
                entry["runs"] = max(0, entry["runs"] - 1)
                self._save(data)

    def rows(self) -> list[dict[str, Any]]:
        with self.lock:
            data = self._load()
        return [{"id": h[:8], **e} for h, e in data.items()]

    def _by_id(self, data: dict[str, dict[str, Any]], ident: str) -> str:
        hits = [h for h in data if h.startswith(ident)]
        if len(hits) != 1:
            raise CodeError(f"找不到编号 {ident}（先用 list 看一眼）")
        return hits[0]

    def topup(self, ident: str, cents: int) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            h = self._by_id(data, ident)
            data[h]["balance"] += cents
            data[h]["granted"] += cents
            self._save(data)
            return dict(data[h])

    def set_disabled(self, ident: str, off: bool) -> None:
        with self.lock:
            data = self._load()
            h = self._by_id(data, ident)
            data[h]["disabled"] = off
            self._save(data)
