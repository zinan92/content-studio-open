"""X 后台只读抄数：北京时间每天一次，产物和失败都留在当天目录。"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import logging
import math
import os
from pathlib import Path
import subprocess

BJ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


def number(value: str | None) -> int | float | None:
    text = (value or "").strip().replace(",", "").replace(" ", "")
    if text in {"", "—", "-"}:
        return None
    factor = {"K": 1000, "M": 1000000}.get(text[-1:].upper(), 1)
    try:
        n = float(text[:-1] if factor != 1 else text) * factor
        return (int(n) if n.is_integer() else n) if math.isfinite(n) else None
    except (ValueError, OverflowError):
        return None


def read_day(folder: Path) -> dict:
    folder = Path(folder)
    with (folder / "daily.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"date", "verified_only", "impressions", "new_follows", "unfollows"} <= set(reader.fieldnames or []):
            raise ValueError("daily.csv 缺少必要列")
        daily = []
        for row in reader:
            day = date.fromisoformat((row.get("date") or "").strip()).isoformat()
            verified = number(row.get("verified_only"))
            if verified not in (0, 1):
                raise ValueError("verified_only 必须是 0 或 1")
            daily.append({"date": day, "verified_only": verified,
                          **{key: number(row.get(key)) for key in ("impressions", "new_follows", "unfollows")}})
    if not daily:
        raise ValueError("daily.csv 没有数据")
    content = []
    if (folder / "content.csv").is_file():
        with (folder / "content.csv").open(encoding="utf-8-sig", newline="") as handle:
            # 未规定的文字列原样保留；ID 也保持字符串，避免大整数损失。
            numeric = {"impressions", "bookmarks", "likes", "replies", "reposts", "quotes", "profile_clicks", "verified_only"}
            content = [{k: number(v) if k in numeric else v for k, v in row.items()} for row in csv.DictReader(handle)]
    return {"folder": str(folder), "daily": daily, "content": content}


def latest(root: Path) -> dict | None:
    try:
        folders = sorted(Path(root).iterdir(), reverse=True)
    except OSError:
        return None
    for folder in folders:
        try:
            date.fromisoformat(folder.name)
            if (folder / "error.txt").exists() or ((folder / "attempt.txt").exists() and not (folder / "success.txt").exists()):
                continue
            return read_day(folder)
        except (OSError, ValueError, TypeError, csv.Error):
            continue
    return None


def run_due(root: Path, *, now: datetime | None = None, runner=None) -> bool:
    """同步执行一个 tick；原子 attempt 标记保证重启/并发也不重复扣额度。"""
    now = now or datetime.now(BJ)
    now = now.replace(tzinfo=BJ) if now.tzinfo is None else now.astimezone(BJ)
    if (now.hour, now.minute) < (10, 30):
        return False
    folder = Path(root) / now.date().isoformat()
    claimed = False
    try:
        if (folder / "error.txt").exists() or (folder / "daily.csv").exists():
            return False
        folder.mkdir(parents=True, exist_ok=True)
        spec = Path(root) / "spec.md"
        if not spec.is_file():
            try:
                with (folder / "missing-spec.txt").open("x", encoding="utf-8") as handle:
                    handle.write("spec.md 不存在，跳过")
            except FileExistsError:
                return False
            logger.info("X 后台抄数跳过：spec.md 不存在（%s）", now.date())
            return False
        try:
            with (folder / "attempt.txt").open("x", encoding="utf-8") as handle:
                handle.write(now.isoformat())
        except FileExistsError:
            return False
        claimed = True
        done = (runner or subprocess.run)([
            os.environ.get("CONTENT_STUDIO_CODEX_BIN") or "/opt/homebrew/bin/codex",
            "exec", "-C", str(folder), "-s", "workspace-write", "--skip-git-repo-check", "-o", "last.txt", "-",
        ], cwd=folder, input=spec.read_text(encoding="utf-8"), text=True, capture_output=True, timeout=1800, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"codex 退出码 {done.returncode}：{(done.stderr or '')[-2000:]}")
        read_day(folder)
        (folder / "success.txt").write_text(now.isoformat(), encoding="utf-8")
        return True
    except Exception as exc:  # 后台故障不能退出工作台或打断别的任务
        logger.warning("X 后台抄数失败 %s: %s", now.date(), exc)
        if claimed:
            try:
                (folder / "error.txt").write_text(str(exc), encoding="utf-8")
            except OSError:
                logger.warning("X 后台抄数错误文件写入失败")
        return False


def daily_loop(root: Path, stop_auto, *, runner=None, enabled=lambda: True) -> None:
    while not stop_auto.is_set():
        try:
            if enabled():
                run_due(root, runner=runner)
        except Exception:
            logger.exception("X 后台抄数检查失败")
        stop_auto.wait(60)
