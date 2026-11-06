"""装机验收（10/6 作者 定的三道闸里的第 2 道）：一条命令，从机器一直测到界面，出一张红绿验收单。

    content-studio acceptance            # 全套：机器 → 安装 → 配置 → 通道（真叫一次 claude / codex）→ 主线（沙盒）→ 界面 → 交接
    content-studio acceptance --quick    # 不叫 AI、不开浏览器

七层，每层一行红绿；红的写清楚「客户该点哪里」，不写技术错误。主线那层在一个临时目录里跑，客户的真数据一个字不碰；
任何一层都不发布、不评论、不操作账号。验收单存成 HTML 和 JSON（config_dir()/acceptance/），诊断包也带上它。
测不了、只能人做的（扫码登录、一起真发一条、重启后再跑一次、签字）列在第 7 层，打 ○。
"""
from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import conf, llm
from .paths import config_dir

LAYERS = {1: "机器", 2: "安装", 3: "配置", 4: "通道", 5: "主线", 6: "界面", 7: "交接"}
ROUTES = ("today", "input", "radar", "report", "board", "platform/douyin", "platform/channels", "platform/xiaohongshu", "platform/x",
          "platform/others", "summary", "mine", "swipe", "consults", "settings", "positioning")
REQUIRED_PACKAGES = (("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("yaml", "pyyaml"), ("httpx", "httpx"), ("markdown", "markdown"),
                     ("PIL", "pillow"), ("multipart", "python-multipart"))
OPTIONAL_PACKAGES = (("mlx_whisper", "转写（mlx-whisper）"), ("playwright", "浏览器组件（playwright）"), ("huggingface_hub", "模型下载（huggingface_hub）"))
WHISPER_MODEL = "models--mlx-community--whisper-large-v3-turbo"
AI_PROMPT = "只回复一个字：好"
HANDOVER = (
    ("客户自己扫码登录各平台", "B 站、YouTube、视频号在各平台页点「后台」登录；公众号、X 的密钥由你陪着填"),
    ("和客户一起真发一条", "发布那一下工作台永远不自己按：他点，你看"),
    ("重启一次电脑，再跑 acceptance --quick", "看服务自己起来了、登录还在"),
    ("客户在验收单上签字", "验收单在 ~/.config/content-studio/acceptance/ 里"),
)


@dataclass
class Item:
    layer: int
    name: str
    ok: bool | None          # None = 没测 / 人做（○）
    note: str = ""
    fix: str = ""            # 红的：客户该点哪里
    hard: bool = True        # 软项红了不算验收失败


@dataclass
class Report:
    at: str
    quick: bool
    items: list[Item] = field(default_factory=list)
    saved: str = ""

    def failed(self) -> list[Item]:
        return [i for i in self.items if i.hard and i.ok is False]

    def passed(self) -> bool:
        return not self.failed() and not self.pending()

    def pending(self) -> list[Item]:
        return [i for i in self.items if i.hard and i.ok is None]

    def layer_state(self, layer: int) -> str:
        mine = [i for i in self.items if i.layer == layer]
        if any(i.hard and i.ok is False for i in mine):
            return "fail"
        if any(i.ok is False for i in mine):
            return "warn"
        if not mine or any(i.hard and i.ok is None for i in mine) or all(i.ok is None for i in mine):
            return "skip"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "quick": self.quick, "passed": self.passed(),
                "status": "failed" if self.failed() else "incomplete" if self.pending() else "checked",
                "handover_complete": False, "items": [asdict(i) for i in self.items], "saved": self.saved}


@dataclass
class Probe:
    """能换掉的外部动作：测试里换成假的，真机上用真的。"""
    which: Callable[[str], str | None] = shutil.which
    find_spec: Callable[[str], Any] = importlib.util.find_spec
    run: Callable[..., Any] = subprocess.run
    get: Callable[[str, float], Any] = None  # type: ignore[assignment]
    home: Path = Path.home()

    def __post_init__(self) -> None:
        if self.get is None:
            self.get = http_get


