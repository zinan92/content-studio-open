"""客户主动下载的诊断包。10/6 作者：具体比隐私重要——带原始日志尾巴、完整验收单、出错的任务、设置和 profile，
远程看包就能定位到哪个文件哪一行。只不带登录凭据（cookies、密钥、浏览器登录目录）：排错用不上，zip 走微信。"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile

from . import acceptance, conf, preflight, profile, updater
from .paths import config_dir

LOG_TAIL_BYTES = 2 * 1024 * 1024
ERROR_ROWS = 30
CELL_CHARS = 4000
REPO = Path(__file__).resolve().parents[2]
# 登录凭据：文件名里有这些字的不进包，也不列出内容。
CREDENTIAL_NAME = re.compile(r"cookie|secret|token|credential|wechat-state|\.key$|-chrome$", re.IGNORECASE)
# 日志里偶尔会带请求头：这几种只换成 ***，其他原样。
CREDENTIAL_HEADER = re.compile(r"(?im)^(\s*(?:set-)?cookie\s*:\s*|\s*authorization\s*:\s*).*$")
CREDENTIAL_TEXT = re.compile(r"(?i)(\b[\w-]*(?:token|secret|bogus|sessionid|sid_tt|ttwid|verifyfp|signature|api[_-]?key|password)[\w-]*\s*[:=]\s*)[^\s;,&\"']+")
TOOLS = (("python", [sys.executable, "--version"]), ("claude", ["claude", "--version"]), ("codex", ["codex", "--version"]),
         ("ffmpeg", ["ffmpeg", "-version"]), ("node", ["node", "--version"]), ("git", ["git", "--version"]))


def redact(text: str) -> str:
    return CREDENTIAL_TEXT.sub(r"\1***", CREDENTIAL_HEADER.sub(r"\1***", text))


def log_tail(path: Path, limit: int = LOG_TAIL_BYTES) -> str | None:
    """最后 limit 字节，从第一整行开始。"""
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            raw = stream.read(limit)
    except OSError:
        return None
    if size > limit and b"\n" in raw:
        raw = raw.split(b"\n", 1)[1]
    return redact(raw.decode("utf-8", errors="replace"))


def _run(argv: list[str], cwd: Path | None = None) -> str:
    exe = shutil.which(argv[0]) or argv[0]
    try:
        done = subprocess.run([exe, *argv[1:]], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"跑不起来：{type(exc).__name__}: {exc}"
    return ((done.stdout or "") + (done.stderr or "")).strip()


def tool_versions() -> dict[str, str]:
    return {name: (_run(argv).splitlines() or [""])[0] for name, argv in TOOLS}


def _cell(value: object) -> object:
    return value[:CELL_CHARS] if isinstance(value, str) else value


def database(path: Path) -> dict:
    """只读打开：每张表多少行、settings 全部、带错误字段的表最近 ERROR_ROWS 条出错记录。"""
    if not path.is_file():
        return {"available": False, "path": str(path)}
    out: dict = {"available": True, "path": str(path), "size_bytes": path.stat().st_size, "rows": {}, "settings": {}, "errors": {}}
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return {"available": False, "path": str(path), "error": str(exc)}
    try:
        db.row_factory = sqlite3.Row
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            out["rows"][table] = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            for col in ("error", "last_error", "message"):
                if col in columns:
                    rows = db.execute(f'SELECT rowid AS _rowid, * FROM "{table}" WHERE "{col}" IS NOT NULL AND "{col}" != "" '
                                      f'ORDER BY rowid DESC LIMIT {ERROR_ROWS}').fetchall()
                    if rows:
                        out["errors"][f"{table}.{col}"] = [{k: _cell(row[k]) for k in row.keys()} for row in rows]
        if "settings" in tables:
            for row in db.execute("SELECT key, value FROM settings ORDER BY key"):
                if not CREDENTIAL_NAME.search(row["key"]):
                    out["settings"][row["key"]] = _cell(row["value"])
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    finally:
        db.close()
    return out


def listing(root: Path, depth: int = 2) -> list[dict]:
    """数据目录里有什么、多大、什么时候改的。浏览器登录目录只列名字不往里走。"""
    rows: list[dict] = []

    def walk(folder: Path, level: int) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            try:
                st = child.stat()
            except OSError:
                continue
            rows.append({"path": str(child.relative_to(root)), "dir": child.is_dir(), "size_bytes": None if child.is_dir() else st.st_size,
                         "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")})
            if child.is_dir() and level < depth and not CREDENTIAL_NAME.search(child.name):
                walk(child, level + 1)

    walk(root, 1)
    return rows


def build_bundle(*, root: Path | None = None, logs_dir: Path | None = None, port: int = 8780) -> tuple[str, bytes]:
    root = root or config_dir()
    logs_dir = logs_dir or Path.home() / "Library/Logs/ContentStudio"
    now = datetime.now(timezone.utc)
    try:
        version: dict = updater.status(fetch=False)
    except updater.UpdateError as exc:
        version = {"available": False, "error": str(exc)}
    probe = acceptance.Probe()
    label = conf.value("service.label")
    answering, head = acceptance._service_answering(probe, port)
    profile_path = profile.find_profile()
    texts: dict[str, str] = {
        "git.txt": f"$ git status --short --branch\n{_run(['git', 'status', '--short', '--branch'], REPO)}\n\n"
                   f"$ git log -5 --oneline\n{_run(['git', 'log', '-5', '--format=%h %ad %s', '--date=iso'], REPO)}\n",
        "launchd.txt": _run(["launchctl", "print", f"gui/{os.getuid()}/{label}"]),
    }
    if profile_path and profile_path.is_file():
        texts["profile.yaml"] = redact(profile_path.read_text(encoding="utf-8", errors="replace"))
    for name in ("latest.json",):
        path = root / "acceptance" / name
        if path.is_file():
            texts[f"acceptance/{name}"] = path.read_text(encoding="utf-8", errors="replace")
    if logs_dir.is_dir():
        for path in sorted(logs_dir.glob("*.log")):
            tail = log_tail(path)
            if tail:
                texts[f"logs/{path.name}"] = tail
    for path in sorted((root / "logs").glob("*.log")) if (root / "logs").is_dir() else ():
        tail = log_tail(path, LOG_TAIL_BYTES // 4)
        if tail:
            texts[f"logs/studio-{path.name}"] = tail
    facts = preflight.gather()
    files = {
        "machine.json": {**facts, "checks": [list(row) for row in preflight.check(facts)]},
        "version.json": version,
        "tools.json": tool_versions(),
        "health.json": {"port": port, "service_answering": answering, "head": head, "launchd": acceptance._launchd_state(probe, label),
                        "repo": str(REPO), "python": sys.executable, "profile": str(profile_path) if profile_path else None,
                        "config_dir": str(root), "env": {k: v for k, v in os.environ.items() if k.startswith("CONTENT_STUDIO_") and not CREDENTIAL_NAME.search(k)}},
        "database.json": database(root / "data" / "studio.sqlite3"),
        "files.json": listing(root),
        "manifest.json": {"schema_version": 2, "at": now.isoformat(), "contains": sorted([*texts, "machine.json", "version.json", "tools.json",
                                                                                          "health.json", "database.json", "files.json"]),
                          "excluded": "登录凭据：cookies、密钥、token、浏览器登录目录；日志里的 Cookie / Authorization 值换成 ***",
                          "checks_run": "只读：没有调用 AI、没有更新代码、没有重启服务"},
    }
    data = BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        for name, text in texts.items():
            archive.writestr(name, text)
    return f"content-studio-diagnostics-{now.strftime('%Y%m%dT%H%M%SZ')}.zip", data.getvalue()