def http_get(url: str, timeout: float = 5.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - 只打本机
        return json.loads(resp.read().decode("utf-8"))


# ---------------- 1 机器 ----------------
def layer_machine(facts: dict[str, Any] | None = None) -> list[Item]:
    from . import preflight

    rows = preflight.check(facts if facts is not None else preflight.gather())
    return [Item(1, name, bool(ok), note, "" if ok else note, hard) for name, ok, hard, note in rows]


# ---------------- 2 安装 ----------------
def layer_install(*, port: int, label: str, probe: Probe | None = None, restart: bool = False) -> list[Item]:
    p = probe or Probe()
    out: list[Item] = []
    v = sys.version_info
    out.append(Item(2, "Python", v >= (3, 11), f"{v.major}.{v.minor}", "把验收单交给安装负责人，用安装目录的 .venv/bin/python 运行"))
    missing = [pip for mod, pip in REQUIRED_PACKAGES if p.find_spec(mod) is None]
    out.append(Item(2, "依赖包", not missing, f"{len(REQUIRED_PACKAGES) - len(missing)}/{len(REQUIRED_PACKAGES)}",
                    f"缺 {'、'.join(missing)}：终端里 {shlex.quote(sys.executable)} -m pip install {' '.join(missing)}" if missing else ""))
    for mod, label_ in OPTIONAL_PACKAGES:
        have = p.find_spec(mod) is not None
        out.append(Item(2, label_, have, "有" if have else "没装", "" if have else f"终端里 {shlex.quote(sys.executable)} -m pip install {mod.replace('_', '-')}", hard=False))
    on_codex = llm.backend() == "codex"
    for tool, hard, fix in (("ffmpeg", True, "brew install ffmpeg"), ("ffprobe", True, "brew install ffmpeg"), ("git", True, "装 Xcode 命令行工具"),
                            ("claude", not on_codex, "装 Claude Code 并登录（终端里 claude）" if not on_codex else "后台 AI 用的是 Codex，可以不装"),
                            ("codex", on_codex, "brew install codex，再在终端里 codex login：后台 AI 和封面都靠它" if on_codex else "没装就不出封面、不配图"),
                            ("node", False, "brew install node")):
        have = bool(p.which(tool))
        out.append(Item(2, tool, have, "有" if have else "没有", "" if have else fix, hard))
    chromium = any(d.name.startswith("chromium") for d in (p.home / "Library/Caches/ms-playwright").glob("*")) if (p.home / "Library/Caches/ms-playwright").is_dir() else False
    out.append(Item(2, "浏览器组件", chromium, "有" if chromium else "没装", "" if chromium else "终端里 .venv/bin/python -m playwright install chromium", hard=False))
    model = (p.home / ".cache/huggingface/hub" / WHISPER_MODEL).is_dir()
    out.append(Item(2, "转写模型", model, "有" if model else "没下", "" if model else "把验收单交给安装负责人，补装转写模型（要 1.5GB）", hard=False))
    try:
        from . import updater

        for d in updater.deps():
            out.append(Item(2, f"依赖仓库 {d['name']}", bool(d["installed"]), d["feature"], "" if d["installed"] else "设置 → 版本 → 依赖，把缺失项和诊断包交给安装负责人补齐", hard=bool(d["required"])))
    except Exception as exc:  # noqa: BLE001 - 读不到清单也要报
        out.append(Item(2, "依赖清单", False, str(exc)[:80], "deploy.json 读不了：重装", hard=False))
    answering, version = _service_answering(p, port)
    out.append(Item(2, f"后台服务 :{port}", answering, version if answering else "没应答", "" if answering else f"终端里 launchctl kickstart -k gui/$(id -u)/{label}；还不行就看 ~/Library/Logs/ContentStudio/content-studio.stderr.log"))
    state = _launchd_state(p, label)
    out.append(Item(2, "开机常驻", state is not None and state.get("running", False), (f"pid {state['pid']} · 起过 {state['runs']} 次" if state and state.get("running") else "launchd 里没有这个服务") if state is not None else "读不到 launchd",
                    "" if state and state.get("running") else "把验收单交给安装负责人修复后台服务；已有安装不重跑装机脚本", hard=False))
    plists = list((p.home / "Library/LaunchAgents").glob("*daily-sync*.plist")) if (p.home / "Library/LaunchAgents").is_dir() else []
    out.append(Item(2, "每日同步", bool(plists), plists[0].name if plists else "没装", "" if plists else "终端里 python3 -m content_studio write-schedule，再 launchctl load 它", hard=False))
    if restart and state and state.get("running"):
        out.append(_restart_once(p, port, label, state))
    else:
        out.append(Item(2, "杀一次自己起来", None, "没试：加 --restart 才会杀一次服务看它自己起来", hard=False))
    return out


def _service_answering(p: Probe, port: int) -> tuple[bool, str]:
    try:
        d = p.get(f"http://127.0.0.1:{port}/api/update?fetch=false", 5.0)
        head = (d or {}).get("head") or {}
        return True, f"{head.get('date', '')} · {head.get('hash', '')}".strip(" ·")
    except Exception:  # noqa: BLE001
        return False, ""


def _launchd_state(p: Probe, label: str) -> dict[str, Any] | None:
    try:
        r = p.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return {"running": False}
    pid = re.search(r"pid = (\d+)", text)
    runs = re.search(r"runs = (\d+)", text)
    return {"running": "state = running" in text, "pid": int(pid.group(1)) if pid else None, "runs": int(runs.group(1)) if runs else None}


def _restart_once(p: Probe, port: int, label: str, before: dict[str, Any]) -> Item:
    try:
        result = p.run([str(Path(conf.value("service.restart")).expanduser())],
                       env={**os.environ, "CONTENT_STUDIO_SERVICE_LABEL": label}, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            return Item(2, "杀一次自己起来", False, "安全重启未执行（可能有任务在跑）", "等工作台中的任务结束后再验收", hard=False)
    except Exception as exc:  # noqa: BLE001
        return Item(2, "杀一次自己起来", False, str(exc)[:80], "把验收单交给安装负责人修复后台服务", hard=False)
    for _ in range(30):
        time.sleep(1)
        ok, _v = _service_answering(p, port)
        after = _launchd_state(p, label) or {}
        if ok and after.get("pid") and after.get("pid") != before.get("pid"):
            return Item(2, "杀一次自己起来", True, f"新 pid {after['pid']}，{_ + 1} 秒内应答", "", hard=False)
    return Item(2, "杀一次自己起来", False, "30 秒内没起来", "看 ~/Library/Logs/ContentStudio/content-studio.stderr.log", hard=False)


# ---------------- 3 配置 ----------------
def layer_config(*, port: int = 8780, probe: Probe | None = None, store_path: Path | None = None, cookie_path: Path | None = None) -> list[Item]:
    """先问跑着的服务（它知道自己读的是哪份 profile、哪个库）；服务没应答再看本地文件。"""
    p = probe or Probe()
    out: list[Item] = []
    st: dict[str, Any] | None
    try:
        st = p.get(f"http://127.0.0.1:{port}/api/state", 10.0)
    except Exception:  # noqa: BLE001
        st = None
    if st:
        setup = st.get("setup") or {}
        missing = [m.get("label") or m.get("key") for m in setup.get("missing_required") or []]
        ok = bool(setup.get("present")) and not missing
        out.append(Item(3, "你是谁", ok, "填好了" if ok else ("还没填" if not setup.get("present") else f"还缺 {len(missing)} 项"),
                        "" if ok else "工作台「开始用」第一步里填" + (f"：{'、'.join(missing)}" if missing else "")))
        vault = st.get("vault") or {}
        raw = str((st.get("settings") or {}).get("obsidian_vault") or "")
        vok = bool(vault.get("ok") and raw)
        out.append(Item(3, "Obsidian 库", vok, raw or "没填", "" if vok else "工作台「开始用」第三步，或设置 → 通用里填"))
        ed = (st.get("edition") or {}).get("name") or "full"
        out.append(Item(3, "版本", True, "试用版（砍掉的见 edition.py）" if ed == "trial" else "完整版", hard=False))
        cookies = st.get("cookies") or {}
        out.append(Item(3, "抖音登录信息", bool(cookies.get("ok")), "有" if cookies.get("ok") else str(cookies.get("message") or "没有"), "" if cookies.get("ok") else "工作台「开始用」第二步导入"))
    else:
        out += _config_from_files(store_path=store_path, cookie_path=cookie_path)
    for name, d in (("数据目录", config_dir()), ("草稿目录", config_dir() / "drafts")):
        wok = _writable(d)
        out.append(Item(3, f"{name}能写", wok, str(d), "" if wok else f"终端里 chmod u+rwx {d}"))
    return out


def _config_from_files(*, store_path: Path | None, cookie_path: Path | None) -> list[Item]:
    from . import profile as profile_mod
    from .creator_metrics import CookieFileError, load_cookie_file
    from .store import DEFAULT_STORE_PATH

    out: list[Item] = []
    try:
        found = profile_mod.find_profile()
        data = profile_mod.load(found) if found else {}
        req = [c for c in profile_mod.check(data) if c.required]
        bad = [c for c in req if not c.ok]
        out.append(Item(3, "你是谁", not bad, f"必填 {len(req) - len(bad)}/{len(req)}（服务没应答，看的是本地文件）",
                        "工作台「开始用」第一步里填：" + "、".join(c.label for c in bad) if bad else ""))
    except Exception:  # noqa: BLE001 - 配置坏了正是需要验收单的情况
        out.append(Item(3, "你是谁", False, "配置文件无法解析或读取", "把验收单交给安装负责人修复 profile.yaml"))
    try:
        db = (store_path or DEFAULT_STORE_PATH).expanduser().resolve()
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'obsidian_vault'").fetchone()
        raw = str(json.loads(row[0]) or "") if row else ""
        root = Path(raw).expanduser() if raw else None
        out.append(Item(3, "Obsidian 库", bool(root and root.is_dir()), raw or "没填", "" if root and root.is_dir() else "工作台「开始用」第三步，或设置 → 通用里填"))
    except Exception as exc:  # noqa: BLE001
        out.append(Item(3, "设置", False, str(exc)[:80], "数据文件读不了：看 ~/.config/content-studio/data/"))
    try:
        load_cookie_file(cookie_path or config_dir() / "douyin-cookies.json")
        out.append(Item(3, "抖音登录信息", True, "有"))
    except CookieFileError as exc:
        out.append(Item(3, "抖音登录信息", False, "没有" if "does not exist" in str(exc) else "文件不对", "工作台「开始用」第二步导入"))
    return out


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".acceptance-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


# ---------------- 4 通道 ----------------
def layer_channels(*, port: int, ai: bool, probe: Probe | None = None) -> list[Item]:
    p = probe or Probe()
    out: list[Item] = []
    on_codex = llm.backend() == "codex"
    if ai:
        out.append(_ai_once(p, "claude", shlex.split(os.environ.get("CONTENT_STUDIO_LLM_CMD") or "claude -p --model sonnet --output-format text --disallowedTools Bash,Edit,Write"),
                            hard=not on_codex, fix="终端里 claude login（launchd 里要有 USER / LOGNAME 才找得到钥匙串）" if not on_codex else "后台 AI 用的是 Codex，这项不挡"))
        codex = p.which("codex") or "/opt/homebrew/bin/codex"
        if Path(codex).is_file() or p.which("codex"):
            out.append(_ai_once(p, "codex", [codex, "exec", "--ignore-user-config", "-m", conf.value("codex.model"), "--skip-git-repo-check", "-s", "read-only",
                                              "--ephemeral", AI_PROMPT], stdin=False, hard=on_codex, fix="终端里 codex login"))
        else:
            out.append(Item(4, "codex", False if on_codex else None, "没装：后台 AI、封面、配图都没有" if on_codex else "没装：不出封面、不配图",
                            "brew install codex，再 codex login" if on_codex else "", hard=on_codex))
    else:
        out.append(Item(4, llm.backend(), None, "没试（--quick / --no-ai）"))
    try:
        st = p.get(f"http://127.0.0.1:{port}/api/state", 10.0)
    except Exception:  # noqa: BLE001
        out.append(Item(4, "抖音", None, "服务没应答，读不到同步状态"))
        st = None
    if st:
        me = st.get("self_account") or {}
        sync = st.get("last_full_sync") or {}
        stopped = sync.get("stopped") or sync.get("error") or (me.get("last_error") if me else None)
        at = me.get("last_synced_at") or ""
        if not (st.get("cookies") or {}).get("ok"):
            out.append(Item(4, "抖音", False, (st.get("cookies") or {}).get("message") or "没有登录信息", "工作台「开始用」第二步导入"))
        elif stopped:
            out.append(Item(4, "抖音", False, str(stopped)[:80], "在你自己的浏览器里打开抖音完成验证，再导入一次登录信息"))
        elif not me:
            out.append(Item(4, "抖音", False, "还没登记自己的号", "工作台「开始用」第一步填抖音主页链接"))
        else:
            try:
                last = datetime.fromisoformat(at.replace("Z", "+00:00"))
                age = datetime.now(timezone.utc) - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))
                recent = timedelta(0) <= age <= timedelta(hours=30)
            except (TypeError, ValueError, AttributeError):
                recent = False
            out.append(Item(4, "抖音", True if recent else None,
                            f"{me.get('nickname') or ''} · 上次读 {str(at)[:16].replace('T', ' ') or '还没读过'}",
                            "" if recent else "先在工作台手动同步自己的号，成功后重跑验收；本次没有抓取平台"))
        plats = (st.get("settings") or {}).get("platform_accounts") or {}
        try:
            rows = p.get(f"http://127.0.0.1:{port}/api/platforms", 60.0).get("platforms") or []
        except Exception:  # noqa: BLE001
            rows = []
        for r in rows:
            if r["key"] == "douyin" or not (plats.get(r["key"]) or {}).get("on"):
                continue
            state = r.get("state")
            if state in ("linked", "ready"):
                out.append(Item(4, r["label"], True, r.get("note") or "已连接", hard=False))
            elif state in ("stale", "setup"):
                out.append(Item(4, r["label"], False, r.get("note") or "", r.get("login_hint") or f"去{r['label']}页「后台」重新登录", hard=False))
            else:
                out.append(Item(4, r["label"], None, "你来传，不用连", hard=False))
    return out


def _ai_once(p: Probe, name: str, argv: list[str], *, stdin: bool = True, hard: bool, fix: str) -> Item:
    try:
        r = p.run(argv, input=AI_PROMPT if stdin else None, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return Item(4, name, False, "没装", fix, hard)
    except subprocess.TimeoutExpired:
        return Item(4, name, False, "3 分钟没回", fix, hard)
    except Exception as exc:  # noqa: BLE001
        return Item(4, name, False, str(exc)[:80], fix, hard)
    text = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0 and (r.stdout or "").strip() == "好":
        return Item(4, name, True, "回了", "", hard)
    low = text.lower()
    disabled = bool(re.search(r"disabled.*access|account.*(disabled|suspended)|organization.*disabled", low))
    why = "订阅访问被禁用" if disabled else "没登录" if re.search(r"authenticat|log ?in|oauth", low) else "额度用完了" if re.search(r"usage limit|rate limit|limit reached|quota", low) else "没有收到预期回复" if r.returncode == 0 else f"调用失败（退出码 {r.returncode}）"
    remedy = "由账号管理员恢复订阅访问后重试" if disabled else "等额度恢复后重试" if why == "额度用完了" else fix
    return Item(4, name, False, why, remedy, hard)


# ---------------- 5 主线（沙盒） ----------------
def layer_mainline() -> list[Item]:
    """在独立进程中验收，隔离 profile、vault 等模块全局和真实数据目录。"""
    with tempfile.TemporaryDirectory(prefix="cs-acceptance-") as tmp:
        env = {**os.environ, "CONTENT_STUDIO_HOME": tmp, "CONTENT_STUDIO_SKIP_PROFILE_ENV": "1",
               "CONTENT_STUDIO_HERMES_HOME": str(Path(tmp) / "hermes"), "CONTENT_STUDIO_NO_OPEN": "1",
               "CONTENT_STUDIO_NO_ILLUSTRATE": "1"}
        for name in ("CONTENT_STUDIO_SECRETS", "CONTENT_STUDIO_YOUTUBE_TOKEN", "CONTENT_OPS_PATH", "CONTENT_STUDIO_PUBLISH_TOOLKIT",
                     "CONTENT_STUDIO_XINGQIU", "CONTENT_DOWNLOADER_PATH", "CONTENT_STUDIO_CONSULTS", "CONTENT_STUDIO_QA_GUIDE"):
            env[name] = str(Path(tmp) / name.lower())
        code = "import json; from dataclasses import asdict; from content_studio.acceptance import sandbox_entry; print(json.dumps([asdict(i) for i in sandbox_entry()], ensure_ascii=False))"
        try:
            result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError(f"沙盒进程退出码 {result.returncode}")
            return [Item(**row) for row in json.loads(result.stdout)]
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return [Item(5, "主线沙盒", False, str(exc), "把验收单发给 作者")]


def sandbox_entry() -> list[Item]:
    """仅在专用子进程中调用；外部进程和网络尝试一律阻断，并让验收失败。"""
    denied: list[str] = []
    def guard(event: str, args: tuple[Any, ...]) -> None:
        if event in ("subprocess.Popen", "os.system", "os.posix_spawn", "socket.connect", "socket.getaddrinfo"):
            denied.append(event)
            raise RuntimeError("验收沙盒禁止外部命令与网络")
    sys.addaudithook(guard)
    items = _mainline_sandbox(config_dir())
    if denied:
        items.append(Item(5, "主线沙盒", False, "沙盒阻止了外部命令或网络尝试", "把验收单交给安装负责人"))
    return items


def _mainline_sandbox(home: Path) -> list[Item]:
    """在临时目录里把一条内容从「进来」走到「平台页待发」「标记发了」「进汇总」。不碰真数据、不叫 AI、不发布。"""
    out: list[Item] = []
    step = ""
    store = None
    try:
        from fastapi.testclient import TestClient

        from . import web
        from . import reach
        from .web import create_app

        vault = home / "vault" / "原始输出"
        vault.mkdir(parents=True)
        (vault / "验收.md").write_text("# 验收\n\n这一篇只在沙盒里。\n", encoding="utf-8")
        cookies = home / "cookies.json"
        cookies.write_text("[]", encoding="utf-8")
        os.chmod(cookies, 0o600)
        web.LEGACY_REPORT_DIRS = ()
        fake = lambda *a, **k: "（验收沙盒，不叫 AI）"  # noqa: E731
        channels = {key: {"label": label, "blocked": "验收沙盒不连接真实平台", "modes": {}} for key, label, _ in reach.PLATFORMS}
        app = create_app(store_path=home / "data" / "studio.sqlite3", cookie_path=cookies, creator_db=None, data_dir=home / "studio",
                         downloads_dir=home / "downloads", drafts_dir=home / "drafts", start_worker=False,
                         profile={"me": {"name": "验收"}, "vault": {"path": str(home / "vault"), "folders": {"my_writing": "原始输出"}}},
                         write_fn=fake, outline_fn=fake, suggest_fn=fake, publishers=channels)
        store = app.state.store
        c = TestClient(app, headers={"X-Content-Studio": "1"})
        step = "设置"
        assert c.put("/api/settings", json={"obsidian_vault": str(home / "vault")}).status_code == 200
        step = "建选题"
        tid = c.post("/api/topics", json={"title": "验收：这一条只在沙盒里"}).json()["id"]
        step = "写标题描述"
        assert c.put(f"/api/topics/{tid}/copy", json={"platforms": {"douyin": {"title": "验收标题", "body": "验收描述", "tags": ["验收"]}}}).status_code == 200
        assert c.put(f"/api/topics/{tid}/approve", json={"key": "copy"}).status_code == 200
        out.append(Item(5, "建选题、定标题", True, "沙盒里走通"))
        step = "平台页待发"
        page = c.get("/api/platform/douyin").json()
        mine = next((it for it in page["pending"] if it["topic_id"] == tid), None)
        ok = bool(mine) and mine["rows"][0]["form"] == "video"
        out.append(Item(5, "平台页看到待发", ok, "抖音页待发里有它，视频那一行等成片" if ok else "没出现在抖音页", "" if ok else "程序问题：把验收单发给 作者"))
        step = "标记发了"
        assert c.post(f"/api/topics/{tid}/platform/x/sent", json={"form": "text", "url": "https://x.com/i/status/1"}).status_code == 200
        posts = c.get("/api/platform/x").json()["posts"]
        ok = any(p_["topic_id"] == tid for p_ in posts)
        out.append(Item(5, "标记发了、进数据", ok, "X 页「发过的」里有它" if ok else "没记上", "" if ok else "程序问题：把验收单发给 作者"))
        step = "汇总和今天"
        codes = {path: c.get(path).status_code for path in ("/api/today/home", "/api/reach?days=7", "/api/platform/counts", "/api/backfill", "/api/outbox/matrix", "/api/state")}
        bad = [k for k, v in codes.items() if v != 200]
        out.append(Item(5, "今天、汇总接口", not bad, f"{len(codes) - len(bad)}/{len(codes)} 应答" if not bad else f"出错：{'、'.join(bad)}", "" if not bad else "程序问题：把验收单发给 作者"))
        out.append(Item(5, "成片、封面、文章", None, "要真视频和 AI：装完和客户一起真发一条时看（第 7 层）", hard=False))
    except Exception as exc:  # noqa: BLE001
        out.append(Item(5, f"主线在「{step or '起沙盒'}」这一步断了", False, str(exc)[:120], "程序问题：把验收单发给 作者"))
    finally:
        try:
            if store is not None:
                store.close()
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------- 6 界面 ----------------
def layer_ui(*, port: int, service_ok: bool = True, routes: tuple[str, ...] = ROUTES) -> list[Item]:
    if not service_ok:
        return [Item(6, "界面", None, "服务没应答，没开浏览器")]
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return [Item(6, "界面", None, "没装浏览器组件（playwright），这层没测")]
    errors: list[str] = []
    opened = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("try{localStorage.setItem('cs-anna','closed');localStorage.setItem('cs-wendy','closed');}catch(e){}")
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text[:120]}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"脚本异常：{str(e)[:120]}"))
            page.on("response", lambda r: errors.append(f"{r.status} {r.url[-60:]}") if r.status >= 500 else None)
            for route in routes:
                page.goto(f"http://127.0.0.1:{port}/#{route}", wait_until="networkidle", timeout=30000)
                page.reload(wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(600)
                opened += 1
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return [Item(6, "界面", False, f"开到第 {opened + 1} 页时断了：{str(exc)[:80]}", "把验收单发给 作者")]
    return [Item(6, "界面", not errors, f"{opened} 页 · {len(errors)} 个报错" + (f"：{errors[0]}" if errors else ""), "" if not errors else "把验收单发给 作者")]


# ---------------- 7 交接 ----------------
def layer_handover() -> list[Item]:
    return [Item(7, name, None, note, hard=False) for name, note in HANDOVER]


# ---------------- 跑一遍 ----------------
def run(*, quick: bool = False, ai: bool | None = None, port: int = 8780, label: str | None = None, restart: bool = False,
        probe: Probe | None = None, mainline: Callable[[], list[Item]] | None = None, ui: Callable[..., list[Item]] | None = None) -> Report:
    label = label or conf.value("service.label")
    use_ai = (not quick) if ai is None else ai
    report = Report(at=datetime.now().isoformat(timespec="minutes"), quick=quick)
    report.items += layer_machine()
    install = layer_install(port=port, label=label, probe=probe, restart=restart)
    report.items += install
    report.items += layer_config(port=port, probe=probe)
    report.items += layer_channels(port=port, ai=use_ai, probe=probe)
    report.items += (mainline or layer_mainline)()
    service_ok = any(i.name.startswith("后台服务") and i.ok for i in install)
    if quick:
        report.items.append(Item(6, "界面", None, "没开浏览器（--quick）"))
    else:
        report.items += (ui or layer_ui)(port=port, service_ok=service_ok)
    report.items += layer_handover()
    return report


MARK = {True: "✅", False: "❌", None: "○ "}
HEADLINE = {2: ("后台服务", "开机常驻"), 3: ("你是谁", "Obsidian 库"), 4: ("抖音", "codex", "claude"), 5: ("建选题、定标题", "今天、汇总接口"), 6: ("界面",)}


def _headline(layer: int, items: list[Item]) -> str:
    """一层全绿时那一行写什么：几项都好，加这一层最要紧的一两句。"""
    if layer == 7:
        return "等你和客户做"
    n_ok = sum(1 for i in items if i.ok)
    picks = [i for i in items if i.ok and any(i.name.startswith(k) for k in HEADLINE.get(layer, ()))]
    extra = " · ".join(f"{i.name} {i.note}" if layer in (2, 4) else i.note for i in picks[:2] if i.note)
    return f"{n_ok} 项 ✓" + (f" · {extra}" if extra else "")


def render_text(report: Report) -> str:
    lines = [f"验收 · {report.at}" + ("（quick）" if report.quick else "")]
    for layer, name in LAYERS.items():
        mine = [i for i in report.items if i.layer == layer]
        state = report.layer_state(layer)
        mark = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "○ "}[state]
        head = [i for i in mine if i.ok is False]
        summary = "、".join(f"{i.name}：{i.note}" for i in head[:2]) if head else _headline(layer, mine)
        lines.append(f"  {mark} {layer} {name:<4} {summary}")
        for i in mine:
            if i.ok is False:
                lines.append(f"       ❌ {i.name}：{i.note}" + (f" → {i.fix}" if i.fix and i.fix != i.note else "") + ("" if i.hard else "（不挡验收）"))
            elif i.ok is None and layer != 7:
                lines.append(f"       ○  {i.name}：{i.note}" + (f" → {i.fix}" if i.fix else ""))
    if report.layer_state(7) == "skip":
        for i in report.items:
            if i.layer == 7:
                lines.append(f"       ○  {i.name}：{i.note}")
    lines.append("")
    bad = report.failed()
    lines.append(f"❌ {len(bad)} 项没过：" + "；".join(f"{i.name}（{i.fix or i.note}）" for i in bad) if bad else
                 "○ 自动检查尚未完成：" + "、".join(i.name for i in report.pending()) if report.pending() else
                 "✅ 自动检查通过；真视频、重启和客户交接仍待完成。")
    if report.saved:
        lines.append(f"验收单已存：{report.saved}")
    return "\n".join(lines)


def render_html(report: Report) -> str:
    rows = []
    for layer, name in LAYERS.items():
        state = report.layer_state(layer)
        rows.append(f'<tr class="h {state}"><th colspan="3">{layer} · {html.escape(name)}</th></tr>')
        for i in report.items:
            if i.layer != layer:
                continue
            cls = "ok" if i.ok else "no" if i.ok is False else "skip"
            rows.append(f'<tr class="{cls}"><td>{MARK[i.ok]}</td><td>{html.escape(i.name)}{"" if i.hard else " <small>可选</small>"}</td>'
                        f'<td>{html.escape(i.note)}{f"<br><b>→ {html.escape(i.fix)}</b>" if i.ok is not True and i.fix and i.fix != i.note else ""}</td></tr>')
    verdict = f"{len(report.failed())} 项没过" if report.failed() else "自动检查尚未完成" if report.pending() else "自动检查通过，交接待完成"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>验收单 {html.escape(report.at)}</title>
<style>body{{font-family:-apple-system,"PingFang SC",sans-serif;max-width:860px;margin:40px auto;padding:0 20px;color:#18222c;line-height:1.6}}
h1{{font-size:26px;margin:0 0 4px}}p.v{{font-size:20px;font-weight:700;margin:0 0 20px;color:{'#24794a' if report.passed() else '#b23a2e'}}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;padding:8px 10px;border-bottom:1px solid #e3e7ea;vertical-align:top}}
tr.h th{{background:#f4f6f5;font-size:13px;letter-spacing:.06em;padding-top:14px}}tr.h.fail th{{color:#b23a2e}}tr.no td{{background:#fbecea}}tr.skip td{{color:#6b7680}}
td:first-child{{width:28px}}small{{color:#6b7680;font-weight:400}}</style></head><body>
<h1>内容工作台 · 装机验收单</h1><p class="v">{verdict} · {html.escape(report.at)}{'（quick）' if report.quick else ''}</p>
<table>{''.join(rows)}</table>
<p style="color:#6b7680;font-size:13px;margin-top:20px">红的每一条后面写着该点哪里。第 7 层是人做的：扫码登录、一起真发一条、重启后再跑一次、签字。</p>
</body></html>"""


def save(report: Report, folder: Path | None = None) -> Path:
    folder = folder or (config_dir() / "acceptance")
    folder.mkdir(parents=True, exist_ok=True)
    stem = report.at.replace(":", "")
    path = folder / f"{stem}.html"
    report.saved = str(path)
    (folder / f"{stem}.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    path.write_text(render_html(report), encoding="utf-8")
    (folder / "latest.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
