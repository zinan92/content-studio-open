from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import json
import subprocess
import sys
import os
import re
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import writing_rules

from .paths import config_dir
from .accounts import PLATFORM_DOUYIN, AccountError, ContentDownloaderClient, sync_account
from .creator_metrics import CookieFileError, load_cookie_file
from . import today as today_plan
from .core import dates
from .core.places import Places
from . import edition
from . import eggs as eggs_mod
from . import vault
from . import video_project
from . import copypack
from . import outline as outline_mod
from .video_project import VideoProjectError
from .extras.positioning.positioning import PositioningError
from .store import StoreError, StudioStore, now_iso
from .worker import TeardownWorker, WorkerConfig


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
REPORT_STALE_DAYS = 7
LEGACY_REPORT_DIRS = (config_dir() / "m1",)


class FrameBody(BaseModel):
    kind: str
    text: str
    key: str | None = None
    folder: str | None = None


class UrlBody(BaseModel):
    url: str
    is_self: bool = False


class StandardBody(BaseModel):
    text: str
    source: str = ""


class JobBody(BaseModel):
    url: str | None = None
    video_id: str | None = None
    source: str | None = None


class CheckBody(BaseModel):
    day: str
    key: str
    checked: bool


class TriageBody(BaseModel):
    path: str
    status: str | None = None


class TopicBody(BaseModel):
    title: str | None = None
    note_paths: list[str] | None = None
    formats: str | None = None
    status: str | None = None
    memo: str | None = None
    published_url: str | None = None
    account_id: int | None = None
    archived: bool | None = None


class SnoozeBody(BaseModel):
    days: int = 14


class StageBody(BaseModel):
    stage: str | None = None  # "outline" = step back to the outline; None = clear the override


class SkillBody(BaseModel):
    name: str
    title: str | None = None  # 表单里空着的格子发 null；空的由 skills.clean_entry 补默认或报人话
    stage: str
    use: str | None = None
    invoke: str | None = None
    author: str | None = None
    repo: str | None = None
    dir: str | None = None
    path: str | None = None
    own: bool = False
    previous: str | None = None


class BackfillMarkBody(BaseModel):
    platform: str
    done: bool = True


class BackfillCancelBody(BaseModel):
    cancel: bool = True


class BackfillSkipBody(BaseModel):
    platform: str
    skip: bool = True


class DailyPickBody(BaseModel):
    key: str
    path: str
    item: str


class AnnaBody(BaseModel):
    scope: str
    message: str
    note_path: str | None = None
    report_id: str | None = None
    screen: str = ""  # 他发消息那一刻屏幕上那一页的字：页面加了什么，她都看得到


class VideoLinkBody(BaseModel):
    name: str | None = None


class PublishJobBody(BaseModel):
    platform: str
    mode: str
    auto: bool = False  # D 补发里一声令下起的：发完不在浏览器里弹页面


class ApproveBody(BaseModel):
    gate: str
    note: str | None = None


class V2ApproveBody(BaseModel):
    gate: str
    message: str


class V2StartBody(BaseModel):
    job: str


class V2SettingsBody(BaseModel):
    values: dict[str, Any]
    scope: str = "project"  # project：只改这条视频；default：设为 作者 以后的默认


class DroppedFile(BaseModel):
    name: str
    size: int


class DropBody(BaseModel):
    files: list[DroppedFile]


class WorktableBody(BaseModel):
    text: str
    filename: str | None = None
    overwrite: bool = False


class PublishBody(BaseModel):
    video_id: str | None = None
    force: bool = False  # 硬要对上比选题还早的视频（补记老视频时）；页面上不给这个口子


class CopyBody(BaseModel):
    platforms: dict[str, dict[str, Any]]


class SkipBody(BaseModel):
    platform: str
    skip: bool


class RecordBody(BaseModel):
    platform: str
    published: bool
    url: str | None = None


class ArticleBody(BaseModel):
    markdown: str


class KpiTargetsBody(BaseModel):
    douyin_end: int | None = Field(default=None, ge=0)
    douyin_end_day: str | None = None
    x_end: int | None = Field(default=None, ge=0)
    x_end_day: str | None = None
    x_impressions: int | None = Field(default=None, ge=0)
    revenue: float | None = None


class SettingsBody(BaseModel):
    x_daily: bool | None = None  # 10/19 作者 关掉了 X 每天排短帖、长文那套
    x_follow_target: dict[str, Any] | None = None
    x_kpi: dict[str, Any] | None = None
    reply_gap_minutes: int | None = None
    park_writing_skill: str | None = None
    threshold: float | None = None
    auto_enqueue_limit: int | None = None
    auto_enqueue_threshold: float | None = None
    sync_pages: int | None = None
    sync_delay_seconds: float | None = None
    obsidian_vault: str | None = None
    yanxishi_admin_url: str | None = None
    video_projects_root: str | None = None
    douyin_archive: str | None = None
    local_video_roots: list[str] | None = None
    platform_accounts: dict[str, dict[str, Any]] | None = None
    tracker_keep: list[str] | None = None
    profiles: dict[str, dict[str, Any]] | None = None
    traffic_tags: dict[str, list[str]] | None = None
    writer_skill: str | None = None
    components_off: list[str] | None = None


class XLineTextBody(BaseModel):
    text: str
    source_id: str | None = None
    quote_url: str | None = None  # 发成引用帖：被引用的那条（X 热榜「引用它」）


class XSuggestBody(BaseModel):
    kind: str                 # note / daily / feed / xhot
    text: str | None = None   # xhot：那条帖子的正文
    quote: bool = False       # xhot：写成引用帖（原帖跟着引用卡片出来，不用再贴链接）
    path: str | None = None   # note：笔记路径；daily：那一期的路径
    key: str | None = None    # daily：哪份日报
    item: str | None = None   # daily：哪一条快讯
    title: str | None = None  # feed：视频标题
    author: str | None = None
    url: str | None = None


class XLineSkipBody(BaseModel):
    source_id: str
    undo: bool = False


class StepApproveBody(BaseModel):
    key: str
    approved: bool = True
    by: str = "park"  # "machine"：补发提前打包时机器替他定的稿


class WriteBody(BaseModel):
    instruction: str | None = None


class ShootBody(BaseModel):
    text: str | None = None
    top: bool = False
    move: int | None = None  # -1 上移 / +1 下移
    planned_day: str | None = None  # 周历：排在哪天拍（YYYY-MM-DD）；传空字符串 = 不排了
    at: int | None = None  # 放到清单第几位（从 0 数）：日历上拖到某天


class ScheduleBody(BaseModel):
    topic_id: int | None = None
    note_id: int | None = None  # 「接下来要拍的」里手写的一条（没有选题）
    at: int | None = None  # 排到第几天（从第一个空着的日子数，0 = 今天）


class QueueTopicsBody(BaseModel):
    topic_ids: list[int]
    at: int | None = None  # 从清单第几位开始放；不传 = 接在最后


class ModeBody(BaseModel):
    mode: str


class CellSentBody(BaseModel):
    sent: bool = True


class WendyBody(BaseModel):
    message: str = ""
    page: str = "today"  # 他在哪一页回的她：today / positioning（定位页聊的是方向，带上定位原文）
    screen: str = ""  # 他发消息那一刻屏幕上那一页的字：页面加了什么，她都看得到


class PlanBody(BaseModel):
    day: str | None = None
    text: str | None = None
    done: bool | None = None


class RevenueBody(BaseModel):
    amount: float
    source: str
    day: str | None = None
    note: str = ""


class MoneyActionBody(BaseModel):
    note: str


class DmBody(BaseModel):
    received: int
    replied: int
    day: str | None = None


class ProfileBody(BaseModel):
    name: str | None = None
    bio: str | None = None
    mtime: float | None = None


class AccountKindBody(BaseModel):
    kind: str


class FeedMarkBody(BaseModel):
    seen: bool | None = None
    note: str | None = None
    opened: bool | None = None


class SwipeBody(BaseModel):
    url: str | None = None
    note: str | None = None
    collection: str | None = None


class CountBody(BaseModel):
    value: int
    day: str | None = None


class DriverMarkBody(BaseModel):
    key: str
    reason: str | None = None


class ReachBody(BaseModel):
    day: str
    platform: str
    views: int | None = None  # None clears the entry


class FollowersBody(BaseModel):
    platform: str
    followers: int


class BackgroundOps:
    """Single-flight background syncs so the UI never blocks and never double-fetches.

    "all"（自己的全部账号）、"benchmarks"（对标）、单个账号都会碰抖音，互相排队：同一时间只有一趟。
    """

    BATCHES = ("all", "benchmarks")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.syncing: set[int] = set()
        self.full_sync_running = False
        self.benchmarks_running = False
        self.last_full_sync: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        return self.full_sync_running or self.benchmarks_running or bool(self.syncing)

    def _flag(self, key: str, value: bool) -> None:
        if key == "all":
            self.full_sync_running = value
        else:
            self.benchmarks_running = value

    def run(self, key: int | str, fn: Callable[[], Any]) -> bool:
        with self._lock:
            if self.busy:
                return False
            if key in self.BATCHES:
                self._flag(key, True)  # type: ignore[arg-type]
            else:
                self.syncing.add(key)  # type: ignore[arg-type]

        def target() -> None:
            try:
                result = fn()
                if key in self.BATCHES:
                    self.last_full_sync = result
            except Exception as exc:  # noqa: BLE001 - surfaced through account status
                logger.warning("background sync %s failed: %s", key, exc)
                if key in self.BATCHES:
                    self.last_full_sync = {"error": str(exc)}
            finally:
                with self._lock:
                    if key in self.BATCHES:
                        self._flag(key, False)  # type: ignore[arg-type]
                    else:
                        self.syncing.discard(key)  # type: ignore[arg-type]

        threading.Thread(target=target, name=f"sync-{key}", daemon=True).start()
        return True


def vault_status(raw: str) -> dict[str, Any]:
    path = Path(raw).expanduser()
    if not path.is_dir():
        return {"path": raw, "ok": False, "message": f"找不到 Obsidian 库：{raw}。在设置里改成你的库所在文件夹"}
    return {"path": raw, "ok": True, "message": None}


def _creator_rows(creator_db: Path | None) -> dict[str, dict[str, Any]]:
    if creator_db is None:
        return {}
    path = creator_db.expanduser()
    if not path.is_file():
        return {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM creator_video_metrics").fetchall()
    except sqlite3.Error:
        return {}
    return {row["video_id"]: {k: row[k] for k in row.keys() if k != "raw_json"} for row in rows}


def _apply_profile(store: StudioStore, data: dict[str, Any] | None) -> None:
    """profile.yaml 是「一个人告诉工作台的所有事」；这里把它落到运行时状态上。

    只在启动时做一次，而且只填空不覆盖：设置页里手改过的值优先。账号只登记不同步——
    第一次启动就去抓六个账号会把人吓跑，让他自己点「同步全部账号」。
    """
    vault.configure((data or {}).get("vault") or None)
    if not data:
        return
    from .extras.team import anna as anna_mod
    from . import outline as outline_mod
    from . import profile as profile_mod
    from .accounts import AccountError, add_account

    current = store.settings()
    patch: dict[str, Any] = {}
    vault_path_cfg = str((data.get("vault") or {}).get("path") or "").strip()
    if vault_path_cfg and current.get("obsidian_vault") in ("", None):
        patch["obsidian_vault"] = vault_path_cfg
    root = str(data.get("video_projects_root") or "").strip()
    if root and not current.get("video_projects_root"):
        patch["video_projects_root"] = root
    archive_cfg = str(data.get("douyin_archive") or "").strip()
    if archive_cfg and current.get("douyin_archive") != archive_cfg:
        patch["douyin_archive"] = archive_cfg
    roots_cfg = [str(r) for r in (data.get("local_video_roots") or []) if str(r).strip()]
    if roots_cfg and current.get("local_video_roots") != roots_cfg:
        patch["local_video_roots"] = roots_cfg
    # Anna 的角色文件和提纲框架：profile 指到哪就读哪；环境变量已设的不动（那是显式覆盖）。
    wendy_cfg = data.get("wendy") or {}
    if isinstance(wendy_cfg, dict):
        from .extras.team import wendy as wendy_mod

        for key, env_name in (("role", wendy_mod.ROLE_ENV), ("hermes", wendy_mod.HERMES_ENV)):
            value = str(wendy_cfg.get(key) or "").strip()
            if value and not os.environ.get(env_name):
                os.environ[env_name] = value
    anna_cfg = data.get("anna") or {}
    if isinstance(anna_cfg, dict):
        for key, env_name in (("role", anna_mod.ANNA_ROLE_ENV), ("workflows", outline_mod.WORKFLOWS_ENV), ("writing_skill", writing_rules.SKILL_ENV)):
            value = str(anna_cfg.get(key) or "").strip()
            if value and not os.environ.get(env_name):
                os.environ[env_name] = value
    platforms = (data.get("me") or {}).get("platforms") or {}
    if isinstance(platforms, dict) and not current.get("platform_accounts"):
        patch["platform_accounts"] = {
            k: {"on": True, "handle": str(v).strip()} for k, v in platforms.items()
            if k in profile_mod.PLATFORM_KEYS and str(v or "").strip()
        }
    if patch:
        store.update_settings(patch)
    me_url = str((data.get("me") or {}).get("douyin") or "").strip()
    if me_url and store.self_account() is None:
        try:
            add_account(store, me_url, is_self=True)
        except AccountError as exc:
            logger.warning("profile: 自己的账号没登记上：%s", exc)
    known = {a["profile_url"] for a in store.accounts()}
    for url in data.get("benchmarks") or []:
        url = str(url or "").strip()
        if url and url not in known:
            try:
                add_account(store, url)
            except AccountError as exc:
                logger.warning("profile: 对标账号 %s 没登记上：%s", url[:40], exc)


SCREEN_REACH_APP = Path("~/Applications/内容工作台读数.app").expanduser()


def _start_screen_reach() -> str:
    """叫「内容工作台读数」小 App 读一次小红书；没装就说一声。"""
    if not SCREEN_REACH_APP.exists():
        return "没装读数小 App，小红书只能每天 9:25 读"
    try:
        subprocess.run(["open", "-g", str(SCREEN_REACH_APP)], check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"读数小 App 没叫起来：{exc}"
    return "started"


# 主线给积木（blocks/ 和 extras/）的全部东西：积木只能从这里拿，各自在 NEEDS 里写明用哪几样。
# 往这里加一样，就是给积木多开一个口子。能放进 core/ 的就别放这里：积木直接 import（第 2 步搬走了「放在哪」和日期）。
BLOCK_API: tuple[str, ...] = (
    # 底座
    "store", "profile", "feature_on", "data_dir", "downloads_dir", "drafts_root", "creator_db", "hooks", "startup", "stop_auto",
    "writer", "reach", "pp_mod",
    # 东西放在哪（core/places.py）
    "places",
    # 今天、汇总的读数
    "get_today", "get_today_home", "get_board", "get_reach", "get_results", "get_kpi", "shot_days", "_traffic", "_local",
    # 平台和发布
    "publisher_specs", "PLATFORM_MODES", "_pp_action", "_pp_label", "_pp_pending", "_release_for", "_open_in_browser",
    "_login_view", "platform_logins", "LOGIN_RECHECK_SECONDS", "LOGIN_TIMEOUT_SECONDS", "others_auto",
    "OTHERS_TICK_SECONDS", "bw_lock", "bw_run", "_bw_pick", "_bw_snapshot", "_bw_start", "get_backfill",
    # 加工中
    "writing", "writing_lock", "_sync_series", "runner_command", "runs_dir", "_video_transcript", "_raw_folder",
    # 可替换的外部调用（测试换成假的）
    "anna_fn", "wendy_fn", "write_fn", "draft_exists_fn", "evidence_fn", "proof_fn", "x_fetch_fn", "x_illustrate_fn", "x_cover_fn",
    "x_post_fn", "x_profile_read_fn", "x_profile_update_fn",
    # 汇总
    "_week", "archive_lock", "archive_state", "kpi_config", "ops", "read_state", "review_fn", "review_lock",
    "shipped_days", "start_archive", "teardown_state", "money_days",
    # 设置
    "cookie_path",
    # 进项
    "DEEP_SYNC_PAGES", "FEED_HOT", "_backfill_state", "_sync_and_queue", "board_mod", "factory", "job_view",
    "report_dirs", "swipe_root", "sync_all_fn", "worker",
)


def create_app(
    *,
    store_path: Path,
    cookie_path: Path,
    creator_db: Path | None,
    data_dir: Path,
    downloads_dir: Path,
    client_factory: Callable[[], Any] | None = None,
    sync_all_fn: Callable[[StudioStore], dict] | None = None,
    creator_sync_fn: Callable[[], dict] | None = None,
    worker: TeardownWorker | None = None,
    start_worker: bool = True,
    drafts_dir: Path | None = None,
    write_fn: Callable[[str], str] | None = None,
    brief_fn: Callable[[str], dict] | None = None,
    outline_fn: Callable[[str], str] | None = None,
    coupon_fn: Callable[[str], str] | None = None,
    review_fn: Callable[[str], dict] | None = None,
    suggest_fn: Callable[[str], str] | None = None,
    x_profile_read_fn: Callable[[], dict] | None = None,
    x_profile_update_fn: Callable[..., dict] | None = None,
    x_fetch_fn: Callable[[str], Any] | None = None,
    x_post_fn: Callable[[str], dict] | None = None,
    x_illustrate_fn: Callable[[Path], Any] | None = None,
    x_cover_fn: Callable[[str, Path], None] | None = None,  # X 长文封面的出图（测试里注入假的，不叫 Codex）
    opening_fn: Callable[[str], dict] | None = None,
    speak_fn: Callable[[str], Any] | None = None,
    qa_fn: Callable[[str], dict] | None = None,
    proof_fn: Callable[..., dict] | None = None,
    evidence_fn: Callable[..., dict] | None = None,
    anna_fn: Callable[[str, str, str | None], dict] | None = None,
    wendy_fn: Callable[[str, str, str | None], dict] | None = None,
    runs_dir: Path | None = None,
    runner_command: str | None = None,
    publishers: dict[str, dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    draft_exists_fn: Callable[[str], bool] | None = None,
) -> FastAPI:
    from . import writer
    from . import board as board_mod
    from . import publish_desk as publish_desk_mod
    from . import schedule as schedule_mod

    store = StudioStore(store_path)
    _apply_profile(store, profile)
    store.recover_interrupted_writes()
    store.recover_interrupted_publishes()
    # 10/7：每条内容在每个平台发什么都记在它自己身上，之后改默认（X 加发文章）不会波及老内容
    store.freeze_platform_forms()
    # 2026-09-16: the vault's Clippings folder was renamed to 002_clippings.
    store.rename_note_prefix("Clippings", "002_clippings")
    review_lock = threading.Lock()
    drafts_root = (drafts_dir or writer.DEFAULT_DRAFTS_DIR).expanduser()
    writing: set[int] = set()
    writing_lock = threading.Lock()
    ops = BackgroundOps()
    if creator_sync_fn is None and client_factory is None and creator_db is not None:
        def creator_sync_fn() -> dict:
            from .cli import sync_creator_metrics

            return sync_creator_metrics(cookie_path=cookie_path, creator_db=creator_db)
    data_dir = data_dir.expanduser()
    report_dirs = [data_dir, *(path.expanduser() for path in LEGACY_REPORT_DIRS)]
    # 东西放在哪（core/places.py）：笔记库、视频盘、成片存档、草稿、报告。下面那些名字是它的别名，主线照旧这么叫
    places = Places(store, drafts_root=drafts_root, data_dir=data_dir, report_dirs=report_dirs)
    worker = worker or TeardownWorker(
        store,
        WorkerConfig(cookie_path=cookie_path, data_dir=data_dir, downloads_dir=downloads_dir, creator_db=creator_db),
    )

    def factory() -> Any:
        if client_factory is not None:
            return client_factory()
        return ContentDownloaderClient(load_cookie_file(cookie_path))


    stop_auto = threading.Event()

    # 积木（blocks/、extras/）开机要起的后台线程，挂上时自己登记进来
    startup: list[Callable[[], Any]] = []
    # 能力积木给主线留的口子：挂上了才有（试用版里没有），主线用 hooks.get(...) 读，不直接 import 那一块
    hooks: dict[str, Callable[..., Any]] = {}

    def _open_in_browser(url: str | None) -> None:
        """发完就在 作者 的默认浏览器里打开那一页（他登录着的那个）。测试里关掉。"""
        if not url or os.environ.get("CONTENT_STUDIO_NO_OPEN") or sys.platform != "darwin":
            return
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def prepare_publish(*args, **kwargs):
        if "prepare_publish" not in hooks:
            raise ValueError("当前安装不包含机器发布")
        return hooks["prepare_publish"](*args, **kwargs)

    def _run_publish(*args, **kwargs):
        return hooks["run_publish"](*args, **kwargs)

    def _proof_hold(topic_id: int | None) -> str:
        """证据单定了「你的截图」还没传（10/9 卡发不卡拍）：返回差什么；没有证据这块（试用版）或不差就空。"""
        fn = hooks.get("proof_hold")
        if not fn or not topic_id or not feature_on("proof"):  # 10/9：证据这一步关了就不卡发
            return ""
        try:
            return fn(topic_id)
        except Exception as exc:  # noqa: BLE001 - 查不了就不卡，别把发布台弄坏
            logger.warning("proof hold %s: %s", topic_id, exc)
            return ""

    def feature_on(key: str) -> bool:
        """这个组件开着没有：版本没砍、用户也没在「设置 · 流程」里关（10/9）。所有「开没开」都问这里。"""
        return edition.on(key, profile, store.settings().get("components_off") or [])

    def _login_ok(*args, **kwargs):
        fn = hooks.get("login_ok")
        return fn(*args, **kwargs) if fn else False

    def _consult_rows() -> list[dict[str, Any]]:
        """咨询记录（extras/consults 挂上了才有）。"""
        fn = hooks.get("consult_rows")
        return fn() if fn and feature_on("consults") else []

    # -- 变现（10/9 作者）：每天一个变现动作算分；收入记账，今天页一张卡 --------------------------
    def money_sources() -> list[dict[str, str]]:
        """「记一笔」能选的来源：咨询，加上产品清单里的每一个（extras/products 挂上了才有）。"""
        fn = hooks.get("product_rows")
        rows = fn() if fn and feature_on("products") else []
        return [{"key": "consult", "label": "咨询"}, *({"key": r["key"], "label": r["name"]} for r in rows), {"key": "other", "label": "其他"}]

    def money_how(since: str) -> dict[str, list[str]]:
        """since 以来每天做了哪些变现动作（工作台看得到的）：记了收入、有咨询、回了私信、他自己写的「做了」。"""
        labels = {s["key"]: s["label"] for s in money_sources()}
        out: dict[str, list[str]] = {}
        for r in store.driver_log(since, "money"):
            out.setdefault(r["day"], []).append(r["reason"] or "")
        for r in store.revenue(since):
            out.setdefault(r["day"], []).append(f"收了 ¥{r['amount']:,.0f}（{labels.get(r['source'], r['source'])}）")
        for c in _consult_rows():
            if (c.get("day") or "") >= since:
                out.setdefault(c["day"], []).append(f"和{c['name']}咨询")
        for day, e in store.dm_entries(since).items():
            if e["replied"] > 0:
                out.setdefault(day, []).append(f"回了 {e['replied']} 条私信")
        return out

    def money_days(since: str) -> set[str]:
        return set(money_how(since))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            for fn in startup:
                fn()
            worker.start()
            threading.Timer(5, _pack_resume_all).start()
            threading.Timer(8, _schedule_write_resume).start()  # 排期的「写开头和骨架」被重启打断了：接着写
            threading.Thread(target=_day_close_loop, name="day-close", daemon=True).start()
        yield
        stop_auto.set()
        worker.stop()

    app = FastAPI(title="内容工作台", docs_url=None, redoc_url=None, lifespan=lifespan)

    from .publisher import PublishError

    @app.exception_handler(PublishError)
    async def _publish_error(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(VideoProjectError)
    async def _video_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(vault.VaultError)
    async def _vault_missing(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    from .standard import StandardError

    @app.exception_handler(PositioningError)
    @app.exception_handler(StandardError)
    @app.exception_handler(StoreError)
    @app.exception_handler(AccountError)
    @app.exception_handler(ValueError)
    async def _friendly(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # -- helpers ------------------------------------------------------------

    report_file = places.report_file

    def job_view(job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {k: job[k] for k in ("id", "stage", "error", "source", "created_at", "updated_at", "url", "video_id")}

    DEEP_SYNC_PAGES = 15

    def teardown_state(video_id: str) -> dict[str, Any]:
        job = store.job_for_video(video_id)
        has_report = report_file(video_id) is not None
        return {"has_report": has_report, "job": job_view(job)}


    # -- state --------------------------------------------------------------


    def _my_handle(key: str) -> str:
        """这个平台上我叫什么：平台设置里的账号名 > 抖音号的昵称 > 品牌名。卡片、封面、预览上的署名用它，不写死。"""
        from . import conf

        acct = (store.settings().get("platform_accounts") or {}).get(key) or {}
        me = store.self_account() or {}
        return str(acct.get("handle") or me.get("nickname") or conf.brand(profile)["name"]).strip()


    # ---------------- 开始用（10/6 作者：装到别人电脑上，第一次打开走三步，都在页面上做，不碰终端、不碰文件） ----------------


    # -- my videos ----------------------------------------------------------


    # -- accounts -----------------------------------------------------------


    def _sync_and_queue(account_id: int, deep: bool = False, first: bool = False) -> dict:
        from .cli import BENCHMARK_PAGES

        is_self = bool(store.account(account_id)["is_self"])
        # 对标平时只看最新一页（省抖音额度）；刚加进来那次读够 3 页好算中位数，「往回翻」才多翻
        pages = DEEP_SYNC_PAGES if deep else (None if is_self or first else BENCHMARK_PAGES)
        result = sync_account(store, account_id, client_factory=factory, pages=pages)
        acct = store.account(account_id)
        store.log_event("sync", f"{'往回翻完' if deep else '同步完'} {acct.get('nickname') or '账号'}，这次拉到 {result.get('video_count', '?')} 条作品")
        if not deep and is_self and creator_sync_fn is not None:
            result["creator_metrics"] = creator_sync_fn()
        return result


    FEED_HOT = 1.5  # 10/4 作者：点赞到这个号平时（中位数）1.5 倍以上的标出来、排在最上面


    # -- jobs ---------------------------------------------------------------


    # -- reports ------------------------------------------------------------


    # -- vault (read-only Obsidian) ----------------------------------------

    vault_path = places.vault_path

    parse_day = dates.parse_day

    @app.put("/api/today/checks")
    def put_check(body: CheckBody) -> dict[str, Any]:
        parse_day(body.day)
        if body.key not in {s.key for s in vault.DAILY_SOURCES} | {k for k, _, _ in READ_DAILIES} | {"video_shot"}:
            raise ValueError("未知的勾选项")
        return {"day": body.day, "checks": store.set_daily_check(body.day, body.key, body.checked)}


    # -- skills -----------------------------------------------------------


    # -- topics & today plan ---------------------------------------------

    @app.get("/api/topics")
    def list_topics(archived: bool = False) -> list[dict[str, Any]]:
        raw = _raw_folder()
        return [{**t, "replicate": _speak_brief(t["id"]), "content_mode": schedule_mod.content_mode(t, raw, drafts_root)}
                for t in store.topics(include_archived=archived)]

    def _script_runner() -> Callable[..., Any] | None:
        """能走 park-writing 第一轮就返回跑口播稿的函数（xline 块在、带清单的 skill 装了）；不能就是 None，照老的写骨架、密度。"""
        ready = getattr(app.state, "topic_script_ready", None)
        run = getattr(app.state, "topic_script_run", None)
        return run if ready and run and ready() else None

    def _own(topic: dict[str, Any]) -> bool:
        return schedule_mod.content_mode(topic, _raw_folder(), drafts_root)["mode"] == "own"

    @app.put("/api/topics/{topic_id}/mode")
    def put_topic_mode(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """这条内容「已经有我的话」（own，直接走第一轮）/「还没有」（draft，才写骨架、密度）/ auto（回到自动判断）。"""
        topic = store.topic(topic_id)
        mode = body.get("mode")
        if mode not in ("own", "draft", "auto"):
            raise ValueError("只能是 own、draft 或 auto")
        schedule_mod.set_mode(drafts_root, topic_id, None if mode == "auto" else mode)
        return {"content_mode": schedule_mod.content_mode(topic, _raw_folder(), drafts_root)}

    @app.post("/api/topics")
    def post_topic(body: TopicBody) -> dict[str, Any]:
        return store.create_topic(
            body.title or "",
            note_paths=body.note_paths,
            formats=body.formats or "both",
            account_id=body.account_id,
            memo=body.memo,
        )

    @app.patch("/api/topics/{topic_id}")
    def patch_topic(topic_id: int, body: TopicBody) -> dict[str, Any]:
        fields = {k: v for k, v in body.model_dump(exclude={"archived"}).items() if v is not None}
        if body.archived is not None:
            fields["archived_at"] = now_iso() if body.archived else None
        topic = store.update_topic(topic_id, **fields)
        if body.archived:
            # 「不做了」= 这几篇笔记重新变成可选的。不清掉 triage 的话，进项会一直显示
            # 「已入选题池」，而那个选题已经不在看板上——点不进去，也加不回来。
            for path in topic.get("note_paths") or []:
                if (store.triage().get(path) or {}).get("status") == "topic":
                    store.set_triage(path, None)
            schedule_mod.drop_notes(store, topic_id)  # 进了回收站就不在日历上
            if topic.get("is_focus"):
                store.set_focus(None)
        elif body.archived is False:
            # 从回收站拖回来：笔记重新算「拿来做」，进项里不会再让他拿同一篇建第二个选题
            for path in topic.get("note_paths") or []:
                if not (store.triage().get(path) or {}).get("status"):
                    store.set_triage(path, "topic")
        return topic

    # -- 每周复盘定下的调整，写提纲时带上 -------------------------------------

    def latest_adjustments() -> list[str]:
        row = store._row("SELECT data FROM reviews WHERE state IN ('done', 'failed') AND data IS NOT NULL ORDER BY week DESC LIMIT 1")
        if not row:
            return []
        try:
            return [str(item) for item in (json.loads(row["data"]).get("next_week") or [])][:3]
        except (ValueError, AttributeError):
            return []

    def _save_transcript(job: dict[str, Any]) -> None:
        """A followed account's video, once torn down, becomes a readable note in 进项."""
        from . import transcripts

        video_id = job.get("video_id")
        video = store.video(video_id) if video_id else None
        if video is None:
            return
        account = store.account(video["account_id"])
        report = _load_report(video_id)
        if report is None:
            return
        text = transcripts.transcript_text(report)
        mine = bool(account["is_self"])
        who = account.get("nickname") or ("我" if mine else "对标")
        if mine:
            # 自己的视频不做时效和「太薄」筛选：这是我的内容库，每一条都要在，
            # 包括短的和没爆的——分析自己的风格时，失败的那几条同样是证据。
            folder = transcripts.MINE_FOLDER
        else:
            skip = transcripts.is_thin(
                title=video.get("title") or "",
                text=text,
                duration_seconds=(report.get("transcript") or {}).get("duration_seconds"),
                published_at=video.get("published_at"),
            )
            if skip:
                logger.info("transcript skipped %s: %s", video_id, skip)
                return
            folder = transcripts.FOLDER
        name = transcripts.note_name(published_at=video.get("published_at"), account=who, title=video.get("title") or "")
        markdown = transcripts.render(video=video, account=who, report=report, text=text)
        path = transcripts.write_note(vault.vault_root(vault_path()), name, markdown, folder=folder)
        logger.info("transcript saved %s", path)
        store.log_event("teardown", f"拆完了{'自己' if mine else who}的《{(video.get('title') or '')[:24]}》，文字稿落进 {folder}")

    worker.on_done = _save_transcript

    _load_report = places.load_report


    @app.post("/api/topics/{topic_id}/wechat-handoff")
    def handoff_to_wechat_pipeline(topic_id: int) -> dict[str, Any]:
        """把写好的文章送进 004_内容加工中，交给 作者 现成的公众号流程。

        路径不叫 /handoff：那个已经是研习室那条线的，同名会把它整个盖掉。
        """
        from . import handoff as handoff_mod, writer

        topic = store.topic(topic_id)
        draft = writer.read_draft(topic)
        if not draft:
            raise ValueError("这个选题还没有文章")
        try:
            result = handoff_mod.handoff(vault.vault_root(vault_path()), topic=topic, markdown=draft["markdown"])
        except handoff_mod.HandoffError as exc:
            raise ValueError(str(exc)) from exc
        store.log_event("handoff", f"《{result['title'][:28]}》已交接到 004_内容加工中，等配图排版", topic_id)
        return result

    # -- 触达：作者's first KPI, every platform in one number -----------------

    def platform_forms(topic: dict[str, Any] | None = None) -> dict[str, str]:
        """每个平台发什么。给了这条内容就按它上面定的（10/5：每条开始做时定好、能手动改），
        没给就是设置里的默认。打包、发布台、今天都读这一份。"""
        from . import reach

        return reach.forms_for(topic, store.settings()["platform_accounts"] or {})

    def _platform_rows(ready: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """每个平台：发布通道有没有、登录还在不在、数据是不是自动来的。

        三种状态，不是两种：已连接（有真实通道且登录没过期）、要登录（有通道但凭据旧了）、
        手动（根本没有通道）。一个永远亮不起来的灯就是骗人。
        """
        from . import publisher, reach

        opened = store.settings()["platform_accounts"] or {}
        me = store.self_account()
        ready = publisher.readiness(publisher_specs()) if ready is None else ready
        rows = []
        for key, label, auto in reach.PLATFORMS:
            style = reach.PLATFORM_STYLE.get(key, {})
            channel = ready.get(key)
            if channel is None:
                state, note = "manual", "手动发布"
                if key == "douyin" and me and me.get("status") == "error":
                    # 抖音没有发布通道，但「连没连上」看的是能不能读到作品：读不到就提示重新登录
                    state, note = "stale", "作品读不到了，多半是登录失效：重新登录抖音"
                if key == "wechat_mp":
                    # 真去问微信，不写死：40164 是 IP 白名单、40125 是 AppSecret，两件事要分清。
                    # 带 6 小时缓存——每次渲染都问一次会把微信每天的取令牌配额耗光。
                    from .extras.autopost import wechat

                    wx = wechat.state()
                    state = "ready" if wx["ok"] else "setup"
                    note = ("凭据没问题，图文发布通道还没做" if wx["ok"] else wx["note"])
            elif channel.get("blocked"):
                state, note = "blocked", channel["note"]
            elif channel.get("setup"):
                state, note = "setup", channel["note"]
            else:
                state = "stale" if channel["likely_expired"] else "linked"
                note = channel["note"]
            # 10/20 作者：「每一个 channel 连不上的话，给用户一个提示，让他去 reconnect」。
            # 文件和探测都说能用，但最近一次发布是登录类失败（B 站投稿页没走到填表），一样算断了
            if state == "linked" and channel is not None:
                last = store.last_publish_job(key)
                if last and last.get("state") == "failed":
                    diag = publisher.diagnose(key, last.get("message") or "", can_login=bool((publisher_specs().get(key) or {}).get("login_argv")))
                    if diag.get("fix") == "login":
                        state, note = "stale", diag["why"]
            row = {
                "key": key, "label": label, "mark": style.get("mark", label[:1]), "hue": style.get("hue", "#888"),
                "can_login": key == "douyin" or bool((publisher_specs().get(key) or {}).get("login_argv")),
                "auto_publish": channel is not None and not channel.get("blocked") and not channel.get("setup"), "auto_data": auto, "state": state, "note": note,
                "login_hint": (channel or {}).get("login_hint", ""),
                "handle": (opened.get(key) or {}).get("handle") or ("" if key != "douyin" else (me or {}).get("nickname") or ""),
                "on": (bool((opened.get(key) or {}).get("on")) or key == "douyin") and key not in edition.platforms_off(profile),
                "admin": copypack.PLATFORMS.get(key, {}).get("admin"),
            }
            rows.append(row)
        return rows

    # ---------------- 平台页（10/6 作者：左边按平台排，打包、发布拆进各平台页） ----------------
    from . import platform_page as pp_mod
    from . import reach

    PLATFORM_MODES = {"x": "article_publish", "bilibili": "upload", "youtube": "public", "wechat_mp": "draft"}
    PENDING_DAYS = 45  # 待发只看最近在做的；更早的旧内容走「汇总」里的补发

    def _pp_label(key: str) -> str:
        return (copypack.PLATFORMS.get(key) or {}).get("label", key)

    def _pp_locked(ap: dict[str, dict[str, Any]], k: str) -> bool:
        a = ap.get(k) or {}
        return bool(a.get("approved") and a.get("valid"))

    def _pp_ready(topic: dict[str, Any], key: str, form: str, ap: dict[str, dict[str, Any]], video: Path | None) -> tuple[bool, str]:
        """这一种形式现在能不能发，不能的话差什么。"""
        if form == "video":
            if video is None:
                return False, "还没有成片"
            if not _pp_locked(ap, "cover"):
                return False, "封面还没定稿"
            return True, ""
        if form == "text" and key in ("x", "wechat_mp", "miniprogram"):
            if not _pp_locked(ap, "article"):
                return False, "文章还没写好"
            if _evidence_pending(topic["id"]):
                return False, "证据图还没挑：要哪几张、还是都不要"
            hold = _proof_hold(topic["id"])
            if hold:
                return False, hold
            if key == "wechat_mp" and not _pp_locked(ap, "wx"):
                return False, "公众号排版还没好"
            return True, ""
        if form == "cards" and key == "xiaohongshu":
            return (True, "") if _pp_locked(ap, "xhs") else (False, "图文卡还没出")
        return True, ""

    def _pp_action(key: str, form: str) -> str:
        """机器发 / 进草稿箱 / 你来传。试用版没有机器代发（#526）。"""
        return pp_mod.action_for(key, form) if feature_on("autopost") else "hand"

    def _pp_form_rows(topic: dict[str, Any], key: str, forms: list[str], *, ap: dict[str, dict[str, Any]], video: Path | None) -> list[dict[str, Any]]:
        records = store.publish_records(topic["id"])
        posts = store.publish_posts(topic["id"])
        marks = store.backfill_marks()
        jobs = store.publish_jobs(topic["id"])
        mine = [j for j in jobs if j.get("platform") == key]
        now = datetime.now(timezone.utc)
        douyin_first = (key in pp_mod.AUTO_KEYS and not topic.get("published_video_id")
                        and "video" in (reach.forms_list(topic, store.settings()["platform_accounts"] or {}).get("douyin") or [])
                        and "douyin" not in store.publish_skips(topic["id"]))
        rows = []
        for form in forms:
            action = _pp_action(key, form)
            ready, why = _pp_ready(topic, key, form, ap, video)
            if ready and not _pp_locked(ap, "copy"):
                ready, why = False, "标题和文案还没定稿"
            job = publish_desk_mod.latest_job(jobs, key) if action in ("auto", "draft") else None
            row = {"form": form, "label": reach.FORM_LABEL.get(form, form),
                   "sent": pp_mod.sent_row(key, form, records=records, posts=posts, marks=marks, topic=topic),
                   "ready": ready, "why": why, "action": action, "action_label": pp_mod.ACTION_LABEL[action],
                   "upload_url": BW_UPLOAD.get(key) or (copypack.PLATFORMS.get(key) or {}).get("admin"),
                   "job": publish_desk_mod._job_view(job) if job else None}
            row["plan"], row["plan_note"] = pp_mod.auto_plan(row, mine, now, login_failed=lambda j: _pp_login_failed(key, j))
            if row["plan"] == "due" and form == "video" and douyin_first:
                # 顺序（10/4）：抖音先发，B 站、YouTube 在后。抖音发了、对上是哪条作品，下一轮就自己发
                row["plan"], row["plan_note"] = "wait", "等抖音先发"
            row["presentation"] = pp_mod.presentation_state(row)
            rows.append(row)
        return rows

    def _publication_warnings(*, platform: str | None = None, topic_id: int | None = None) -> list[dict[str, Any]]:
        """Read both sources: platform_posts hides legacy mirrors and cannot audit conflicts."""
        rows = []
        for topic in store.topics(include_archived=True):
            for source, publications in (("publish_posts", store.publish_posts(topic["id"]).values()),
                                         ("publish_records", store.publish_records(topic["id"]).values())):
                rows.extend({**record, "title": topic["title"], "source": source}
                            for record in publications if platform is None or record["platform"] == platform)
        warnings = pp_mod.duplicate_publications(rows)
        return [warning for warning in warnings if topic_id is None or topic_id in warning["topic_ids"]]

    def _pp_login_failed(key: str, job: dict[str, Any]) -> bool:
        from . import publisher

        if job.get("state") != "failed":
            return False
        spec = publisher_specs().get(key) or {}
        return publisher.diagnose(key, job.get("message") or "", can_login=bool(spec.get("login_argv")))["fix"] == "login"

    def _traffic() -> dict[str, list[str]]:
        """设置里各平台的流量话题。发的时候现读：新填的话题，已经打包好的那条也带上。"""
        return dict(store.settings().get("traffic_tags") or {})

    def _product_for(topic_id: int) -> dict[str, Any] | None:
        """这条带的产品（#590，「标题和封面」① 里选的）；发的时候现读，描述末尾加它的私信关键词或落地页。没挂产品块就是 None。"""
        fn = hooks.get("product_for_topic")
        return fn(topic_id) if fn and feature_on("products") else None

    def _pp_pending(key: str, *, awaiting_handoff: bool = False) -> list[dict[str, Any]]:
        """这个平台等着发的：标题定稿了（加工中「标题和封面」做完）、没结掉、这个平台开着、没标不发、还有形式没发出去的。"""
        from . import approvals, pack_auto

        accounts = store.settings()["platform_accounts"] or {}
        skip_video = store.settings().get("tracker_skip") or {}
        since = (date.today() - timedelta(days=PENDING_DAYS)).isoformat()
        out = []
        for t in store.topics():
            if t.get("closed_at") or (not t.get("video_project") and (t.get("updated_at") or "")[:10] < since):
                continue
            if not t.get("video_project") and t.get("published_video_id"):
                continue  # 拿去补发的旧视频：不是手上这条，走「汇总」里的补发
            if not (copypack.read_copy(drafts_root, t["id"]) or {}).get("platforms"):
                continue
            if key in store.publish_skips(t["id"]) or key in set(skip_video.get(str(t.get("published_video_id") or "")) or []):
                continue
            rel = _release_for(t) or {}
            st = _approval_state(t, rel)
            ap = approvals.status(st["folder"], st["fps"])
            forms = reach.forms_list(t, accounts)[key]
            video = final_video_path(t)
            rows = _pp_form_rows(t, key, forms, ap=ap, video=video)
            preparation = pack_auto.load(st["folder"])
            if preparation.get("handoff_required") and not awaiting_handoff:
                # 放进待发是一格一格放的：放过的格照常在，没放的格这里先等着，不挡别的格
                existing = {"published", "draft", "running", "awaiting_confirm", "unknown"}
                # 这个平台没开（不在打包页的格子里）：放不了它，别的格放过了就算放过
                on_lane = key in {lane["key"] for lane in _pack_lanes(t, ap)}
                waiting = [r for r in rows if r["presentation"]["state"] not in existing
                           and not (pack_auto.handed(preparation, pack_auto.lane_id(key, r["form"]), _lane_fingerprint(t, st, key, r["form"]))
                                    if on_lane else pack_auto.any_handed(preparation))]
                if len(waiting) == len(rows) and not any(r["presentation"]["state"] in existing for r in rows):
                    continue
                for r in waiting:
                    r.update(ready=False, why="等待在内容页点击发布", plan="wait", plan_note="等待确认发布")
                    r["presentation"] = pp_mod.presentation_state(r)
            # Invalidating preparation must not hide a draft or an unresolved delivery.
            # Rows stay unready, so the scheduler still cannot start a new publication.
            if not _pp_locked(ap, "copy") and not any(
                r["presentation"]["state"] in ("published", "running", "awaiting_confirm", "unknown", "draft", "failed")
                for r in rows
            ):
                continue
            if all(r["sent"] for r in rows):
                continue
            copy = copypack.read_copy(drafts_root, t["id"]) or {}
            own = publish_desk_mod.own_entry(copy.get("platforms"), key, publish_desk_mod.shared_entry(copy), _traffic(), _product_for(t["id"]))
            size = None
            if video is not None:
                try:
                    size = round(video.stat().st_size / 1_048_576)
                except OSError:
                    size = None
            out.append({"topic_id": t["id"], "title": t["title"], "video_id": t.get("published_video_id"),
                        "cover": (rel.get("cover_urls") or {}).get("portrait"), "video": video is not None, "video_mb": size,
                        "forms": forms, "default_forms": reach.default_forms(key, accounts),
                        "choices": [{"key": f, "label": reach.FORM_LABEL[f]} for f in reach.FORM_CHOICES.get(key, ("video",))],
                        "rows": rows, "copy": own, "updated_at": t.get("updated_at"), "pack_locked": _pp_locked(ap, "cover")})
        out.sort(key=lambda r: r["updated_at"] or "", reverse=True)
        return out

    def _pp_posts(key: str) -> list[dict[str, Any]]:
        """这个平台发过的每条内容和最近读到的数。抖音是它自己的作品列表（同步来的）。"""
        from .links import post_id

        if key == "douyin":
            me = store.self_account()
            if me is None:
                return []
            from .backfill import split_douyin_title

            vids = [v for v in store.videos(me["id"]) if not v["is_image_post"]]
            vids.sort(key=lambda v: v.get("published_at") or "", reverse=True)
            return [{"topic_id": None, "title": split_douyin_title(v.get("title") or "")["title"] or (v.get("title") or ""), "forms": ["video"], "url": f"https://www.douyin.com/video/{v['video_id']}",
                     "published_at": v.get("published_at"), "views": v.get("views"), "likes": v.get("likes")} for v in vids[:30]]
        posts = pp_mod.attach_views(key, store.platform_posts(key), store.latest_post_views(),
                                    store.latest_post_titles(key) if key == "xiaohongshu" else [], post_id)
        return pp_mod.group_rows(posts)[:30]

    def _platform_payload(key: str) -> dict[str, Any]:
        if key == "others":
            groups = [_platform_payload(k) for k in pp_mod.GROUPS["others"]]
            for g in groups:
                g["login"] = g["key"] in others_auto["login"]
                g["login_action"] = bool((publisher_specs().get(g["key"]) or {}).get("login_argv"))
            return {"key": "others", "label": pp_mod.GROUP_LABEL["others"], "groups": groups,
                    "auto": feature_on("autopost"), "table": _others_table(groups),
                    "publication_warnings": [w for g in groups for w in g["publication_warnings"]]}
        if key not in reach.PLATFORM_KEYS:
            raise HTTPException(status_code=404, detail="没有这个平台")
        rows = {p["key"]: p for p in _platform_rows()}
        p = rows[key]
        accounts = store.settings()["platform_accounts"] or {}
        today = date.today()
        totals, pulled, read_state, _last = _reach_totals(7, today)
        tkey = today.isoformat()
        today_views = totals.get(tkey, {}).get(key)
        all_today = sum(totals.get(tkey, {}).values())
        order = list(publish_desk_mod.SEQUENCE)
        return {
            **{k: p.get(k) for k in ("key", "label", "mark", "hue", "handle", "state", "note", "admin", "login_hint", "auto_publish", "auto_data", "on")},
            "core": key in reach.CORE,
            "how": _bw_how(key, ("hand", "文案和文件备好，你去传，传完点「发了」")),
            "today": {"views": today_views, "share": (round(100 * today_views / all_today) if all_today and today_views else None),
                      "manual": key != "douyin" and key not in pulled, "read": read_state.get(key), "stats_url": reach.STATS_URLS.get(key)},
            "days": [{"day": d, "views": totals[d].get(key)} for d in sorted(totals)],
            "pending": _pp_pending(key),
            "defaults": {"on": bool(p.get("on")), "handle": p.get("handle") or "", "forms": reach.default_forms(key, accounts),
                         "choices": [{"key": f, "label": reach.FORM_LABEL[f]} for f in reach.FORM_CHOICES.get(key, (reach.FORM.get(key, "video"),))],
                         "traffic_tags": list((store.settings().get("traffic_tags") or {}).get(key) or []),
                         "order": order.index(key) + 1 if key in order else None},
            "posts": _pp_posts(key),
            "publication_warnings": _publication_warnings(platform=key),
            "notes": list((store.settings().get("platform_notes") or {}).get(key) or []),
        }

    @app.get("/api/platform/counts")
    def platform_counts() -> dict[str, Any]:
        """左栏每个平台右边的数：等着发的条数。10/19 作者：六个平台一个格式，X 不再另报「等你勾」。
        B 站、YouTube 机器自己会发，只数要他动手的格子（和「其他三个」总表同一个数法）。"""
        out: dict[str, Any] = {}
        for key in ("douyin", "channels", "xiaohongshu", "x"):
            out[key] = len(_pp_pending(key))
        groups = [{"key": k, "pending": _pp_pending(k)} for k in pp_mod.GROUPS["others"]]
        table, login = _others_table(groups), set(others_auto["login"])
        out["others"] = pp_mod.needs_you(table, login)
        for key in ("bilibili", "youtube"):
            out[key] = pp_mod.needs_you([{**r, "cells": {key: r["cells"].get(key) or []}} for r in table], login)
        return out

    @app.get("/api/platform/{key}")
    def platform_page(key: str) -> dict[str, Any]:
        return _platform_payload(key)

    @app.put("/api/platform/{key}/settings")
    def platform_settings(key: str, body: dict[str, Any]) -> dict[str, Any]:
        """这个平台的默认：开没开、账号名、默认发哪几种。流量话题 10/8 起只在设置里改（PUT /api/settings）。"""
        if key not in reach.PLATFORM_KEYS:
            raise HTTPException(status_code=404, detail="没有这个平台")
        accounts = dict(store.settings()["platform_accounts"] or {})
        cur = dict(accounts.get(key) or {})
        if "on" in body:
            cur["on"] = bool(body["on"])
        if "handle" in body:
            cur["handle"] = str(body["handle"] or "").strip()
        if "forms" in body:
            wanted = [str(f) for f in (body.get("forms") or [])]
            if not wanted or any(f not in reach.FORM_CHOICES.get(key, ()) for f in wanted):
                raise ValueError("至少选一种，而且只能是 视频 / 图文 / 文字")
            cur["forms"] = list(dict.fromkeys(wanted))
            cur["form"] = cur["forms"][0]
        accounts[key] = cur
        store.update_settings({"platform_accounts": accounts})
        return _platform_payload(key)

    @app.post("/api/platform/{key}/notes")
    def platform_note_add(key: str, body: dict[str, Any]) -> dict[str, Any]:
        """记一条：哪条被删、哪条被限流，平台说了什么。以后看哪些话在这个平台不能说。"""
        if key not in reach.PLATFORM_KEYS:
            raise HTTPException(status_code=404, detail="没有这个平台")
        text = str(body.get("text") or "").strip()
        if not text:
            raise ValueError("写一句发生了什么")
        notes = dict(store.settings().get("platform_notes") or {})
        mine = list(notes.get(key) or [])
        nid = max([int(n.get("id") or 0) for n in mine] + [0]) + 1
        mine.insert(0, {"id": nid, "at": now_iso(), "text": text[:500], "title": str(body.get("title") or "")[:120],
                        "topic_id": body.get("topic_id"), "form": str(body.get("form") or "")})
        notes[key] = mine
        store.update_settings({"platform_notes": notes})
        return {"notes": mine}

    @app.delete("/api/platform/{key}/notes/{note_id}")
    def platform_note_drop(key: str, note_id: int) -> dict[str, Any]:
        notes = dict(store.settings().get("platform_notes") or {})
        mine = [n for n in (notes.get(key) or []) if int(n.get("id") or 0) != note_id]
        notes[key] = mine
        store.update_settings({"platform_notes": notes})
        return {"notes": mine}

    @app.post("/api/topics/{topic_id}/platform/{key}/sent")
    def platform_sent(topic_id: int, key: str, body: dict[str, Any]) -> dict[str, Any]:
        """他自己传完回来点「发了」（能贴链接）；点错了能撤回（undo）。形式级和平台级都记一笔，老的追踪表也认。"""
        topic = store.topic(topic_id)
        if key not in copypack.PLATFORMS or key not in reach.PLATFORM_KEYS:
            raise ValueError("未知平台")
        form = str(body.get("form") or reach.forms_list(topic, store.settings()["platform_accounts"])[key][0])
        if form not in reach.FORM_LABEL:
            raise ValueError("未知形式")
        url = str(body.get("url") or "").strip() or None
        if url and not url.startswith(("https://", "http://")):
            raise ValueError("链接需要以 https:// 开头")
        undo = bool(body.get("undo"))
        # 10/20 走查：小红书是昨晚发的、今天才来登记，复盘就把它算在今天、昨天照样扣分。补登可以说哪天发的
        at = None
        if body.get("day"):
            try:
                day_ = date.fromisoformat(str(body["day"]))
            except ValueError:
                raise ValueError("日期要写成 2026-10-19 这样")
            if day_ > date.today():
                raise ValueError("发布日期不能是以后")
            at = f"{day_.isoformat()}T12:00:00+08:00"
        store.set_publish_post(topic_id, key, form, published=not undo, url=url, at=at)
        if undo:
            # 平台级那条记录跟着剩下的形式走：还有别的形式发过就改成它，一种都没有了才删
            left = [r for (p, _f), r in store.publish_posts(topic_id).items() if p == key]
            if left:
                store.set_publish_record(topic_id, key, published=True, url=left[0].get("url"), form=left[0]["form"])
            else:
                store.set_publish_record(topic_id, key, published=False)
        else:
            store.set_publish_record(topic_id, key, published=True, url=url, form=form, at=at)
        vid = topic.get("published_video_id")
        if vid and key != "douyin" and form == "video":
            store.set_backfill_mark(str(vid), key, not undo)
        store.log_event("publish", f"《{topic['title'][:24]}》{'撤回' if undo else '发了'}：{_pp_label(key)} · {reach.FORM_LABEL.get(form, form)}", topic_id)
        return {"ok": True}


    # ---------------- 其他三个自己发（10/8 作者） ----------------
    # 「只要是主线下来的内容，全部都自动处理」：B 站、YouTube 做好了（成片 + 封面定稿）机器自己发；公众号做好了
    # （文章 + 排版定稿、证据图挑过）自己存进草稿箱，他只去后台扫码群发；群发之后草稿箱里那份没了，这里自己打 ✓。
    # 一个平台一次只发一条；登录过期就停下，页面上给扫码登录的按钮，登好了下一轮接着发。
    others_auto: dict[str, Any] = {"login": {}, "draft_checked": {}}
    OTHERS_TICK_SECONDS = 120
    LOGIN_RECHECK_SECONDS = 600

    def _others_table(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """关着的平台：表里只留发过的，不摆「马上自动发」（tick 也不发它）。"""
        since = (date.today() - timedelta(days=PENDING_DAYS)).isoformat()
        accounts = store.settings()["platform_accounts"] or {}
        live = [g if (accounts.get(g["key"]) or {}).get("on") else {**g, "pending": []} for g in groups]
        return pp_mod.summary_rows(live, {g["key"]: store.platform_posts(g["key"]) for g in groups}, since=since)


    app.state.others_auto = others_auto

    @app.get("/api/platforms")
    def platforms() -> dict[str, Any]:
        return {"platforms": _platform_rows()}

    def _skipped(video_id: str | None, topic_id: int | None) -> set[str]:
        """这一条哪些平台不发：补发工作台里标的（tracker_skip，按抖音作品）加上发布台上跳过的（publish_skips，按选题）。"""
        out = set((store.settings().get("tracker_skip") or {}).get(video_id) or []) if video_id else set()
        return out | (store.publish_skips(topic_id) if topic_id else set())

    def _on_keys() -> set[str]:
        from . import publisher

        return {p["key"] for p in _platform_rows(publisher.readiness(publisher_specs())) if p.get("on")}

    def _fresh(topic: dict[str, Any]) -> bool:
        """打包、发布页挂着的是「新的那条」：还没上抖音，或者抖音上是两周内发的。
        10/3：补发的老内容昨晚批量打包过，选题的更新时间是新的，但它们走补发工作台，不该挂在打包页上。"""
        vid = topic.get("published_video_id")
        video = store.video(vid) if vid else None
        if video is None:
            return True
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        return (video.get("published_at") or "") >= cutoff

    def _unfinished(topic: dict[str, Any], on_keys: set[str]) -> bool:
        """还没发完：没点「发布完毕」、没「不补发」，还有开着的平台既没发、也没标不发。
        发了算三种：发布台的记录、补发工作台里点的「发了」（backfill_marks）、抖音挂上了作品。"""
        vid = topic.get("published_video_id")
        if topic.get("closed_at") or (vid and vid in set(store.settings().get("tracker_cancel") or [])):
            return False
        done = set(store.publish_records(topic["id"])) | _skipped(vid, topic["id"])
        if vid:
            done |= {"douyin"} | store.backfill_marks().get(vid, set())
        return bool(on_keys - done)

    @app.get("/api/publish/desk")
    def publish_desk(topic_id: int | None = None) -> dict[str, Any]:
        """发布台：一条内容铺在所有平台上。哪条内容由 topic_id 定，没给就取最接近能发的那条。"""
        from . import approvals, board, copypack, handoff as handoff_mod, publish_desk, publisher

        cards = [c for c in get_board(None)["cards"] if not c.get("snoozed_until")]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        shipped = [{"id": t["id"], "title": t["title"], "stage": "shipped", "focus": False, "updated_at": t.get("updated_at")}
                   for t in store.topics() if board.is_shipped(t) and (t.get("updated_at") or "") >= cutoff]
        ordered = publish_desk.order_candidates(cards, shipped)
        candidates = []
        for c in ordered:
            n = len(store.publish_records(c["id"])) + (1 if c["stage"] == "shipped" and "douyin" not in store.publish_records(c["id"]) else 0)
            candidates.append({"id": c["id"], "title": c["title"], "stage": c["stage"], "stage_label": dict(board.MILESTONES).get(c["stage"], c["stage"]), "shipped_count": n})
        sendable = publish_desk.ready_to_publish(candidates)
        waiting = publish_desk.waiting_for(candidates) if not sendable else None
        # 9/29 作者：一条发完了就收起来；没指定哪条时，打包和发布只挑还有平台没发的那条。
        # 10/3：抖音发出只是第一个平台——还有开着的平台没发也没跳过、也没点「发布完毕」，就还没发完。
        on_keys = _on_keys()
        on_count = len(on_keys)
        unfinished = [c for c in sendable if (t := store.topic(c["id"])) and _fresh(t) and _unfinished(t, on_keys)]
        chosen = next((c for c in candidates if c["id"] == topic_id), None) if topic_id is not None else (unfinished[0] if unfinished else None)
        if topic_id is not None and chosen is None:
            # 不在候选里（归档了、或者太老）也允许直接打开——链接可能是从别处带过来的。
            t = store.topic(topic_id)
            chosen = {"id": t["id"], "title": t["title"], "stage": "shipped" if board.is_shipped(t) else "outline", "stage_label": "", "shipped_count": len(store.publish_records(t["id"]))}
        ready = publisher.readiness(publisher_specs())
        platform_rows = _platform_rows(ready)
        if chosen is None:
            empty = {"title": "", "body": "", "tags": []}
            # 手上没有要发的：告诉 作者 刚发完的是哪条（各平台链接）、下一条在哪（9/29：发布页不能一片空白）
            done = [c for c in sendable if c not in unfinished]
            finished = None
            if done:
                last = done[0]
                recs = store.publish_records(last["id"])
                finished = {"id": last["id"], "title": last["title"], "shipped_count": last["shipped_count"], "on_count": on_count,
                            "links": {k: {"url": v.get("url"), "label": (copypack.PLATFORMS.get(k) or {}).get("label", k)} for k, v in recs.items()}}
            return {"candidates": [], "waiting": waiting or publish_desk.waiting_for(candidates), "finished": finished,
                    "others": candidates, "topic": None, "video": None, "has_copy": False, "has_article": False, "entry": empty, "forms": platform_forms(),
                    "platforms": publish_desk.rows(platform_rows, specs=copypack.PLATFORMS, publishers=publisher_specs(), readiness=ready, records={}, jobs=[], entry=empty)}
        topic = store.topic(chosen["id"])
        copy = copypack.read_copy(drafts_root, topic["id"])
        entry = publish_desk.shared_entry(copy)
        video = final_video_path(topic)
        article = writer.read_draft(topic)
        handoff_done = False
        try:
            root = vault.vault_root(vault_path())
            handoff_done = (root / handoff_mod.FOLDER / handoff_mod.slug(topic["title"]) / handoff_mod.PACKAGE / "wechat-article.md").exists()
        except (vault.VaultError, OSError):
            pass
        rows = publish_desk.rows(platform_rows, specs=copypack.PLATFORMS, publishers=publisher_specs(), readiness=ready,
                                 records=store.publish_records(topic["id"]), jobs=store.publish_jobs(topic["id"]), entry=entry,
                                 douyin_linked=board.is_shipped(topic), handoff_done=handoff_done, skips=store.publish_skips(topic["id"]),
                                 copies=(copy or {}).get("platforms"), traffic=_traffic(), product=_product_for(topic["id"]))
        return {
            # 能发的才列出来；其余的留在 others 里，页面上折起来。
            "candidates": sendable,
            "waiting": waiting,
            "others": [c for c in candidates if c["id"] not in {s["id"] for s in sendable}],
            "topic": {**chosen, "published_video_id": topic.get("published_video_id"), "published_url": topic.get("published_url"), "closed_at": topic.get("closed_at"),
                      "video_project": topic.get("video_project"), "write_state": topic.get("write_state"), "write_error": topic.get("write_error")},
            "video": {"path": str(video), "name": video.name, "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
            "release": (release_info := _release_for(topic)),
            "approvals": approvals.status((st := _approval_state(topic, release_info))["folder"], st["fps"]),
            "has_copy": bool(entry["title"] or entry["body"]),
            "has_article": article is not None,
            "forms": platform_forms(topic),
            "next": publish_desk.next_step(rows),
            # 左边那张仿平台页面要填真的内容：文章标题、摘要、正文开头（纯文字）
            "article": _article_preview(article["markdown"]) if article else None,
            "entry": entry,
            "platforms": rows,
        }

    def _reach_totals(days: int, today: date) -> tuple[dict[str, dict[str, int]], list[str], dict[str, str], dict[str, dict[str, str]]]:
        """近 days 天（到 today 为止）每天每个平台涨了多少播放。一天 = 本地（北京）0 点到 24 点。

        返回 (totals, 自动读的平台, 今天读了没有, 每天每个平台最后一次读数的时间)。日结（day_close）和概览用同一份。"""
        from . import reach

        # 多取一天：窗口第一天也要有「前一天最后一次读数」当基准，不然老视频那天全算 0
        bound = reach.utc_bound(today - timedelta(days=days))
        me = store.self_account()
        last_read: dict[str, dict[str, str]] = {}

        def note(key: str, rows: list[dict[str, Any]]) -> set[str]:
            seen = set()
            for r in rows:
                d = reach.local_day(r["fetched_at"])
                seen.add(d)
                cur = last_read.setdefault(d, {}).get(key)
                if cur is None or str(r["fetched_at"]) > cur:
                    last_read[d][key] = str(r["fetched_at"])
            return seen

        snaps = store.account_snapshots(me["id"], bound) if me else []
        auto = reach.daily_views(snaps, days, today) if me else {}
        note("douyin", snaps)
        totals: dict[str, dict[str, int]] = {(today - timedelta(days=i)).isoformat(): {} for i in range(days)}
        for day_key, views in auto.items():
            if views:
                totals[day_key]["douyin"] = views
        synced = store.post_synced_at()
        # YouTube 在 作者 授权「查看」之后才开始有读数；有了就按自动算。
        pulled = [k for k in reach.PLATFORM_KEYS if k != "douyin" and (k in reach.AUTO_KEYS or k in synced)]
        read_state: dict[str, str] = {}
        for key in pulled:
            rows = store.post_snapshots(key, bound)
            seen = note(key, rows)
            for day_key, views in reach.daily_views(rows, days, today).items():
                # 那天读过就记下（哪怕涨了 0）；没读过才空着。9/29 以前涨 0 也显示「—」，看着像没读到。
                if day_key in totals and (views or day_key in seen):
                    totals[day_key][key] = views
            if key == "x":  # 10/12：X 后台每天 10:30 抄一次的曝光是准数，有就用它（接口算出来的只是近似）
                for day_key, views in _x_backend_days().items():
                    if day_key in totals:
                        totals[day_key]["x"] = views
            first = min(seen) if seen else None
            read_state[key] = ("baseline" if first == today.isoformat() else "read") if today.isoformat() in seen else "not_read"
        since = (today - timedelta(days=days - 1)).isoformat()
        for row in store.reach_entries(since):
            # 自动的平台以读到的为准；以前手填的旧数只在还没开始自动读的日子里算。
            if row["day"] in totals and row["platform"] not in totals[row["day"]]:
                totals[row["day"]][row["platform"]] = int(row["views"])
        return totals, pulled, read_state, last_read

    def _x_backend_days() -> dict[str, int]:
        """X 后台抄来的每天总曝光（verified_only=0）；只信抄的那天之前的日子（当天的还没过完）。"""
        try:
            from . import x_analytics
        except ImportError:  # 试用版不带 X 后台抄数
            return {}

        root = config_dir() / "x-analytics"
        data = x_analytics.latest(root)
        if not data:
            return {}
        pulled = max((f.name for f in root.iterdir() if f.is_dir() and (f / "daily.csv").exists()), default="")
        return {r["date"]: int(r["impressions"]) for r in data.get("daily", [])
                if r.get("verified_only") == 0 and r.get("impressions") is not None and r["date"] < pulled}

    @app.get("/api/reach")
    def get_reach(days: int = 14) -> dict[str, Any]:
        from . import reach

        days = min(max(days, 7), 90)
        today = date.today()
        me = store.self_account()
        totals, pulled, read_state, last_read = _reach_totals(days, today)
        synced = store.post_synced_at()
        accounts = store.settings()["platform_accounts"] or {}
        today_key = today.isoformat()
        return {
            **reach.summary(totals, today),
            "month": _month_reach(today),
            "platforms": [
                {"key": key, "label": label, "auto": auto_flag or key in pulled, "on": (bool((accounts.get(key) or {}).get("on")) or auto_flag or key in pulled) and key not in edition.platforms_off(profile),
                 "handle": (accounts.get(key) or {}).get("handle") or "", "today": totals[today_key].get(key),
                 # 自动的平台今天读了没有：baseline = 今天第一次读，只能当基准，明天起才算得出涨了多少
                 "read": read_state.get(key), "stats_url": reach.STATS_URLS.get(key),
                 # 9/29 注意力分层：主攻的 core=True，其余降权（页面上放右边、淡一点）
                 "core": key in reach.CORE,
                 # 发什么（视频 / 文字 / 图文）；能选的平台给出选项，设置里改，存进 platform_accounts[key].form
                 "form": reach.form_of(key, accounts), "form_choices": [{"key": f, "label": reach.FORM_LABEL[f]} for f in reach.FORM_CHOICES.get(key, ())]}
                for key, label, auto_flag in reach.PLATFORMS
            ],
            "douyin_synced_at": me["last_synced_at"] if me else None,
            "synced_at": {**synced, **({"douyin": me["last_synced_at"]} if me else {})},
            # 「今天到目前为止」截至哪一次读数（10/3：今天的数是 0 点以来涨的，到这次读数为止）
            "today_as_of": max((last_read.get(today_key) or {}).values(), default=None),
        }

    # -- 日结（dayclose.py）：每天 23:55 读一次、冻结那天的概览，存库 + 存文件，以后不改 -------------------
    day_close_lock = threading.Lock()

    def _freeze_day(day: date, kind: str) -> bool:
        """冻结 day 那一天。存过的不动。live 才存「各平台累计」（那是此刻的累计，补存的时候已经不是那天的了）。"""
        from . import dayclose, driver, reach
        from .paths import config_dir

        key = day.isoformat()
        with day_close_lock:
            if store.day_close(key):
                return False
            totals, _pulled, _read, last_read = _reach_totals(7, day)
            summ = reach.summary(totals, day)
            labels = {k: label for k, label, _ in reach.PLATFORMS}
            week = _week(driver.week_start(day), day + timedelta(days=1))  # 当天当成已经过完来算分
            kpi_day = next((d for d in week["days"] if d["day"] == key), None)
            matrix = None
            if kind == "live":
                try:
                    matrix = outbox_matrix(8)
                except Exception as exc:  # noqa: BLE001 - 累计表没了，触达照样存
                    logger.warning("day close matrix %s: %s", key, exc)
            data = {
                "day": key, "kind": kind, "kind_label": dayclose.KIND_LABEL[kind],
                "reach": {"total": summ["today"], "by_platform": totals.get(key, {}), "avg7": summ["avg7"], "pace30": summ["pace30"],
                          "labels": {k: labels.get(k, k) for k in totals.get(key, {})}},
                # 每个平台那天最后一次读数几点：没有 23:55 那次，就照实说最后一次是几点
                "last_reading": {k: dayclose.hhmm(v) for k, v in (last_read.get(key) or {}).items()},
                "kpi": {k: kpi_day.get(k) for k in ("ship", "rd", "dm", "xr", "mn", "shipped", "backfilled", "demerits")} if kpi_day else None,
                "matrix": matrix,
            }
            if not store.add_day_close(key, kind, data):
                return False
            try:
                dayclose.write_file(config_dir(), data)
            except OSError as exc:
                logger.warning("day close file %s: %s", key, exc)
            store.log_event("sync", f"日结存好了：{key} 触达 {summ['today']}（{dayclose.KIND_LABEL[kind]}）")
            return True

    def _freeze_missing(today: date) -> int:
        """今天以前没存过的日子都补上：上线前的从原始读数重算，之后错过的算补存。"""
        from . import dayclose, reach

        first = store.first_snapshot_at()
        if not first:
            return 0
        day, made = date.fromisoformat(reach.local_day(first)), 0
        while day < today:
            if not store.day_close(day.isoformat()):
                made += _freeze_day(day, dayclose.kind_for(day, today))
            day += timedelta(days=1)
        return made

    def _close_sync() -> None:
        """收尾那次读数：自己的号和各平台，不碰对标、不开读数小 App（半夜截 作者 的 Chrome）。和别的同步排队。"""
        from .cli import sync_everything

        def run() -> dict:
            if sync_all_fn is not None:
                return sync_all_fn(store)
            return sync_everything(store, cookie_path=cookie_path, creator_db=creator_db or Path("/nonexistent"), benchmarks=False)

        deadline = time.monotonic() + 600
        while not ops.run("all", run):
            if stop_auto.is_set() or time.monotonic() > deadline:
                logger.warning("day close: 10 分钟都有别的同步在跑，这次收尾不读了")
                return
            stop_auto.wait(15)
        deadline = time.monotonic() + 1200
        while ops.full_sync_running and not stop_auto.is_set() and time.monotonic() < deadline:
            stop_auto.wait(5)

    def _day_close_loop() -> None:
        from . import dayclose

        while not stop_auto.is_set():
            try:
                _freeze_missing(date.today())
            except Exception as exc:  # noqa: BLE001 - 下一轮再补
                logger.warning("day close catch-up: %s", exc)
            run_at, target = dayclose.plan(datetime.now().astimezone())
            # 一分钟醒一次看钟：Mac 睡着的时候 sleep 不走，醒来要按墙上的钟算
            while not stop_auto.is_set() and datetime.now().astimezone() < run_at:
                stop_auto.wait(60)
            if stop_auto.is_set():
                return
            try:
                if dayclose.on_time(datetime.now().astimezone(), target):
                    _close_sync()
                    _freeze_day(target, "live")
                else:
                    _freeze_day(target, "late")
            except Exception as exc:  # noqa: BLE001 - 明天启动时补存
                logger.warning("day close %s: %s", target, exc)

    @app.get("/api/day-close")
    def list_day_close(limit: int = 60) -> dict[str, Any]:
        from . import dayclose

        rows = store.day_closes(min(max(limit, 1), 400))
        return {"days": [{"day": r["day"], "kind": r["kind"], "kind_label": dayclose.KIND_LABEL.get(r["kind"], r["kind"]),
                          "total": (r["data"].get("reach") or {}).get("total"), "frozen_at": r["frozen_at"]} for r in rows],
                "close_at": dayclose.CLOSE_AT.strftime("%H:%M")}

    @app.get("/api/day-close/{day}")
    def get_day_close(day: str) -> dict[str, Any]:
        row = store.day_close(parse_day(day).isoformat())
        if row is None:
            raise HTTPException(status_code=404, detail="这天没有日结")
        return {**row["data"], "frozen_at": row["frozen_at"]}

    @app.post("/api/day-close/catch-up")
    def catch_up_day_close() -> dict[str, Any]:
        """把今天以前没存的日子补上（启动时也会自己做）。今天还没过完，不能冻结。"""
        return {"made": _freeze_missing(date.today())}

    @app.put("/api/reach")
    def put_reach(body: ReachBody) -> dict[str, Any]:
        from . import reach

        if body.platform not in reach.PLATFORM_KEYS or body.platform in reach.AUTO_KEYS or body.platform in store.post_synced_at():
            raise ValueError("这个平台的数据是自动读的，不用手填")
        parse_day(body.day)
        if body.views is not None and body.views < 0:
            raise ValueError("触达不能是负数")
        store.set_reach(body.day, body.platform, body.views)
        return get_reach()

    # -- 「今天」最上面：两条线 + 两个预期数（10/5 作者：「I can see the results, I can see it happen」）-------------
    READERS_FROM = date(2026, 9, 25)  # 这天起 B站 / X / 研习室 才自动读；更早只有抖音，画进去是一截假的低谷

    def _month_reach(today: date) -> dict[str, Any]:
        from . import followers

        days = max(14, (today - READERS_FROM).days + 1)
        totals, *_ = _reach_totals(min(days, 90), today)
        return followers.month_reach({d: sum(v.values()) for d, v in totals.items()}, today)

    @app.get("/api/today/results")
    def get_results() -> dict[str, Any]:
        """触达：每天的合计，只画过完的日子（今天早上的半截数天天像跳水）；粉丝：每次读数落一个点。"""
        from . import followers, reach

        today = date.today()
        days = min(90, max(14, (today - READERS_FROM).days + 1))
        totals, *_ = _reach_totals(days, today)
        series = [{"day": d, "total": sum(v.values())} for d, v in sorted(totals.items()) if READERS_FROM.isoformat() <= d < today.isoformat()]
        month = followers.month_reach({d: sum(v.values()) for d, v in totals.items()}, today)
        f = followers.summary(store.follower_counts(), today)
        latest = {r["platform"]: r for r in store.follower_counts()}  # 按 day 排，最后一行就是最近一次
        labels = {k: label for k, label, _ in reach.PLATFORMS}
        return {
            "reach": {"days": series, "month": month, "since": READERS_FROM.isoformat()},
            "followers": {**f, "manual": [{"key": k, "label": followers.LABELS[k], "value": (latest.get(k) or {}).get("followers"),
                                           "day": (latest.get(k) or {}).get("day")} for k in followers.MANUAL]},
            "labels": labels,
        }


    # -- 战况（10/12 作者：Wendy 是 full owner，背 KPI；目标他拍板，转化率是算出来的。算法在 kpi_board.py）------------
    def kpi_targets() -> dict[str, Any]:
        st = store.settings()
        return {"douyin": st["douyin_follow_target"], "x": st["x_follow_target"], "x_impressions": int(st["x_kpi"].get("impressions") or 0),
                "revenue": float(kpi_config()["revenue_monthly"])}

    def get_kpi() -> dict[str, Any]:
        from . import driver, kpi_board, reach

        today = date.today()
        totals, *_ = _reach_totals(max(kpi_board.CONV_WINDOW + 1, 21), today)
        me = store.self_account()
        try:
            row = store._rows("SELECT followers FROM x_followers_hourly ORDER BY at DESC LIMIT 1")
        except sqlite3.Error:
            row = []
        money = None
        if feature_on("consults"):
            labels = {s["key"]: s["label"] for s in money_sources()}
            money = driver.month_money(store.revenue(today.replace(day=1).isoformat()), today, target=float(kpi_config()["revenue_monthly"]), labels=labels)
        since = (today - timedelta(days=31)).isoformat()
        notes = [{"day": r["day"], "note": r["reason"] or ""} for r in store.driver_log(since, "money")]
        notes += [{"day": r["day"], "note": f"收了 ¥{float(r['amount']):,.0f}"} for r in store.revenue(since)]
        board = kpi_board.build(today=today, followers=store.follower_counts(), views=totals, targets=kpi_targets(),
                                x_now=int(row[0]["followers"]) if row else None, videos=store.videos(me["id"]) if me else [],
                                creator=_creator_rows(creator_db), money=money, money_notes=notes, local_day=reach.local_day)
        return {**board, "targets": kpi_targets()}

    @app.get("/api/kpi")
    def api_kpi() -> dict[str, Any]:
        return get_kpi()

    @app.put("/api/kpi/targets")
    def put_kpi_targets(body: KpiTargetsBody) -> dict[str, Any]:
        """改目标：只改终点（到哪天、到多少），起点是定下来那天的数，不跟着动。"""
        changes: dict[str, Any] = {}
        if body.douyin_end is not None or body.douyin_end_day:
            changes["douyin_follow_target"] = {k: v for k, v in (("end", body.douyin_end), ("end_day", body.douyin_end_day)) if v not in (None, "")}
        if body.x_end is not None or body.x_end_day:
            changes["x_follow_target"] = {k: v for k, v in (("end", body.x_end), ("end_day", body.x_end_day)) if v not in (None, "")}
        if body.x_impressions is not None:
            changes["x_kpi"] = {**store.settings()["x_kpi"], "impressions": body.x_impressions}
        if body.revenue is not None:
            if body.revenue < 0:
                raise ValueError("收入目标不能是负数")
            changes["kpi"] = {**(store.settings().get("kpi") or {}), "revenue_monthly": body.revenue}
        if changes:
            store.update_settings(changes)
            store.log_event("kpi", "改了 KPI 目标：" + "、".join(changes))
        return get_kpi()

    # -- 「今天」下半页（10/5 作者：「感觉有点空荡荡」「我今天明明完成了任务，也没有地方可以点」）-------------
    # 今天这一条（走到哪一步、下一步、发了就 ✓）、本月咨询几单（钱）、接下来 3 条备好没有（明天会不会断）。
    STEPS = (("outline", "骨架"), ("record", "录"), ("edit", "剪"), ("ready", "标题封面"), ("shipped", "发出"))
    ship_check: dict[str, Any] = {"at": None, "state": None, "error": None}  # 「我发了」那次核对：running / done / failed

    def _step_of(card: dict[str, Any] | None, shipped: bool) -> int:
        if shipped:
            return len(STEPS) - 1
        keys = [k for k, _ in STEPS]
        stage = (card or {}).get("stage")
        if stage == "outline" and (card or {}).get("has_outline"):
            return 0  # 骨架写了，他退回来要改：还在骨架这一步
        return keys.index(stage) if stage in keys else 0

    def _money_home(today: date) -> dict[str, Any] | None:
        """今天页的钱那一格：本月收入（结果）+ 今天的变现动作（算分）。"""
        from . import driver

        if not feature_on("consults"):
            return None
        kpi = kpi_config()
        sources = money_sources()
        month_start = today.replace(day=1).isoformat()
        m = driver.month_money(store.revenue(month_start), today, target=float(kpi["revenue_monthly"]), labels={s["key"]: s["label"] for s in sources})
        how = money_how(today.isoformat()).get(today.isoformat(), [])
        return {**m, "sources": sources, "action": {"done": bool(how), "how": how}, "scored": kpi["money_started"] <= today.isoformat() < kpi.get("money_ended", "9999"),
                "rows": [r for r in store.revenue(month_start)][-8:]}

    @app.get("/api/today/home")
    def get_today_home() -> dict[str, Any]:
        from . import reach as reach_mod

        today = date.today()
        tkey = today.isoformat()
        t = get_today()
        board = get_board(None)
        cards = {c["id"]: c for c in board["cards"]}
        ship = t["ship"]
        notes = t["ship"]["notes"]
        shipped = bool(ship.get("done"))
        nxt = ship.get("next") or {}
        # 今天发了：就是发出去的那条。没发：「下一步」指着哪条就是哪条（和 Wendy 说的同一件），这样标题和按钮永远对得上
        topic = ship.get("topic") if shipped else None
        if shipped and topic is None:  # 发了，但没对上哪个选题：就写抖音上那条的标题
            titles = next((d.get("shipped") for d in t["week"]["days"] if d["day"] == tkey), None) or ["今天的新视频"]
            topic = {"id": None, "title": titles[0]}
        if topic is None and nxt:
            m = re.match(r"(?:work|pack|publish|platform/\w+)/(\d+)", nxt.get("go") or "")
            tid = int(m.group(1)) if m else None
            if tid in cards:
                topic = {"id": tid, "title": cards[tid]["title"]}
            elif tid is not None:
                try:
                    topic = {"id": tid, "title": store.topic(tid)["title"]}
                except StoreError:
                    topic = None
            elif (nxt.get("key") or "").startswith("note:"):
                n = next((x for x in notes if f"note:{x['id']}" == nxt["key"]), None)
                topic = {"id": None, "title": n["text"]} if n else None
        card = cards.get((topic or {}).get("id"))
        week = t["week"]
        month_new = sum(len(d.get("shipped") or []) for w in _month(today, today)["weeks"] for d in w["days"] if d["day"][:7] == tkey[:7])
        focus = None
        if topic:
            focus = {"topic_id": topic.get("id"), "title": topic["title"], "step": _step_of(card, shipped), "steps": [label for _, label in STEPS],
                     "has_outline": bool((card or {}).get("has_outline")), "shipped": shipped, "next": ship.get("next")}
        # 接下来 3 条：「接下来要拍的」按顺序一天一条摆出来的（和月历同一套），今天那条不算
        queue = _queue_days(today, notes)
        upcoming = []
        for day in sorted(queue):
            if day <= tkey or len(upcoming) == 3:
                continue
            n = queue[day]
            c = cards.get(n.get("topic_id"))
            has_script = bool(n.get("topic_id")) and schedule_mod.script_path(drafts_root, n["topic_id"]).is_file()
            ok = bool(c and c.get("has_outline")) or has_script
            upcoming.append({"day": day, "title": n["text"], "topic_id": n.get("topic_id"), "ready": ok,
                             "why": ("稿子准备好了" if has_script else "骨架写好了") if ok else ("还没建成选题" if not n.get("topic_id") else "还没准备")})
        rows = _consult_rows()
        month = [r for r in rows if (r.get("day") or "")[:7] == tkey[:7]]
        return {
            "focus": focus,
            "streak": t["streak"], "month_new": month_new, "week_new": week.get("new_videos"), "week_target": week.get("new_target"),
            "consults": {"count": len(month), "month": today.month, "latest": ({"name": month[0]["name"], "day": month[0]["day"]} if month else None)}
            if feature_on("consults") else None,
            "money": _money_home(today),
            "upcoming": upcoming,
            # 今天点过「我发了」的那次核对；昨天的不算
            "check": dict(ship_check) if ship_check["at"] and reach_mod.local_day(ship_check["at"]) == tkey else None,
        }

    @app.post("/api/today/check-shipped")
    def check_shipped() -> dict[str, Any]:
        """他点「我发了」：马上同步一次自己的抖音号。看到了，月历今天那格就变绿；自己点一下不算，工作台看到才算。"""
        me = store.self_account()
        if not me:
            raise ValueError("还没加自己的抖音号")
        last = ship_check["at"]
        if last and ship_check["state"] != "failed" and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 120:
            return {"started": False, "message": "两分钟内刚看过一次，稍等再点"}
        def run() -> dict:
            try:
                result = _sync_and_queue(me["id"])
                ship_check.update(state="done", error=None)
                return result
            except Exception as exc:  # noqa: BLE001 - 页面上要说出来为什么没核对成
                ship_check.update(state="failed", error=str(exc)[:200])
                raise

        before = dict(ship_check)
        ship_check.update(at=now_iso(), state="running", error=None)  # 先标上：线程可能比这行还快跑完
        started = ops.run(me["id"], run)
        if not started:
            ship_check.update(before)
        return {"started": started, "message": "去抖音看一眼，半分钟左右" if started else "抖音正在同步，等它跑完再点"}

    # -- the one video in production ----------------------------------------

    @app.post("/api/topics/{topic_id}/focus")
    def focus_topic(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if topic.get("archived_at"):
            raise ValueError("这条已经归档了")
        previous = store.focus_topic()
        _claim_focus(topic_id)
        swapped = previous and previous["id"] != topic_id
        store.log_event("focus", f"开始做《{topic['title'][:30]}》" + (f"，《{previous['title'][:20]}》放回选题池" if swapped else ""), topic_id)
        return {"topic": store.topic(topic_id), "previous": previous["title"] if swapped else None}

    @app.delete("/api/topics/{topic_id}/focus")
    def unfocus_topic(topic_id: int) -> dict[str, Any]:
        store.topic(topic_id)
        current = store.focus_topic()
        if current and current["id"] == topic_id:
            _guard_in_flight(topic_id, "放回选题池")
            store.set_focus(None)
            schedule_mod.drop_notes(store, topic_id)  # 10/6 正在做 = 今天：放回选题池就是不排了
            store.log_event("focus", f"《{current['title'][:30]}》放回了选题池", topic_id)
        return {"topic": store.topic(topic_id)}

    # -- 复刻 → 加工中第一步「你说一遍」（speak.py，10/4 作者，10/5 改成一个按钮）-----------------
    # 拆完的爆款可以直接入选题池；在选题池里点「复刻」开做。左边拆解报告，右边空白大框口播，
    # 可以删口水话（不改写），存进 Obsidian 的原始输出，后面的骨架只读他说的话。
    speak_running: set[int] = set()
    speak_lock = threading.Lock()

    _speak_dir = places.topic_dir

    def _speak_brief(topic_id: int) -> dict[str, Any] | None:
        from . import speak as speak_mod

        data = speak_mod.load(_speak_dir(topic_id))
        if not data:
            return None
        return {"mode": data.get("mode"), "mode_label": speak_mod.MODES.get(data.get("mode") or ""), "author": data.get("author"),
                "multiple": data.get("multiple"), "video_id": data.get("video_id"), "note_path": data.get("note_path"),
                "series": data.get("series")}


    def _oral_source(topic_id: int) -> dict[str, Any]:
        """口述页左边放的材料：日报带来的原文快照，或收藏、Clippings 的笔记；都没有就只有备注。"""
        topic = store.topic(topic_id)
        parts: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        if feature_on("dailies"):  # 试用版没有日报这一块
            from .extras.dailies import newsletter

            snapshots = newsletter.attached_sources(drafts_root, topic_id)
        for snap in snapshots:
            parts.append({"title": snap["title"], "url": snap.get("url"), "body": snap["body"][:6000]})
        mine = _raw_folder().strip("/") + "/"
        for rel in topic.get("note_paths") or []:
            if rel.startswith(mine):  # 他自己的笔记不是「别人的材料」
                continue
            try:
                note = vault.read_note(vault_path(), rel)
            except (vault.VaultError, OSError, ValueError):
                continue
            if note.get("body"):
                parts.append({"title": note["title"], "url": (note.get("meta") or {}).get("source"), "body": note["body"][:6000]})
        return {"memo": topic.get("memo") or "", "parts": parts[:3]}

    def _speak_view(topic_id: int) -> dict[str, Any]:
        from . import speak as speak_mod

        data = speak_mod.load(_speak_dir(topic_id))
        if data is None:
            raise HTTPException(status_code=404, detail="这条不是从拆解来的")
        with speak_lock:
            running = topic_id in speak_running
        view = {**data, "running": running, "mode_label": speak_mod.MODES.get(data.get("mode") or "")}
        if data.get("mode") == "oral":
            view["source"] = _oral_source(topic_id)
        if data.get("series"):
            found = next((s for s in _series_list() if s["folder"] == data["series"]), None)
            view["series_episodes"] = found["episodes"] if found else []
            view["episode"] = next((e["n"] for e in view["series_episodes"] if e["title"] == data.get("episode_title")), None)
        return view

    # -- 系列（series.py，10/5 作者）：003 下的「系列…」文件夹，系列.md 一行一集 ------------------
    # Obsidian 是正本：每次看选题池都对一遍——新写的标题进池子，删掉的（还没说、没开做的）拿掉。
    _raw_root = places.raw_root

    def _series_list() -> list[dict[str, Any]]:
        from .extras.series import series as series_mod

        try:
            return series_mod.all_series(_raw_root())
        except (ValueError, vault.VaultError, OSError):
            return []

    def _topic_series(topic: dict[str, Any]) -> tuple[str | None, str | None]:
        from . import speak

        data = speak.load(drafts_root / f"topic-{topic['id']}") or {}
        return data.get("series"), data.get("episode_title")

    def _topic_frames(topic: dict[str, Any]) -> dict[str, str]:
        from . import frames

        folder, title = _topic_series(topic)
        frame = frames.load_series_frame(folder)
        return {"series_frame": frame, "episode_material": frames.episode_material(frame, title or "")}

    # 内容框架是生成流程的设置，不依赖助手功能是否启用。
    from . import frames, outline as outline_mod

    def _frame_path(kind: str, key: str | None = None, folder: str | None = None) -> Path:
        if kind == "one":
            file = next((f["path"] for f in frames.layer_one_files() if f["key"] == key), None)
            if file:
                return Path(file)
        elif kind == "series" and folder in {s["folder"] for s in _series_list()}:
            return frames.series_frame_path(folder)
        raise ValueError("没有这个内容框架")

    def _frame_doc(kind: str, key: str | None = None, folder: str | None = None) -> dict[str, Any]:
        path = _frame_path(kind, key, folder)
        exists = path.is_file()
        body = path.read_text(encoding="utf-8") if exists else (
            frames.NEW_TEMPLATE.format(series_name=folder) if kind == "series" else ""
        )
        return {"name": path.name, "path": str(path).replace(str(Path.home()), "~", 1), "body": body, "exists": exists}

    @app.get("/api/frames")
    def get_frames() -> dict[str, Any]:
        return {"layer_one": [{**f, "path": f["path"].replace(str(Path.home()), "~", 1)}
                              for f in frames.layer_one_files()],
                "series": [{"folder": s["folder"], "episodes": len(s["episodes"]),
                            "has_frame": frames.series_frame_path(s["folder"]).is_file(),
                            "path": str(frames.series_frame_path(s["folder"])).replace(str(Path.home()), "~", 1)}
                           for s in _series_list()]}

    @app.get("/api/frames/doc")
    def get_frame_doc(kind: str, key: str | None = None, folder: str | None = None) -> dict[str, Any]:
        return _frame_doc(kind, key, folder)

    @app.put("/api/frames/doc")
    def put_frame_doc(body: FrameBody) -> dict[str, Any]:
        if not body.text.strip():
            raise ValueError("内容是空的")
        path = _frame_path(body.kind, body.key, body.folder)
        references = writing_rules.references_dir() if body.kind == "one" else None
        if references is not None:
            frames.save(Path(path.name), body.text, root=references)
        else:
            frames.save(path.relative_to(outline_mod.workflows_dir().absolute()), body.text)
        return _frame_doc(body.kind, body.key, body.folder)

    def _sync_series() -> list[dict[str, Any]]:
        """系列.md 里的每一集对上选题池里的一条（按系列 + 标题对）；返回每个系列、每集对上的选题。"""
        from . import speak as speak_mod

        found = _series_list()
        if not found:
            return []
        episodes: dict[tuple[str, str], dict[str, Any]] = {}
        for topic in store.topics(include_archived=True):
            data = speak_mod.load(_speak_dir(topic["id"]))
            if data and data.get("series"):
                episodes.setdefault((data["series"], data.get("episode_title") or ""), {**topic, "speak": data})
        me = store.self_account()
        for item in found:
            titles = {e["title"] for e in item["episodes"]}
            for ep in item["episodes"]:
                topic = episodes.get((item["folder"], ep["title"]))
                if topic is None:
                    created = store.create_topic(ep["title"], formats="video", account_id=me["id"] if me else None,
                                                 memo=f"{item['folder']} · 第 {ep['n']} 集")
                    data = {"series": item["folder"], "episode_title": ep["title"], "title": ep["title"], "mode": None, "dictation": ""}
                    speak_mod.save(_speak_dir(created["id"]), data)
                    store.log_event("pool", f"《{ep['title'][:30]}》进了选题池（{item['folder']}）", created["id"])
                    topic = episodes[(item["folder"], ep["title"])] = {**created, "speak": data}
                ep["topic_id"] = topic["id"]
                ep["said"] = bool(topic["speak"].get("note_path"))
                ep["archived"] = bool(topic.get("archived_at"))
            # 在 Obsidian 里删掉或改掉的标题：还没说、没开做的那条就拿掉（说过的留着，那是他的话）
            for (folder, title), topic in episodes.items():
                if folder == item["folder"] and title not in titles and not topic.get("archived_at") \
                        and not topic["speak"].get("note_path") and not topic.get("is_focus"):
                    store.update_topic(topic["id"], archived_at=now_iso())
        return found


    def _start_oral(topic_id: int) -> dict[str, Any]:
        """10/13 作者：别人的材料进池后，在排期里多一步「口述」。没有拆解也能说；说的时候不抢「正在做」。"""
        from . import speak as speak_mod

        topic = store.topic(topic_id)
        if topic.get("archived_at"):
            raise ValueError("这条已经归档了")
        folder = _speak_dir(topic_id)
        data = speak_mod.load(folder) or {"title": topic["title"], "dictation": ""}
        data["mode"] = "oral"
        speak_mod.save(folder, data)
        store.log_event("pool", f"口述《{topic['title'][:30]}》", topic_id)
        return {"topic": store.topic(topic_id), "speak": _speak_view(topic_id)}

    @app.post("/api/schedule/oral")
    def new_oral(body: dict[str, Any]) -> dict[str, Any]:
        """排期选题池里「+ 口述一条」：没有任何材料，直接对着说。先建一个选题，标题在口述页里改。"""
        title = str(body.get("title") or "").strip()[:60] or "新口述"
        me = store.self_account()
        topic = store.create_topic(title, formats="video", account_id=me["id"] if me else None, memo="直接口述，没有别人的材料")
        store.log_event("pool", f"《{title[:30]}》从口述进了选题池", topic["id"])
        return _start_oral(topic["id"])

    @app.post("/api/topics/{topic_id}/replicate")
    def start_replicate(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """「复刻」：开始做这条（设为焦点），第一步是「你说一遍」。10/5 起只有一个按钮，mode 不传就是 copy。"""
        from . import speak as speak_mod

        mode = str(body.get("mode") or "copy")
        if mode not in speak_mod.MODES:
            raise ValueError("不认识这种复刻")
        folder = _speak_dir(topic_id)
        data = speak_mod.load(folder)
        if mode == "oral":
            return _start_oral(topic_id)
        if data is None:
            raise ValueError("这条不是从拆解来的")
        data["mode"] = mode
        speak_mod.save(folder, data)
        focused = focus_topic(topic_id)
        store.log_event("focus", f"{speak_mod.MODES[mode]}《{store.topic(topic_id)['title'][:30]}》", topic_id)
        return {**focused, "speak": _speak_view(topic_id)}

    @app.get("/api/topics/{topic_id}/speak")
    def get_speak(topic_id: int) -> dict[str, Any]:
        return _speak_view(topic_id)

    @app.put("/api/topics/{topic_id}/speak")
    def put_speak(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """存他说的（语音输入的一大段，边说边存）。undo：撤回上一次删口水话。"""
        from . import speak as speak_mod

        folder = _speak_dir(topic_id)
        data = speak_mod.load(folder)
        if data is None:
            raise HTTPException(status_code=404, detail="这条不是从拆解来的")
        if body.get("undo") and data.get("before_clean") is not None:
            data["dictation"], data["before_clean"], data["result"] = data["before_clean"], None, None
        elif "dictation" in body:
            text = str(body.get("dictation") or "")[:20000]
            if text != data.get("dictation"):  # 删完又自己改了：撤回就不该再把这些改动冲掉
                data["before_clean"], data["result"] = None, None
            data["dictation"] = text
        speak_mod.save(folder, data)
        return _speak_view(topic_id)

    @app.post("/api/topics/{topic_id}/speak/arrange")
    def arrange_speak(topic_id: int) -> dict[str, Any]:
        """删口水话：后台跑，页面轮询；先记结果再放开占位（#390 的教训）。不改写，顺序和换行照他说的。"""
        from . import speak as speak_mod

        folder = _speak_dir(topic_id)
        data = speak_mod.load(folder)
        if data is None:
            raise HTTPException(status_code=404, detail="这条不是从拆解来的")
        if not (data.get("dictation") or "").strip():
            raise ValueError("还没说话：先在大框里说一遍")
        with speak_lock:
            if topic_id in speak_running:
                return {"started": False, "message": "正在整理"}
            speak_running.add(topic_id)
        data.update(state="running", error=None)
        speak_mod.save(folder, data)
        snapshot = data["dictation"]

        def run() -> None:
            result, error = None, None
            try:
                result = speak_mod.clean(snapshot, speak_fn or speak_mod.cli_ask)
            except Exception as exc:  # noqa: BLE001 - 页面显示
                logger.warning("speak arrange %s failed: %s", topic_id, exc)
                error = str(exc)[:300] or type(exc).__name__
            try:
                fresh = speak_mod.load(folder) or data
                if result is not None and fresh.get("dictation") != snapshot:
                    error = "删的时候你又改了大框，没套用：再点一次「删口水话」"
                elif result is not None:
                    fresh.update(before_clean=snapshot, dictation=result.pop("text"), result=result)
                fresh.update(state="failed" if error else "done", error=error)
                speak_mod.save(folder, fresh)
            finally:
                with speak_lock:
                    speak_running.discard(topic_id)

        threading.Thread(target=run, name=f"speak-{topic_id}", daemon=True).start()
        return {"started": True, "message": "在删口水话：不改你的字，一般半分钟"}

    @app.post("/api/topics/{topic_id}/speak/save")
    def save_speak(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """存进 Obsidian 的原始输出（只有他说的话），挂到这条选题上，接着写骨架。"""
        from . import speak as speak_mod

        folder = _speak_dir(topic_id)
        data = speak_mod.load(folder)
        if data is None or not (data.get("dictation") or "").strip():
            raise ValueError("还没说话：先在右边大框里说一遍")
        topic = store.topic(topic_id)
        title = str(body.get("title") or "").strip()[:60] or topic["title"]
        raw_root = _raw_root()
        root = vault.vault_root(vault_path())
        if data.get("series"):
            # 系列里的一集：存进系列文件夹，文件名「编号 标题」；标题跟着 系列.md 走，这里不改名
            from .extras.series import series as series_mod

            title = topic["title"]
            series_dir = raw_root / data["series"]
            n = next((e["n"] for s in _series_list() if s["folder"] == data["series"]
                      for e in s["episodes"] if e["title"] == data.get("episode_title")), 0)
            written = speak_mod.write_note(series_dir, series_mod.episode_note_name(n, title), speak_mod.series_note_markdown(data, n, title))
            memo = f"{data['series']} · 第 {n} 集。内容全是 作者自己说的，在原始输出「{data['series']}/{written.name}」里。"
        elif data.get("mode") == "oral":
            parts = _oral_source(topic_id)["parts"]
            source = (parts[0].get("url") or "") if parts else ""
            source = source or next(iter(topic.get("note_paths") or []), "")
            written = speak_mod.write_note(raw_root, title, speak_mod.oral_note_markdown(data, title, source))
            memo = (f"{topic.get('memo') or ''}".strip() + "\n" if topic.get("memo") else "") + \
                f"内容全是 作者自己说的，在原始输出「{written.name}」里" + ("；别人的材料只是话题，里面的话一句都没用。" if parts else "。")
        else:
            written = speak_mod.write_note(raw_root, title, speak_mod.note_markdown(data, title))
            # 选题的备注也说清：结构是借的，内容是他自己说的（骨架会读备注）
            memo = (f"照 {data.get('author') or '对标博主'}《{speak_mod._clean_title(data.get('title') or '')}》的分段结构做（复刻）。"
                    f"内容全是 作者自己说的，在原始输出「{written.name}」里；对标博主的原话一句都没用。")
        rel = str(written.relative_to(root))
        paths = [p for p in (topic.get("note_paths") or []) if p != data.get("note_path")] + [rel]
        store.update_topic(topic_id, note_paths=paths, memo=memo, **({"title": title} if title != topic["title"] else {}))
        data["note_path"] = rel
        speak_mod.save(folder, data)
        store.log_event("pool", f"《{title[:30]}》说完了，存进原始输出：{written.name}", topic_id)
        topic = store.topic(topic_id)
        start_script = getattr(app.state, "topic_script_start", None)
        hold = _prep_hold(topic_id)
        if hold:  # 话存好了，稿子等前一条发完再出
            return {"path": rel, "name": written.name, "script": {"started": False, "message": hold}, "outline": None}
        if _script_runner() and start_script and _own(topic):
            # 10/12 作者：说完了就是他自己的话，不再写骨架、密度，直接拿原话走第一轮
            return {"path": rel, "name": written.name, "script": start_script(topic_id, "note"), "outline": None}
        started = start_outline(topic_id)
        return {"path": rel, "name": written.name, "outline": started}

    @app.post("/api/topics/{topic_id}/close")
    def close_topic(topic_id: int) -> dict[str, Any]:
        """「发布完毕」：这条结了，从加工中拿掉。还没发的平台（比如小宇宙）以后照样能在发布台补。"""
        topic = store.topic(topic_id)
        if not store.publish_records(topic_id) and not topic.get("published_video_id"):
            raise ValueError("一个平台都还没发，先发出去一个再点「这条发完了」")
        if topic.get("is_focus"):
            store.set_focus(None)
        topic = store.update_topic(topic_id, closed_at=now_iso())
        store.log_event("close", f"《{topic['title'][:30]}》发布完毕，从加工中拿掉", topic_id)
        return {"topic": topic}

    @app.delete("/api/topics/{topic_id}/close")
    def reopen_topic(topic_id: int) -> dict[str, Any]:
        topic = store.update_topic(topic_id, closed_at=None)
        store.log_event("close", f"《{topic['title'][:30]}》撤销发布完毕，放回加工中", topic_id)
        return {"topic": topic}

    @app.post("/api/topics/{topic_id}/snooze")
    def snooze_topic(topic_id: int, body: SnoozeBody) -> dict[str, Any]:
        store.topic(topic_id)
        days = min(max(body.days, 1), 90)
        _guard_in_flight(topic_id, "暂缓")
        return {"topic": store.update_topic(topic_id, snoozed_until=(date.today() + timedelta(days=days)).isoformat(), is_focus=0)}

    @app.delete("/api/topics/{topic_id}/snooze")
    def unsnooze_topic(topic_id: int) -> dict[str, Any]:
        store.topic(topic_id)
        return {"topic": store.update_topic(topic_id, snoozed_until=None)}

    @app.post("/api/topics/{topic_id}/stage")
    def set_stage(topic_id: int, body: StageBody) -> dict[str, Any]:  # noqa: D401
        """Step the focus video back to 提纲 (or clear that override) — the pipeline can move backwards."""
        store.topic(topic_id)
        if body.stage not in (None, "outline"):
            raise ValueError("只能退回到提纲")
        title = store.topic(topic_id)["title"][:30]
        store.log_event("stage", f"《{title}》{'退回提纲重写' if body.stage == 'outline' else '提纲改好了，回到录制'}", topic_id)
        return {"topic": store.update_topic(topic_id, manual_stage=body.stage)}

    # -- article line ------------------------------------------------------

    def _write_topic(topic_id: int, instruction: str = "") -> None:
        failed = None
        try:
            topic = store.topic(topic_id)
            result = writer.write_article(
                topic,
                vault_raw=vault_path(),
                drafts_dir=drafts_root,
                transcript=_transcript_for_article(topic),
                instruction=instruction,
                skill=store.settings()["writer_skill"],
                **({"write_fn": write_fn} if write_fn else {}),
            )
            current = store.topic(topic_id)
            store.update_topic(
                topic_id,
                article_path=result["article_path"],
                write_state=None,
                write_error=None,
                status="drafting" if current["status"] == "todo" else current["status"],
            )
            # 9/29 起写完不自动配图：作者 先看文章、定稿，再配（打包页定稿文章时开始配）。还要重写的话不白画一轮。
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("writing topic %s failed: %s", topic_id, exc)
            failed = str(exc)[:300] or type(exc).__name__
            store.update_topic(topic_id, write_state="failed", write_error=failed)
        finally:
            _pack_job_done(topic_id, "article", failed, slot=topic_id)

    @app.post("/api/topics/{topic_id}/write")
    def start_write(topic_id: int, body: WriteBody | None = None) -> dict[str, Any]:
        topic = store.topic(topic_id)
        instruction = (body.instruction if body else "") or ""
        if topic.get("article_path") and not instruction.strip():
            # 9/29 作者：重写要知道会怎么不一样——已经写过的，重写必须说这次要怎么改
            raise HTTPException(status_code=400, detail="重写要先说这次要怎么改")
        if topic["formats"] == "video":
            # 视频拍完了，文字版也能发（研习室、X）。点了写文章就是要写，不再挡他。
            store.update_topic(topic_id, formats="both")
            store.log_event("stage", f"《{topic['title'][:24]}》加了文章版", topic_id)
        with writing_lock:
            if topic_id in writing:
                return {"started": False, "message": "这篇正在写"}
            writing.add(topic_id)
        store.update_topic(topic_id, write_state="running", write_error=None)
        threading.Thread(target=_write_topic, args=(topic_id, instruction), name=f"write-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写了，一般 1–5 分钟"}

    def _outline_topic(topic_id: int, chain: bool = True) -> None:
        from . import outline

        try:
            topic = store.topic(topic_id)
            result = outline.write_outline(
                topic, vault_raw=vault_path(), drafts_dir=drafts_root,
                **_topic_frames(topic), **({"write_fn": outline_fn} if outline_fn else {})
            )
            store.update_topic(topic_id, outline_path=result["outline_path"], outline_state=None, outline_error=None, manual_stage=None)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:30]}》的骨架写好了", topic_id)
            if feature_on("qa"):
                _run_qa(topic_id)
            if chain and feature_on("coupon") and not (_script_runner() and _own(store.topic(topic_id))):
                _start_coupon(topic_id)  # 10/2 作者：骨架后面接着出付息稿；10/12：已经有他自己的话的，骨架是他点「更多」要的，不接密度
        except Exception as exc:  # noqa: BLE001 - shown on the topic card
            logger.warning("skeleton topic %s failed: %s", topic_id, exc)
            store.update_topic(topic_id, outline_state="failed", outline_error=str(exc)[:300] or type(exc).__name__)
            store.log_event("outline", f"《{store.topic(topic_id)['title'][:24]}》骨架生成失败：{str(exc)[:60]}", topic_id)
        finally:
            with writing_lock:
                writing.discard(-topic_id)

    # -- 付息稿（10/2 作者：观众买了你的国债——开头发债、每 10 秒付息、最后兑付本金）--------------------
    coupon_errors: dict[int, str] = {}

    def _coupon_topic(topic_id: int) -> None:
        from . import coupon, outline

        try:
            topic = store.topic(topic_id)
            sk = outline.read_outline(topic)
            coupon.write_coupon(topic, skeleton=(sk or {}).get("markdown", ""), vault_raw=vault_path(), drafts_dir=drafts_root,
                                **_topic_frames(topic), **({"write_fn": coupon_fn} if coupon_fn else {}))
            store.log_event("outline", f"《{topic['title'][:30]}》的密度排好了", topic_id)
        except Exception as exc:  # noqa: BLE001 - shown on the tab
            logger.warning("coupon topic %s failed: %s", topic_id, exc)
            coupon_errors[topic_id] = str(exc)[:300] or type(exc).__name__
        finally:
            with writing_lock:
                writing.discard(60_000 + topic_id)

    def _start_coupon(topic_id: int) -> bool:
        from . import coupon

        try:
            coupon.load_framework()  # 框架文件不在：不起线程，等他放好了再点
        except Exception as exc:  # noqa: BLE001
            coupon_errors[topic_id] = str(exc)[:300]
            return False
        with writing_lock:
            if 60_000 + topic_id in writing:
                return False
            writing.add(60_000 + topic_id)
        coupon_errors.pop(topic_id, None)
        threading.Thread(target=_coupon_topic, args=(topic_id,), name=f"coupon-{topic_id}", daemon=True).start()
        return True

    @app.get("/api/topics/{topic_id}/coupon")
    def get_coupon(topic_id: int) -> dict[str, Any]:
        from . import coupon

        store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        return {"running": running, "error": coupon_errors.get(topic_id), "coupon": coupon.read_coupon(drafts_root, topic_id)}

    @app.post("/api/topics/{topic_id}/coupon")
    def start_coupon(topic_id: int) -> dict[str, Any]:
        from . import coupon

        topic = store.topic(topic_id)
        if not topic.get("outline_path"):
            raise ValueError("先写骨架，密度是照着骨架排的")
        _check_prep(topic_id)
        coupon.load_framework()
        if not _start_coupon(topic_id):
            return {"started": False, "message": "正在写"}
        return {"started": True, "message": "开始排密度，一般 1–3 分钟"}

    @app.put("/api/topics/{topic_id}/coupon")
    def put_coupon(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        from . import coupon

        store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("密度不能为空")
        path = drafts_root / f"topic-{topic_id}" / coupon.FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        return coupon.read_coupon(drafts_root, topic_id) or {}

    @app.post("/api/topics/{topic_id}/outline")
    def start_outline(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        _check_prep(topic_id)
        if topic["formats"] == "article":
            raise ValueError("这个选题只写文章；先把形式改成「视频」或「文章 + 视频」")
        # 框架文件在 Obsidian 里，作者 随时会改。先读一次，缺了就当场说清楚，
        # 而不是让线程在后台失败、他等两分钟才看到。
        outline_mod.load_framework()
        with writing_lock:
            if -topic_id in writing:
                return {"started": False, "message": "正在写"}
            writing.add(-topic_id)
        store.update_topic(topic_id, outline_state="running", outline_error=None)
        threading.Thread(target=_outline_topic, args=(topic_id,), name=f"outline-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始写骨架，一般 1–2 分钟"}

    title_errors: dict[int, str] = {}

    def _article_preview(markdown: str, limit: int = 3000) -> dict[str, Any]:
        lines = markdown.splitlines()
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
        paras = [re.sub(r"[*_`>#]+", "", l).strip() for l in lines if l.strip() and not l.startswith("# ")]
        paras = [p for p in paras if p]
        text = "\n\n".join(paras)
        return {"title": title, "summary": (paras[0] if paras else "")[:120], "text": text[:limit], "chars": len(re.sub(r"\s", "", text))}

    def _video_transcript(topic: dict[str, Any]) -> str:
        """视频项目里的原话：优先校对过标点的句子表，没有再用 SRT。"""
        from . import koubo, titles

        if not topic.get("video_project"):
            # 补发的旧视频没有视频项目：用拆解时转写的逐字稿 transcript.json（full_text）。
            # 同目录的 text.txt 是抖音简介，不是原话，只有几十到几百字。
            vid = topic.get("published_video_id")
            if vid and str(vid).isdigit():
                for path in sorted((downloads_dir / "douyin").glob(f"*/{vid}/transcript.json")):
                    try:
                        text = str(json.loads(path.read_text(encoding="utf-8")).get("full_text") or "").strip()
                    except (OSError, ValueError, AttributeError):
                        continue
                    if text:
                        return text
            return ""
        try:
            base = video_project.project_dir(video_root(), topic["video_project"])
            sentences = base / "subtitles" / "transcript.sentences.json"
            if sentences.is_file():
                data = json.loads(sentences.read_text(encoding="utf-8"))
                rows = data.get("transcript") if isinstance(data, dict) else data
                return "".join(str(r.get("text") or "") for r in rows or [] if isinstance(r, dict))
            srt = koubo.find_srt(base)
            return titles.srt_text(srt) if srt else ""
        except (VideoProjectError, OSError, ValueError):
            return ""

    def _transcript_for_article(topic: dict[str, Any]) -> str:
        """写文章要的原话。有成片、却找不到字幕时不写，请 作者 从剪映导出 SRT。
        9/29 作者：9/28 那条的研习室文章是照他 Obsidian 里的语音笔记写的，不是视频原话——项目里找不到字幕，
        写作就悄悄退回了笔记。字幕是他在剪映里校对过的原话，比机器转写准，所以不拿机器转写顶替，也不拿笔记顶替。"""
        text = _video_transcript(topic)
        if text.strip() or not topic.get("video_project"):
            return text
        if final_video_path(topic) is None:
            return ""  # 还没拍完：只有笔记，照笔记写是对的
        raise writer.WriterError("没找到这条的字幕：剪映导出时勾上「字幕 SRT」，把 .srt 放进项目文件夹（和成片放一起也行），再点重写")

    REDO_ARTICLE = "视频重新录过了，上一版是照旧字幕整理的。这次完全照最新的字幕原话重新整理，别沿用上一版的句子。"

    def _article_stale(topic: dict[str, Any]) -> str | None:
        """文章是旧的就说为什么：10/13 作者 昨天录过一遍、今天又重录，文章还是 10/12 照旧字幕写的。
        文章 meta 记着它是照哪份字幕写的（transcript_fp）；老文章没记，就看字幕文件有没有比文章新。"""
        from . import koubo

        if not topic.get("video_project") or not topic.get("article_path") or board_mod.is_shipped(topic):
            return None
        text = _video_transcript(topic)
        if not text.strip():
            return None
        meta_path = Path(topic["article_path"]).with_name("meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if meta.get("transcript_fp"):
            return "视频重录过了，文章还是照旧字幕写的，要重写" if meta["transcript_fp"] != writer.transcript_fp(text) else None
        try:
            base = video_project.project_dir(video_root(), topic["video_project"])
            sentences = base / "subtitles" / "transcript.sentences.json"
            source = sentences if sentences.is_file() else koubo.find_srt(base)
            wrote = datetime.fromisoformat(str(meta.get("generated_at")))
            if source is not None and datetime.fromtimestamp(source.stat().st_mtime, timezone.utc) > wrote + timedelta(minutes=1):
                return "字幕比文章新（视频重录过了），文章要重写"
        except (VideoProjectError, OSError, ValueError, TypeError):
            pass
        return None

    app.state.article_stale = _article_stale

    def _title_material(topic: dict[str, Any]) -> tuple[str, str]:
        """转写（视频项目里的 SRT）和骨架。都没有也能出，只是依据少。"""
        from . import outline

        transcript = _video_transcript(topic)
        skeleton = (outline.read_outline(topic) or {}).get("markdown", "")
        return transcript, skeleton

    def _title_topic(topic_id: int) -> None:
        from . import titles

        try:
            topic = store.topic(topic_id)
            transcript, skeleton = _title_material(topic)
            titles.write_titles(topic, transcript=transcript, skeleton=skeleton, drafts_dir=drafts_root,
                                adjustments=latest_adjustments())
            store.log_event("copy", f"《{topic['title'][:24]}》的标题候选出好了", topic_id)
        except Exception as exc:  # noqa: BLE001 - 弹窗里显示
            logger.warning("titles topic %s failed: %s", topic_id, exc)
            title_errors[topic_id] = str(exc)[:300] or type(exc).__name__
        finally:
            with writing_lock:
                writing.discard(30_000 + topic_id)

    @app.post("/api/topics/{topic_id}/titles")
    def start_titles(topic_id: int) -> dict[str, Any]:
        from . import titles

        store.topic(topic_id)
        titles.load_framework()  # 工作流文件缺了当场说，别让他等一分钟才看到
        with writing_lock:
            if 30_000 + topic_id in writing:
                return {"started": False, "message": "正在出"}
            writing.add(30_000 + topic_id)
        title_errors.pop(topic_id, None)
        threading.Thread(target=_title_topic, args=(topic_id,), name=f"titles-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出标题，一般半分钟到一分钟"}

    @app.get("/api/topics/{topic_id}/titles")
    def get_titles(topic_id: int) -> dict[str, Any]:
        from . import titles

        store.topic(topic_id)
        with writing_lock:
            running = 30_000 + topic_id in writing
        return {"running": running, "error": title_errors.get(topic_id), "result": titles.read_titles(drafts_root, topic_id)}

    layout_errors: dict[int, str] = {}

    _article_path = places.article_path

    @app.post("/api/topics/{topic_id}/layout")
    def start_layout(topic_id: int) -> dict[str, Any]:
        """用 gzh-design skill 给研习室文章排版；公众号和研习室发布都用这份。"""
        from . import gzh_layout

        topic = store.topic(topic_id)
        article = _article_path(topic)
        if article is None or not article.is_file():
            raise ValueError("先在「研习室文章」写好文章")
        with writing_lock:
            if 50_000 + topic_id in writing:
                return {"started": False, "message": "正在排"}
            writing.add(50_000 + topic_id)
        layout_errors.pop(topic_id, None)

        def run() -> None:
            try:
                gzh_layout.layout(article)
                store.log_event("copy", f"《{topic['title'][:24]}》用 gzh 排好版了", topic_id)
            except Exception as exc:  # noqa: BLE001 - 文章页显示
                logger.warning("gzh layout %s failed: %s", topic_id, exc)
                layout_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "wx", layout_errors.get(topic_id), slot=50_000 + topic_id)

        threading.Thread(target=run, name=f"layout-{topic_id}", daemon=True).start()
        return {"started": True, "message": f"开始用 gzh 排版（{gzh_layout.THEME}），一般 5–10 分钟"}

    @app.get("/api/topics/{topic_id}/layout")
    def layout_state(topic_id: int) -> dict[str, Any]:
        from . import gzh_layout

        topic = store.topic(topic_id)
        with writing_lock:
            running = 50_000 + topic_id in writing
        return {"running": running, "error": layout_errors.get(topic_id), **gzh_layout.state(_article_path(topic))}

    illustrate_errors: dict[int, str] = {}

    def start_illustrate(topic_id: int) -> bool:
        """配图（Codex 画，4–8 张，5–10 分钟）。已经在配就不再起一个。"""
        from . import illustrate as il

        article = _article_path(store.topic(topic_id))
        if article is None or not article.is_file():
            raise ValueError("先写好文章再配图")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return False
            writing.add(60_000 + topic_id)
        illustrate_errors.pop(topic_id, None)

        def run() -> None:
            try:
                sheet = hooks["proof_sheet"](topic_id) if "proof_sheet" in hooks and feature_on("proof") else None
                r = il.illustrate(article, sheet=sheet)
                done = f"配好了 {len(r['images'])} 张图" if r["images"] or sheet is None else "证据单里没有要画插图的论点，这次不画"
                store.log_event("copy", f"《{store.topic(topic_id)['title'][:24]}》{done}", topic_id)
            except Exception as exc:  # noqa: BLE001 - 发布台显示
                logger.warning("illustrate %s failed: %s", topic_id, exc)
                illustrate_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "figs", illustrate_errors.get(topic_id), slot=60_000 + topic_id)

        threading.Thread(target=run, name=f"illustrate-{topic_id}", daemon=True).start()
        return True

    @app.post("/api/topics/{topic_id}/illustrate")
    def post_illustrate(topic_id: int) -> dict[str, Any]:
        started = start_illustrate(topic_id)
        return {"started": started, "message": "开始配图（小黑手绘），一般 5–10 分钟" if started else "正在配"}

    @app.get("/api/topics/{topic_id}/illustrate")
    def get_illustrate(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import illustrate as il

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        st = il.state(_article_path(topic))
        for img in st["images"]:
            img["url"] = f"/api/topics/{topic_id}/article-file/{il.FOLDER}/{quote(img['file'])}"
        return {"running": running, "error": illustrate_errors.get(topic_id), **st}

    @app.get("/api/topics/{topic_id}/article-file/{relative:path}")
    def article_file(topic_id: int, relative: str) -> Response:
        """文章目录里的图（配图），只读，只给图片。"""
        article = _article_path(store.topic(topic_id))
        if article is None:
            raise HTTPException(status_code=404, detail="还没有文章")
        base = article.parent.resolve()
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/api/topics/{topic_id}/wechat-preview.html")
    def wechat_preview(topic_id: int) -> Response:
        """公众号里会是什么样：和发布时用的是同一份正文（有 gzh 排版用 gzh 的，没有用基础排版），手机宽度。"""
        import html as html_mod

        from . import gzh_layout
        from .extras.autopost import wechat_publish

        article = _article_path(store.topic(topic_id))
        if article is None or not article.is_file():
            raise HTTPException(status_code=404, detail="还没写文章")
        title, digest_text, body = wechat_publish.render_html(article.read_text(encoding="utf-8"))
        styled = gzh_layout.current(article)
        if styled is not None:
            body = styled.read_text(encoding="utf-8")
        kind = "gzh 排版（橄榄手记）" if styled is not None else "基础排版（还没用 gzh 排）"
        # 配图是文章目录里的相对路径：预览里换成能打开的地址（发的时候另外传到微信）
        body = re.sub(r'(<img\b[^>]*?\bsrc=")(?!https?:|data:)([^"]+)"', lambda m: f'{m.group(1)}/api/topics/{topic_id}/article-file/{m.group(2)}"', body)
        doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
               '<body style="margin:0;background:#ededed;font-family:-apple-system,PingFang SC,sans-serif">'
               f'<div style="max-width:390px;margin:0 auto;background:#fff;min-height:100vh;padding:20px 16px 40px;box-sizing:border-box">'
               f'<div style="font-size:12px;color:#999;margin-bottom:10px">预览 · {html_mod.escape(kind)}</div>'
               f'<h1 style="font-size:22px;line-height:1.4;margin:0 0 8px;color:#111">{html_mod.escape(title)}</h1>'
               f'<div style="font-size:14px;color:#576b95;margin-bottom:18px">{html_mod.escape(_my_handle("wechat_mp"))}</div>{body}</div></body></html>')
        return Response(content=doc, media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.get("/api/topics/{topic_id}/layout.html")
    def layout_html(topic_id: int) -> Response:
        """排版预览。放进隔离的源：页面是模型生成的，不许碰工作台接口。"""
        from . import gzh_layout

        article = _article_path(store.topic(topic_id))
        page = article.parent / gzh_layout.FILENAME if article else None
        if page is None or not page.is_file():
            raise HTTPException(status_code=404, detail="还没排版")
        doc = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#fff">{page.read_text(encoding="utf-8")}</body></html>'
        return Response(content=doc, media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    xhs_errors: dict[int, str] = {}

    @app.post("/api/topics/{topic_id}/xhs")
    def start_xhs(topic_id: int) -> dict[str, Any]:
        """研习室文章一字不改排成小红书 3:4 图。"""
        from . import xhs_cards

        topic = store.topic(topic_id)
        article = _article_path(topic)
        if article is None or not article.is_file():
            raise ValueError("先在「研习室文章」写好文章，小红书图文用的就是那一篇")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return {"started": False, "message": "正在出图"}
            writing.add(60_000 + topic_id)
        xhs_errors.pop(topic_id, None)

        def run() -> None:
            try:
                meta = xhs_cards.make_cards(article, handle=_my_handle("xiaohongshu"))
                store.log_event("copy", f"《{topic['title'][:24]}》小红书图文出好了：{meta['images']} 张", topic_id)
            except Exception as exc:  # noqa: BLE001 - 发布台显示
                logger.warning("xhs cards %s failed: %s", topic_id, exc)
                xhs_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "xhs", xhs_errors.get(topic_id), slot=60_000 + topic_id)

        threading.Thread(target=run, name=f"xhs-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出小红书图文，十几秒"}

    @app.get("/api/topics/{topic_id}/xhs")
    def xhs_state(topic_id: int) -> dict[str, Any]:
        from . import xhs_cards

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        st = xhs_cards.state(_article_path(topic))
        return {"running": running, "error": xhs_errors.get(topic_id), **st,
                "urls": [f"/api/topics/{topic_id}/xhs/{name}" for name in st["images"]]}

    @app.get("/api/topics/{topic_id}/xhs/{name}")
    def xhs_image(topic_id: int, name: str) -> Response:
        from . import xhs_cards

        article = _article_path(store.topic(topic_id))
        if article is None or not re.fullmatch(r"\d{2}\.png", name):
            raise HTTPException(status_code=404, detail="没有这张")
        path = article.parent / xhs_cards.FOLDER / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="没有这张")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/topics/{topic_id}/xhs/reveal")
    def xhs_reveal(topic_id: int) -> dict[str, Any]:
        """在访达里打开小红书图片文件夹并选中第一张（封面），上传时直接拖或选。只打开，不动文件。"""
        import subprocess

        from . import xhs_cards

        article = _article_path(store.topic(topic_id))
        first = article.parent / xhs_cards.FOLDER / "01.png" if article else None
        if first is None or not first.is_file():
            raise ValueError("还没出图：先点「出图文」")
        subprocess.run(["open", "-R", str(first)], check=False, timeout=10)
        return {"ok": True}

    @app.get("/api/topics/{topic_id}/xhs.zip")
    def xhs_zip(topic_id: int) -> Response:
        """按顺序打包：01 是封面，手机上按文件名顺序选就对了。"""
        import io
        import zipfile

        from . import xhs_cards

        topic = store.topic(topic_id)
        article = _article_path(topic)
        folder = article.parent / xhs_cards.FOLDER if article else None
        images = sorted(folder.glob("*.png")) if folder and folder.is_dir() else []
        if not images:
            raise HTTPException(status_code=404, detail="还没出图")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for image in images:
                zf.write(image, image.name)
        from urllib.parse import quote

        filename = quote(f"小红书图文-{topic['title'][:20]}.zip")
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

    @app.get("/api/topics/{topic_id}/outline")
    def get_outline(topic_id: int) -> dict[str, Any]:
        from . import outline

        data = outline.read_outline(store.topic(topic_id))
        if data is None:
            raise HTTPException(status_code=404, detail="这个选题还没有骨架")
        return data

    @app.put("/api/topics/{topic_id}/outline")
    def put_outline(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        from . import outline

        topic = store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("提纲不能为空")
        path = Path(topic["outline_path"]) if topic.get("outline_path") else drafts_root / f"topic-{topic_id}" / outline_mod.FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        if not topic.get("outline_path"):
            store.update_topic(topic_id, outline_path=str(path))
        return outline.read_outline(store.topic(topic_id)) or {}

    # -- video projects (口播 workflow) -----------------------------------

    video_root = places.video_root

    # -- three-point QA (痛点具象度 / 认知反差度 / 交付可行性) --------------------

    qa_runs: dict[int, dict[str, Any]] = {}
    qa_lock = threading.Lock()

    def _qa_material(topic: dict[str, Any]) -> str:
        parts = [f"备注：{topic['memo']}"] if topic.get("memo") else []
        parts += [f"### {s['title']}\n{s['body']}" for s in writer.topic_sources(vault_path(), topic, drafts_root)]
        return "\n\n".join(parts)

    def _run_qa(topic_id: int) -> None:
        """Score a topic in the calling thread; failures are kept for the tab, never raised."""
        from . import outline, qa

        with qa_lock:
            if (qa_runs.get(topic_id) or {}).get("state") == "running":
                return
            qa_runs[topic_id] = {"state": "running"}
        try:
            topic = store.topic(topic_id)
            draft = outline.read_outline(topic)
            result = qa.score_topic(topic["title"], draft["markdown"] if draft else "", _qa_material(topic), **({"qa_fn": qa_fn} if qa_fn else {}))
            qa.save(drafts_root, topic_id, result)
            with qa_lock:
                qa_runs.pop(topic_id, None)
        except Exception as exc:  # noqa: BLE001 - shown on the outline tab
            logger.warning("qa topic %s failed: %s", topic_id, exc)
            with qa_lock:
                qa_runs[topic_id] = {"state": "failed", "error": str(exc)[:300] or type(exc).__name__}

    @app.get("/api/topics/{topic_id}/qa")
    def get_qa(topic_id: int) -> dict[str, Any]:
        from . import qa

        store.topic(topic_id)
        with qa_lock:
            run = dict(qa_runs.get(topic_id) or {})
        return {"state": run.get("state") or "idle", "error": run.get("error"), "result": qa.load(drafts_root, topic_id)}

    @app.post("/api/topics/{topic_id}/qa")
    def start_qa(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("outline_path") and not topic.get("memo") and not topic.get("note_paths"):
            raise ValueError("没有提纲也没有素材，没法评")
        with qa_lock:
            if (qa_runs.get(topic_id) or {}).get("state") == "running":
                return {"started": False, "message": "正在评"}
        threading.Thread(target=_run_qa, args=(topic_id,), name=f"qa-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始按三点评分，一般半分钟"}

    # -- opening 15 seconds ---------------------------------------------------

    opening_runs: dict[int, dict[str, Any]] = {}
    opening_lock = threading.Lock()

    def _score_opening(topic_id: int, project: Path, thesis: str) -> None:
        from . import opening

        try:
            result = opening.score_opening(project, thesis=thesis, **({"opening_fn": opening_fn} if opening_fn else {}))
            opening.save(drafts_root, topic_id, result)
            with opening_lock:
                opening_runs.pop(topic_id, None)
        except Exception as exc:  # noqa: BLE001 - shown on the video tab
            logger.warning("opening topic %s failed: %s", topic_id, exc)
            with opening_lock:
                opening_runs[topic_id] = {"state": "failed", "error": str(exc)[:300] or type(exc).__name__}

    @app.get("/api/topics/{topic_id}/opening")
    def get_opening(topic_id: int) -> dict[str, Any]:
        from . import opening

        _topic, project, _info = linked_project(topic_id)
        found = opening.find_subtitles(project)
        with opening_lock:
            run = dict(opening_runs.get(topic_id) or {})
        return {"state": run.get("state") or "idle", "error": run.get("error"), "result": opening.load(drafts_root, topic_id),
                "subtitles": {"path": str(found[0].relative_to(project)), "label": found[1]} if found else None}

    @app.post("/api/topics/{topic_id}/opening")
    def start_opening(topic_id: int) -> dict[str, Any]:
        from . import opening, outline

        topic, project, _info = linked_project(topic_id)
        if opening.find_subtitles(project) is None:
            raise ValueError("项目里还没有字幕文件：录完把粗剪和字幕放进项目文件夹")
        draft = outline.read_outline(topic)
        thesis = opening.thesis_for(draft["markdown"] if draft else None, topic["title"])
        with opening_lock:
            if (opening_runs.get(topic_id) or {}).get("state") == "running":
                return {"started": False, "message": "正在检查开头"}
            opening_runs[topic_id] = {"state": "running"}
        threading.Thread(target=_score_opening, args=(topic_id, project, thesis), daemon=True).start()
        return {"started": True, "message": "开始检查开头 15 秒，一般半分钟"}

    @app.post("/api/topics/{topic_id}/video-project/worktable")
    def import_worktable(topic_id: int, body: WorktableBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        return video_project.import_worktable(
            video_root(), topic["video_project"], text=body.text, source=(body.filename or "粘贴")[:80], overwrite=body.overwrite
        )

    linked_project = places.linked_project
    # -- one-click publishing (作者 confirms every job) --------------------

    def publisher_specs() -> dict[str, dict[str, Any]]:
        from . import publisher

        return publishers if publishers is not None else publisher.PUBLISHERS

    _media_base = places.media_base

    def _media_url(topic: dict[str, Any], relative: str) -> str:
        from urllib.parse import quote

        return f"/api/topics/{topic['id']}/media/{quote(relative)}"

    @app.get("/api/topics/{topic_id}/media/{relative:path}")
    def topic_media(topic_id: int, relative: str) -> Response:
        """选题的封面、候选帧，只读。项目里的和补发草稿目录里的都从这里取。"""
        topic = store.topic(topic_id)
        try:
            base = _media_base(topic).resolve()
        except VideoProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    def _release_for(topic: dict[str, Any]) -> dict[str, Any] | None:
        """final/ 下的封面和发布文案，带上每张封面的地址。补发的旧视频也有（放在草稿目录）。"""
        from . import release

        try:
            base = _media_base(topic)
        except VideoProjectError:
            return None
        found = release.find_release(base)
        covers = found.get("covers") or {}
        return {"project": topic.get("video_project"), **found,
                "cover_urls": {k: _media_url(topic, v) for k, v in covers.items() if v}}

    def _approval_state(topic: dict[str, Any], release_info: dict[str, Any] | None = None) -> dict[str, Any]:
        """打包页每一步的定稿状态（见 approvals.py）。"""
        from . import approvals, copypack, gzh_layout, illustrate as il, reach, xhs_cards
        from .extras.proof import evidence

        rel = release_info if release_info is not None else _release_for(topic)
        covers: list[Path] = []
        if rel:
            try:
                base = _media_base(topic)
                covers = [base / v for k, v in (rel.get("covers") or {}).items() if v and k in ("landscape", "portrait", "wide")]
            except VideoProjectError:
                pass
        art = _article_path(topic)
        text = art.read_text(encoding="utf-8") if art is not None and art.is_file() else None
        figs = [art.parent / il.FOLDER / i["file"] for i in il.state(art)["images"]] if text else []
        fps = approvals.fingerprints(
            copy=(copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms"),
            covers=covers, article=il.strip_images(evidence.strip(text)) if text else None, figs=figs,
            wx=gzh_layout.state(art) if text else {},
            xhs=(xhs_cards.state(art) if text else {}) if "cards" in reach.forms_list(topic, store.settings()["platform_accounts"])["xiaohongshu"] else None,
        )
        return {"fps": fps, "folder": drafts_root / f"topic-{topic['id']}"}

    @app.put("/api/topics/{topic_id}/approve")
    def approve_step(topic_id: int, body: StepApproveBody) -> dict[str, Any]:
        """定稿 / 撤销定稿（改这一步）。"""
        from . import approvals

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        try:
            by = "machine" if body.by == "machine" else "park"
            result = {"approvals": approvals.set_approval(st["folder"], body.key, body.approved, st["fps"], by=by, skip=_pack_skip())}
        except approvals.ApprovalError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if body.key == "copy" and body.approved:
            _title_follows_copy(topic)
        return result

    def _title_follows_copy(topic: dict[str, Any]) -> None:
        """标题定稿了，选题就叫抖音那个标题（10/5：54 号一直叫复刻来的别人的标题，视频讲的是另一件事，认错了）。
        系列靠 replicate.json 里的 episode_title 对，不靠选题名，改名不影响。"""
        from . import copypack

        title = ((((copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms") or {}).get("douyin") or {}).get("title") or "").strip()
        if title and title != topic["title"]:
            store.update_topic(topic["id"], title=title)
            store.log_event("stage", f"《{topic['title'][:24]}》标题定稿，改叫《{title[:24]}》", topic["id"])


    archive_root = places.archive_root

    final_video_path = places.final_video_path

    def _cover_target(topic_id: int) -> tuple[dict[str, Any], Path, Path]:
        topic = store.topic(topic_id)
        video = final_video_path(topic)
        if video is None:
            raise HTTPException(status_code=400, detail="这一条还没有成片，封面要从成片里取人像")
        return topic, _media_base(topic), video

    cover_errors: dict[int, str] = {}

    def _cover_title(topic: dict[str, Any], base: Path) -> tuple[str, bool]:
        """封面上的字就是标题：打包里存的 > 成片包的发布文案 > 选题名。第二个值说是不是 作者 在打包里写的。"""
        from . import copypack, release

        platforms = (copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms") or {}
        # 9/29 作者：「封面上的字直接就是这个视频的 title。」打包里先写标题，封面跟着它走。
        saved = next((e.get("title") for e in (platforms.get(k) or {} for k in ("douyin", "channels", "xiaohongshu", "bilibili", "youtube")) if e.get("title")), "")
        rel = release.find_release(base).get("copy") or {}
        return (saved or rel.get("title") or topic["title"]), bool(saved)

    @app.get("/api/topics/{topic_id}/cover")
    def cover_options(topic_id: int) -> dict[str, Any]:
        """打包页做封面要的：标题（就是封面上的字）、取帧用的那份视频、机器挑好的一帧 + 另外几张候选、
        正在不在出、上次出错没有。"""
        import hashlib

        from . import cover

        topic, base, video = _cover_target(topic_id)
        title, from_copy = _cover_title(topic, base)
        source = cover.source_video(base, video)
        tag = hashlib.sha1(str(source).encode()).hexdigest()[:8]
        try:
            frames = cover.pick_frames(source, base / "analysis" / f"cover-frames-{tag}")
        except cover.CoverError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        with writing_lock:
            running = 70_000 + topic_id in writing
        return {
            "title": title, "from_copy": from_copy, "lines": cover.split_title(title),
            "source": source.name, "running": running, "error": cover_errors.get(topic_id),
            "progress": cover.progress(base) if running else None,
            "frames": [{"at": f["at"], "score": f["score"], "pick": f["pick"], "url": _media_url(topic, str(f["path"].relative_to(base)))} for f in frames],
        }

    @app.post("/api/topics/{topic_id}/cover")
    def make_cover(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """出竖、横两张封面（Codex image_gen，5–10 分钟），放进 final/covers/，发布台的交付包会自己认到。"""
        from . import cover

        topic, base, video = _cover_target(topic_id)
        title, _ = _cover_title(topic, base)
        at = float(payload.get("at") or 0)
        with writing_lock:
            if 70_000 + topic_id in writing:
                return {"started": False, "message": "正在出封面"}
            writing.add(70_000 + topic_id)
        cover_errors.pop(topic_id, None)

        def run() -> None:
            try:
                made = cover.generate(base, cover.source_video(base, video), at=at, title=title)
                store.log_event("copy", f"《{title[:24]}》封面出好了：{'、'.join(made)}", topic_id)
            except Exception as exc:  # noqa: BLE001 - 打包页显示
                logger.warning("cover %s failed: %s", topic_id, exc)
                cover_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                _pack_job_done(topic_id, "cover", cover_errors.get(topic_id), slot=70_000 + topic_id)

        threading.Thread(target=run, name=f"cover-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始出封面（图像生成），一般 5–10 分钟"}

    # -- 打包自动档（pack_auto.py）：作者 只定标题，剩下的一步接一步做完、自动定稿 -----------

    pack_lock = threading.Lock()

    def _pack_running(topic_id: int, state: dict[str, Any]) -> set[str]:
        with writing_lock:
            live = set(writing)
        running = set()
        if 70_000 + topic_id in live:
            running.add("cover")
        if topic_id in live:
            running.add("article")
        if 50_000 + topic_id in live:
            running.add("wx")
        if 60_000 + topic_id in live:
            # 配图和小红书出图共用一个占位：看自动档记的是哪一步在跑
            steps = state.get("steps") or {}
            running.add("xhs" if (steps.get("xhs") or {}).get("state") == "running" and (steps.get("figs") or {}).get("state") != "running" else "figs")
        return running

    def _pack_start(topic_id: int, key: str) -> None:
        from . import cover

        if key == "cover":
            _topic, base, video = _cover_target(topic_id)
            source = cover.source_video(base, video)
            import hashlib

            frames = cover.pick_frames(source, base / "analysis" / f"cover-frames-{hashlib.sha1(str(source).encode()).hexdigest()[:8]}")
            pick = next((f for f in frames if f["pick"]), frames[len(frames) // 2] if frames else {"at": 0})
            make_cover(topic_id, {"at": pick["at"]})
        elif key == "article":
            # 已经有文章的（字幕换了要重写）：重写必须带说明，不然 start_write 会拒绝
            start_write(topic_id, WriteBody(instruction=REDO_ARTICLE) if store.topic(topic_id).get("article_path") else None)
        elif key == "figs":
            start_illustrate(topic_id)
        elif key == "wx":
            start_layout(topic_id)
        elif key == "xhs":
            start_xhs(topic_id)

    def _pack_needed(topic: dict[str, Any]) -> set[str]:
        """按各平台发什么决定打包做哪几样（10/6 作者：全是视频就只出封面）。
        封面：有平台发视频（10/7：一条都不发视频就不出封面）；文章、插图：有平台要发文章（X、公众号、研习室）或小红书要图文；
        公众号排版：公众号发文章；小红书图文：小红书选了图文。这条标了不发的平台不算。"""
        from . import reach

        fl = reach.forms_list(topic, store.settings()["platform_accounts"] or {})
        on = _on_keys() - store.publish_skips(topic["id"])
        need = {"cover"} if any("video" in fl[k] for k in on if k in fl) else set()
        text_on = [k for k in ("x", "wechat_mp", "miniprogram") if k in on and "text" in fl[k]]
        cards_on = "xiaohongshu" in on and "cards" in fl["xiaohongshu"]
        if text_on or cards_on:
            need |= {"article", "figs"}
        if "wechat_mp" in text_on:
            need.add("wx")
        if cards_on:
            need.add("xhs")
        if not feature_on("figs"):
            need.discard("figs")  # 10/9：插图关了，排版、小红书图文不等它
        return need

    def _pack_skip() -> set[str]:
        """关掉的打包步骤：后面的步骤定稿时不等它。"""
        return set() if feature_on("figs") else {"figs"}

    def pack_advance(topic_id: int) -> dict[str, Any]:
        """照 pack_auto.plan 往下走一步：做好的自动定稿，该开始的开始。没 armed 什么都不做。"""
        from . import approvals, pack_auto

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        folder, fps = st["folder"], st["fps"]
        needed = _pack_needed(topic)
        stale = {"article"} if "article" in needed and _article_stale(topic) else set()
        with pack_lock:
            state = pack_auto.load(folder)
            if stale and str(((state.get("steps") or {}).get("article") or {}).get("error") or "").startswith("重写要先说"):
                state = pack_auto.retry(folder, "article")  # 旧版自动档没带说明去重写、被拒记下的错：现在能重写了，不用他点重试
            status = approvals.status(folder, fps)
            running = _pack_running(topic_id, state)
            for action, key in pack_auto.plan(state, status, running, title=state.get("title") or "", xhs="xhs" in fps, needed=needed, stale=stale):
                step = (state.get("steps") or {}).get(key) or {}
                if action == "approve":
                    try:
                        status = approvals.set_approval(folder, key, True, fps, by="auto", skip=_pack_skip())
                        state = pack_auto.mark(folder, key, state="done", error=None)
                    except approvals.ApprovalError as exc:
                        state = pack_auto.mark(folder, key, state="error", error=str(exc))
                elif action in ("start", "interrupted"):
                    tries = int(step.get("tries") or 0) + 1 if action == "interrupted" else 1
                    try:
                        # 先记「在做」再起任务：任务失败得快（比如出图马上报错），它的「失败」会先写进去，
                        # 再被这里的「在做」盖掉，下一轮当成被打断又重做一遍（10/3 CI 偶发：封面出了两次）
                        state = pack_auto.mark(folder, key, state="running", started_at=pack_auto.now(), tries=tries, error=None,
                                               **({"title": state.get("title")} if key == "cover" else {}))
                        _pack_start(topic_id, key)
                    except Exception as exc:  # noqa: BLE001 - 打包页显示，等 作者 点重试
                        logger.warning("pack %s %s failed to start: %s", topic_id, key, exc)
                        state = pack_auto.mark(folder, key, state="error", error=str(getattr(exc, "detail", "") or exc)[:300])
                elif action == "give_up":
                    state = pack_auto.mark(folder, key, state="error", error="被中断了两次（服务重启），点重试再来")
        return state

    def _pack_job_done(topic_id: int, key: str, error: str | None, *, slot: int) -> None:
        """打包要的任务做完（不管是自动档起的还是手点的）：记一笔，放开占位，自动档往下走。

        顺序要紧：先记下做好了 / 失败了，再放开占位（slot，writing 里那个数）。反过来的话，中间那一下
        自动档看到「记着在做、可线程没了」，当成服务重启打断，重做一遍（10/3 CI 上偶发：失败被记成「被中断了两次」）。"""
        from . import pack_auto

        armed = False
        try:
            folder = drafts_root / f"topic-{topic_id}"
            state = pack_auto.load(folder)
            armed = bool(state.get("armed"))
            if armed:
                pack_auto.mark(folder, key, state="error" if error else "made", error=error)
        except Exception as exc:  # noqa: BLE001 - 不让收尾把任务本身弄成失败
            logger.warning("pack mark after %s %s: %s", key, topic_id, exc)
        finally:
            with writing_lock:
                writing.discard(slot)
        if not armed:
            return
        try:
            pack_advance(topic_id)
        except Exception as exc:  # noqa: BLE001 - 不让收尾把任务本身弄成失败
            logger.warning("pack advance after %s %s: %s", key, topic_id, exc)

    LANE_STEPS = {"video": ("cover",), "text": ("article", "figs"), "cards": ("xhs",)}

    def _lane_fingerprint(topic: dict[str, Any], st: dict[str, Any], key: str, form: str) -> str:
        """这一格（平台 × 形式）放进待发时的指纹，只算它自己用的材料：视频用封面，文章用文章和插图（公众号再加排版），
        再加这个平台自己的文案。别的格的东西变了（比如文章重写）不会让抖音视频从待发里掉出来（10/13 作者：各项发布不要互为依赖）。"""
        from . import approvals

        steps = list(LANE_STEPS.get(form, ()))
        if key == "wechat_mp" and form == "text":
            steps.append("wx")
        entry = ((copypack.read_copy(drafts_root, topic["id"]) or {}).get("platforms") or {}).get(key)
        version = None
        if form == "video":
            video = final_video_path(topic)
            if video is not None:
                try:
                    info = video.stat()
                    version = [str(video), info.st_size, info.st_mtime_ns, info.st_ctime_ns]
                except OSError:
                    pass
        return approvals.digest({k: st["fps"].get(k) for k in steps}, entry, key, form, version)

    def pack_view(topic_id: int) -> dict[str, Any]:
        from . import approvals, pack_auto

        topic = store.topic(topic_id)
        st = _approval_state(topic)
        state = pack_auto.load(st["folder"])
        status = approvals.status(st["folder"], st["fps"])
        running = _pack_running(topic_id, state)
        detail: dict[str, str] = {}
        if "cover" in running:
            try:
                from . import cover

                _t, base, _v = _cover_target(topic_id)
                detail["cover"] = cover.progress_note(cover.progress(base))
            except Exception:  # noqa: BLE001 - 进度只是一句话
                detail["cover"] = "出图中"
        if "article" in running:
            detail["article"] = "在润色，一般 2–5 分钟" if status["article"]["made"] else "照视频字幕写，一般 1–5 分钟"
        if "figs" in running:
            detail["figs"] = "小黑手绘，一张一张画，5–10 分钟"
        if "wx" in running:
            detail["wx"] = "gzh 排版，5–10 分钟"
        needed = _pack_needed(topic)
        stale_note = _article_stale(topic) if "article" in needed else None
        rows = pack_auto.view(state, status, running, xhs="xhs" in st["fps"], detail=detail, needed=needed,
                              stale={"article": stale_note} if stale_note else None)
        lanes = _pack_lanes(topic, status)
        for lane in lanes:
            lane["handed"] = pack_auto.handed(state, pack_auto.lane_id(lane["key"], lane["form"]), _lane_fingerprint(topic, st, lane["key"], lane["form"]))
        handed_keys = list(dict.fromkeys(lane["key"] for lane in lanes if lane["handed"]))
        return {"armed": bool(state.get("armed")), "title": state.get("title") or "", "copy_locked": bool(status["copy"]["approved"] and status["copy"]["valid"]),
                "steps": rows, "ready": all(r["state"] == "done" for r in rows), "busy": any(r["state"] in ("running", "waiting") for r in rows),
                "lanes": lanes, "handoff": {"platforms": handed_keys} if handed_keys else None,
                "publication_warnings": _publication_warnings(topic_id=topic_id)}

    def _pack_lanes(topic: dict[str, Any], ap: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """③ 每个要发的平台 × 形式各一条：能不能发、差什么（10/7 作者：只发视频的那天，抖音封面好了就能发，不等插图）。"""
        from . import reach

        fl = reach.forms_list(topic, store.settings()["platform_accounts"] or {})
        skips = store.publish_skips(topic["id"])
        video = final_video_path(topic)
        out = []
        for p in _platform_rows():
            if not p.get("on") or p["key"] in skips:
                continue
            for row in _pp_form_rows(topic, p["key"], fl[p["key"]], ap=ap, video=video):
                out.append({**row, "key": p["key"], "label": p["label"], "form_label": row["label"]})
        return out

    @app.post("/api/topics/{topic_id}/pack/go")
    def pack_go(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """作者 定了标题：存标题（描述、话题沿用已经写的；没写过的用成片包里的发布文案），文字定稿，打开自动档。"""
        from . import approvals, copypack, pack_auto

        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="先写标题")
        topic = store.topic(topic_id)
        pack_auto.require_handoff(drafts_root / f"topic-{topic_id}")
        old = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms") or {}
        from .publish_desk import shared_entry

        shared = shared_entry({"platforms": old})
        rel = _release_for(topic) or {}
        seed = rel.get("copy") or {}
        body = shared["body"] or seed.get("body") or ""
        tags = shared["tags"] or list(seed.get("tags") or [])
        # B 站、YouTube 不在打包页上露面（10/2 作者），但照样写一份共用的标题和描述，发的时候还能用
        traffic = store.settings().get("traffic_tags") or {}
        keys = [k for k in copypack.PLATFORMS if k in ("douyin", "channels", "xiaohongshu", "bilibili", "youtube")]

        content = [t for t in tags if not any(t in (v or []) for v in traffic.values())]
        if not content:
            # 还没写过内容话题：用出标题时按内容出的那批（10/2 起），视频号、小红书也就有话题了
            from . import titles as titles_mod

            content = list(((titles_mod.read_titles(drafts_root, topic_id) or {}).get("tags")) or [])

        platforms = {**old, **{k: {"title": title, "body": (old.get(k) or {}).get("body") or body, "tags": copypack.with_traffic(k, content, traffic)} for k in keys}}
        copypack.save_copy(drafts_root, topic_id, platforms)
        st = _approval_state(topic)
        approvals.set_approval(st["folder"], "copy", True, st["fps"])
        prior = pack_auto.load(st["folder"])
        covers = [str((rel.get("covers") or {}).get(k) or "") for k in ("portrait", "landscape")]
        stem = re.sub(r'[\\/:*?"<>|]', "", title)[:40]  # cover.generate 存封面时的文件名开头
        if any(covers) and not ((prior.get("steps") or {}).get("cover") or {}).get("title") \
                and not any(Path(c).name.startswith(stem) for c in covers if c):
            # 现有封面不是按这个标题出的：记下来，让自动档按新标题重出，不拿旧封面直接定稿
            pack_auto.mark(st["folder"], "cover", state="made", title=shared["title"] or "（旧封面）")
        pack_auto.arm(st["folder"], title)
        pack_advance(topic_id)
        return pack_view(topic_id)

    @app.post("/api/topics/{topic_id}/pack/advance")
    def pack_tick(topic_id: int) -> dict[str, Any]:
        """页面轮询用（POST：会启动任务）。没定标题的不动。"""
        pack_advance(topic_id)
        return pack_view(topic_id)

    @app.get("/api/topics/{topic_id}/pack")
    def pack_get(topic_id: int) -> dict[str, Any]:
        """只读：打开页面时看自动档的状态，不启动任何任务。"""
        return pack_view(topic_id)

    @app.post("/api/topics/{topic_id}/pack/handoff")
    def pack_handoff(topic_id: int) -> dict[str, Any]:
        """把现在材料齐了的每一格放进各平台的待发；没齐的不挡着（10/13 作者：各项发布不要互为依赖），好了再放。
        只在本地放，不会真的发出去。"""
        from . import pack_auto

        view = pack_view(topic_id)
        lanes = view["lanes"]
        if not lanes:
            raise HTTPException(status_code=400, detail="先选择发布平台和形式")
        if not view["copy_locked"]:
            raise HTTPException(status_code=409, detail="标题和文案还没定稿")
        live = {"draft", "running", "awaiting_confirm", "unknown"}
        open_lanes = [r for r in lanes if r["presentation"]["state"] != "published" and not r["handed"]]
        ready = [r for r in open_lanes if r["ready"] or r["presentation"]["state"] in live]
        # 这个平台那边要认得这一条（没结束、没标不发），才放进去
        receiving = {key: any(row["topic_id"] == topic_id for row in _pp_pending(key, awaiting_handoff=True)) for key in {r["key"] for r in ready}}
        ready = [r for r in ready if receiving[r["key"]]]
        if not ready:
            if not open_lanes:
                return view  # 能放的都放过了
            why = "、".join(dict.fromkeys(r["why"] or "素材未就绪" for r in open_lanes))
            raise HTTPException(status_code=409, detail=why)
        topic = store.topic(topic_id)
        st = _approval_state(topic)
        pack_auto.record_handoff(st["folder"], {pack_auto.lane_id(r["key"], r["form"]): _lane_fingerprint(topic, st, r["key"], r["form"]) for r in ready})
        return pack_view(topic_id)

    @app.post("/api/topics/{topic_id}/pack/retry")
    def pack_retry(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        from . import pack_auto

        key = str(payload.get("key") or "")
        if key not in pack_auto.ORDER:
            raise HTTPException(status_code=400, detail="没有这一步")
        pack_auto.retry(drafts_root / f"topic-{topic_id}", key)
        {"cover": cover_errors, "figs": illustrate_errors, "wx": layout_errors, "xhs": xhs_errors}.get(key, {}).pop(topic_id, None)
        pack_advance(topic_id)
        return pack_view(topic_id)

    def _pack_resume_all() -> None:
        """服务刚起来：自动档里记着在跑的，重起（被部署重启打断的）。"""
        from . import pack_auto

        for path in sorted(drafts_root.glob(f"topic-*/{pack_auto.FILE}")):
            try:
                state = pack_auto.load(path.parent)
                if state.get("armed") and any((s or {}).get("state") in ("running", "made") for s in (state.get("steps") or {}).values()):
                    pack_advance(int(path.parent.name.split("-", 1)[1]))
            except Exception as exc:  # noqa: BLE001 - 一条坏了不挡别的
                logger.warning("pack resume %s: %s", path, exc)

    phone_errors: dict[int, str] = {}

    def _phone_state(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import phone

        topic = store.topic(topic_id)
        with writing_lock:
            running = 40_000 + topic_id in writing
        parts = []
        if topic.get("video_project"):
            try:
                base = video_project.project_dir(video_root(), topic["video_project"])
                prefix = f"/api/video-projects/{quote(topic['video_project'])}/raw/"
                parts = [{**p, "url": prefix + quote(p["path"])} for p in phone.existing(base)]
            except VideoProjectError:
                parts = []
        return {"running": running, "error": phone_errors.get(topic_id), "parts": parts, "cap_mb": phone.CAP_MB}

    @app.get("/api/topics/{topic_id}/phone-preview")
    def phone_preview_state(topic_id: int) -> dict[str, Any]:
        return _phone_state(topic_id)

    @app.post("/api/topics/{topic_id}/phone-preview")
    def start_phone_preview(topic_id: int) -> dict[str, Any]:
        """成片压成手机能看的大小，只在本机出文件，不上传。"""
        from . import phone

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        if video is None:
            raise ValueError("这一条还没有成片")
        base = video_project.project_dir(video_root(), topic["video_project"])
        with writing_lock:
            if 40_000 + topic_id in writing:
                return {"started": False, "message": "正在压"}
            writing.add(40_000 + topic_id)
        phone_errors.pop(topic_id, None)

        def run() -> None:
            try:
                parts = phone.make_preview(base, video)
                store.log_event("edit", f"《{topic['title'][:24]}》的手机预览好了：{len(parts)} 个文件", topic_id)
            except Exception as exc:  # noqa: BLE001 - 进度页上显示
                logger.warning("phone preview %s failed: %s", topic_id, exc)
                phone_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                with writing_lock:
                    writing.discard(40_000 + topic_id)

        threading.Thread(target=run, name=f"phone-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始压手机预览，12 分钟的片子大约半分钟"}


    # 手动传的平台要哪几个文件（9/29 作者：点上传，就弹开那个文件夹，里面是视频和竖、横封面，他自己拖进去）
    UPLOAD_KIT = {
        "douyin": (("video", "视频"), ("portrait", "竖封面"), ("landscape", "横封面")),
        "channels": (("video", "视频"), ("portrait", "竖封面")),
        # 9/29 作者：小红书改发视频（图文三篇共 262 播放，抖音同一条 7,893）。传抖音那条竖版无水印成片。
        "xiaohongshu": (("video", "视频"), ("portrait", "竖封面")),
        "bilibili": (("video", "视频"), ("wide", "16比9封面")),
        "youtube": (("video", "视频"), ("wide", "16比9封面")),
    }
    # 同一个文件几个平台都要、叫法不一样时（B 站的 16比9 封面没出、拿横封面顶上），用排前面的名字
    UPLOAD_NAME_RANK = ("视频", "竖封面", "横封面", "16比9封面")
    UPLOAD_DIR = "上传"

    def _clear_upload_dir(folder: Path) -> None:
        """清掉以前放进上传文件夹的东西：只删链接（硬链接数 > 1 或符号链接）、文案.txt、.DS_Store，
        本体（只剩这一份的文件）一个不碰；删空了才把文件夹删掉。"""
        if not folder.is_dir():
            return
        for old in folder.iterdir():
            try:
                if old.is_symlink() or old.name in ("文案.txt", ".DS_Store") or (old.is_file() and old.stat().st_nlink > 1):
                    old.unlink()
            except OSError:
                pass

    def _upload_platforms(topic: dict[str, Any], asked: str) -> list[str]:
        """这一条要手动传视频的平台：开着、这条没跳过、这条发视频。点的那个平台一定在里面。按平台表的顺序。"""
        from . import reach

        fl = reach.forms_list(topic, store.settings()["platform_accounts"] or {})
        keep = _on_keys() - _skipped(str(topic.get("published_video_id") or "") or None, topic["id"])
        return [k for k, _, _ in reach.PLATFORMS if k in UPLOAD_KIT and "video" in fl.get(k, ()) and (k in keep or k == asked)]

    @app.post("/api/topics/{topic_id}/upload-folder")
    def upload_folder(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """这一条所有手动传视频的平台共用一个文件夹 final/上传/，没有子文件夹，在访达里打开。用硬链接，不多占硬盘。

        10/8 作者：「不要给每一个平台都搞一个新的 folder……封面是重复的，视频是重复的，连 title 也是重复的，
        只有 hashtag 是不重复的。」所以同一个文件只放一份，名字里写给哪几个平台：竖封面（抖音、视频号、小红书）.png；
        文案.txt 也只一份，标题和描述一样的只写一遍，话题每个平台一行。以前的 上传-<平台>/ 清掉。"""
        from . import copypack, reach

        platform = str(body.get("platform") or "")
        topic = store.topic(topic_id)
        if platform not in UPLOAD_KIT or "video" not in reach.forms_list(topic, store.settings()["platform_accounts"] or {}).get(platform, ()):
            raise HTTPException(status_code=400, detail="这个平台没有要准备的上传文件")
        video = final_video_path(topic)
        if video is None:
            raise HTTPException(status_code=400, detail="还没有成片")
        base = _media_base(topic)
        covers = (_release_for(topic) or {}).get("covers") or {}
        label = {k: (copypack.PLATFORMS.get(k) or {}).get("label", k).replace(" ", "") for k in UPLOAD_KIT}
        keys = _upload_platforms(topic, platform)
        landscape_video = False
        if "xiaohongshu" in keys:
            # 10/1 作者：小红书的封面框跟着视频的比例走——横屏视频（3 月那批抖音下载版都是 1920×1080）框是 4:3 横的，
            # 放竖封面会被裁掉一半。横屏就放 4:3 横封面。
            from .cover import _dimensions

            w, h = _dimensions(video)
            landscape_video = w > h
        files: dict[Path, dict[str, Any]] = {}  # 同一个文件 → 叫什么、给哪几个平台
        missing: dict[str, list[str]] = {}
        for key in keys:
            kit = UPLOAD_KIT[key]
            if key == "xiaohongshu" and landscape_video:
                kit = (("video", "视频"), ("landscape", "横封面"))
            for kind, name in kit:
                if kind == "video":
                    src = video
                else:
                    rel = covers.get(kind) or (covers.get("landscape") if kind == "wide" else None)
                    src = base / rel if rel else None
                if src is None or not src.is_file():
                    missing.setdefault(name, []).append(label[key])
                    continue
                got = files.setdefault(src.resolve(), {"names": [], "who": []})
                got["names"].append(name)
                got["who"].append(label[key])
        final = base / "final"
        folder = final / UPLOAD_DIR
        folder.mkdir(parents=True, exist_ok=True)
        _clear_upload_dir(folder)
        for old in final.glob("上传-*"):
            _clear_upload_dir(old)
            try:
                old.rmdir()
            except OSError:
                pass  # 里面还有不是链接的东西（作者自己放的），留着
        placed = []
        for src, got in files.items():
            name = min(got["names"], key=lambda n: UPLOAD_NAME_RANK.index(n) if n in UPLOAD_NAME_RANK else 99)
            dest = folder / f"{name}（{'、'.join(dict.fromkeys(got['who']))}）{src.suffix.lower()}"
            try:
                os.link(src, dest)
            except OSError:
                dest.symlink_to(src)
            placed.append(dest.name)
        # 文案也放一份进去：传视频的时候标题、描述、话题就在旁边，不用回工作台复制
        from . import publish_desk

        copy = copypack.read_copy(drafts_root, topic_id) or {}
        shared = publish_desk.shared_entry(copy)
        product = _product_for(topic_id)
        own = {k: publish_desk.own_entry(copy.get("platforms"), k, shared, _traffic(), product) for k in keys}
        groups: dict[tuple[str, str], list[str]] = {}
        for k in keys:
            if own[k].get("title") or own[k].get("body"):
                groups.setdefault((own[k].get("title") or "", own[k].get("body") or ""), []).append(label[k])
        if groups:
            parts = []
            for (title, text), who in groups.items():
                head = f"【{'、'.join(who)}】\n" if len(groups) > 1 else ""
                parts.append(f"{head}{title}\n\n{text}".rstrip())
            tags = [f"话题 · {label[k]}：{' '.join(f'#{t}' for t in own[k].get('tags') or [])}" for k in keys if own[k].get("tags")]
            (folder / "文案.txt").write_text("\n\n".join(parts) + ("\n\n" + "\n".join(tags) if tags else "") + "\n", encoding="utf-8")
            placed.append("文案.txt")
        if body.get("open", True) and not os.environ.get("CONTENT_STUDIO_NO_OPEN") and sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"folder": str(folder), "files": placed, "missing": [f"{n}（{'、'.join(w)}）" for n, w in missing.items()]}


    # -- publish & performance -------------------------------------------

    @app.get("/api/topics/{topic_id}/publish")
    def topic_publish(topic_id: int) -> dict[str, Any]:
        from . import publish

        topic = store.topic(topic_id)
        me = store.self_account(topic.get("account_id")) or store.self_account()
        if me is None:
            return {"account": None, "video": None, "suggestions": [], "recent": [], "stale_sync": False}
        videos = [v for v in store.videos(me["id"]) if not v["is_image_post"]]
        taken = {t["published_video_id"] for t in store.topics(include_archived=True) if t.get("published_video_id") and t["id"] != topic_id}
        result: dict[str, Any] = {
            "account": {"id": me["id"], "nickname": me["nickname"], "last_synced_at": me["last_synced_at"], "syncing": me["id"] in ops.syncing or ops.full_sync_running},
            "stale_sync": publish.sync_is_stale(me["last_synced_at"]),
            "video": None,
            "suggestions": [],
            # 10/5：抖音还没读到刚发的那条时，这里列的旧视频被点成了「就是这条」（54 号对上了 9/12 的视频）。
            # 只列选题建好以后（前一天起）发的；更早的不可能是这条。
            "recent": [{k: v[k] for k in ("video_id", "title", "published_at", "likes")} for v in videos
                       if v["video_id"] not in taken and not publish.older_than_topic(topic, v)][:15],
        }
        linked = store.video(topic["published_video_id"]) if topic.get("published_video_id") else None
        if linked:
            result["video"] = publish.performance(
                linked,
                median_likes=store.account_median(linked["account_id"]),
                snapshots=store.snapshots(linked["video_id"]),
                creator=_creator_rows(creator_db).get(linked["video_id"]),
                has_report=report_file(linked["video_id"]) is not None,
            ) | {"job": job_view(store.job_for_video(linked["video_id"]))}
        else:
            result["suggestions"] = [
                {k: v[k] for k in ("video_id", "title", "published_at", "likes", "score")} for v in publish.suggest_matches(topic, videos, taken)
            ]
        return result

    @app.put("/api/topics/{topic_id}/publish")
    def link_publish(topic_id: int, body: PublishBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not body.video_id:
            return store.update_topic(topic_id, published_video_id=None)
        from . import publish

        video = store.video(body.video_id)
        if video is None or not store.account(video["account_id"])["is_self"]:
            raise ValueError("只能关联你自己账号里已同步的视频")
        if publish.older_than_topic(topic, video) and not body.force:
            day = (video.get("published_at") or "")[:10]
            raise ValueError(f"这条是 {day} 发的，比这个选题建得还早，不会是它。刚发的视频要等工作台读一次抖音才看得到。")
        fields: dict[str, Any] = {"published_video_id": body.video_id}
        if topic["status"] != "published":
            fields["status"] = "published"
        if not topic.get("published_url") or "douyin.com/video/" in topic["published_url"]:  # 改对上的视频，链接跟着换
            fields["published_url"] = f"https://www.douyin.com/video/{body.video_id}"
        return store.update_topic(topic_id, **fields)

    # -- copy packs & platform records ------------------------------------

    @app.get("/api/topics/{topic_id}/copy")
    def get_copy(topic_id: int) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        return {
            "platforms_spec": copypack.PLATFORMS,
            "copy": copypack.read_copy(drafts_root, topic_id),
            "records": store.publish_records(topic_id),
        }

    @app.put("/api/topics/{topic_id}/copy")
    def put_copy(topic_id: int, body: CopyBody) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        unknown = set(body.platforms) - set(copypack.PLATFORMS)
        if unknown:
            raise ValueError(f"未知平台：{sorted(unknown)}")
        current = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms", {})
        merged = {**current, **{k: {"title": v.get("title") or "", "body": v.get("body") or "", "tags": [str(t).strip().lstrip("#") for t in v.get("tags") or [] if str(t).strip()]} for k, v in body.platforms.items()}}
        copypack.save_copy(drafts_root, topic_id, merged)
        return copypack.read_copy(drafts_root, topic_id) or {}

    @app.get("/api/topics/{topic_id}/forms")
    def topic_forms(topic_id: int) -> dict[str, Any]:
        """这一条发到哪、发什么（10/7 作者：拍完在「标题和封面」页一张表上定）。开着的平台每个一行，
        格子是这个平台能发的形式；一个都没勾就是这条不发这个平台。"""
        from . import reach

        topic = store.topic(topic_id)
        lists = reach.forms_list(topic, store.settings()["platform_accounts"] or {})
        skips = store.publish_skips(topic_id)
        return {"platforms": [{"key": p["key"], "label": p["label"], "forms": [] if p["key"] in skips else lists[p["key"]],
                               "choices": [{"key": f, "label": reach.FORM_LABEL[f]} for f in reach.FORM_CHOICES.get(p["key"], ())]}
                              for p in _platform_rows() if p.get("on") and p["key"] in reach.FORM_CHOICES]}

    @app.put("/api/topics/{topic_id}/forms")
    def set_topic_forms(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """{"forms": {"x": ["video", "text"], "wechat_mp": []}}：空列表 = 这条不发这个平台（记进 publish_skips，
        形式不动——空列表进 platform_forms 会被当成「按默认」，平台就悄悄又开了）。"""
        from . import reach

        forms = payload.get("forms")
        if not isinstance(forms, dict) or not forms:
            raise ValueError("要给出平台和形式，比如 {\"forms\": {\"x\": [\"video\", \"text\"]}}")
        keep: dict[str, list[str]] = {}
        said = []
        for k, v in forms.items():
            k = str(k)
            if k not in reach.FORM_CHOICES:
                raise ValueError(f"没有这个平台：{k}")
            wanted = [str(x) for x in (v if isinstance(v, list) else [v])]
            if wanted:
                keep[k] = wanted
                store.set_publish_skip(topic_id, k, skip=False)
                said.append(f"{_pp_label(k)}→{' + '.join(reach.FORM_LABEL.get(x, x) for x in wanted)}")
            else:
                store.set_publish_skip(topic_id, k, skip=True)
                said.append(f"{_pp_label(k)}→不发")
        topic = store.update_topic(topic_id, platform_forms=keep) if keep else store.topic(topic_id)
        store.log_event("stage", f"《{topic['title'][:24]}》改了发到哪、发什么：{'、'.join(said)}", topic_id)
        return topic_forms(topic_id)

    @app.put("/api/topics/{topic_id}/platforms")
    def put_record(topic_id: int, body: RecordBody) -> dict[str, Any]:
        from . import copypack

        store.topic(topic_id)
        if body.platform not in copypack.PLATFORMS:
            raise ValueError("未知平台")
        if body.url and not body.url.startswith(("https://", "http://")):
            raise ValueError("链接需要以 https:// 开头")
        return store.set_publish_record(topic_id, body.platform, published=body.published, url=body.url)

    @app.put("/api/topics/{topic_id}/skip")
    def put_skip(topic_id: int, body: SkipBody) -> dict[str, Any]:
        """这一条不发某个平台：发布台的顺序跳过它，走下一个。"""
        from . import copypack

        store.topic(topic_id)
        if body.platform not in copypack.PLATFORMS:
            raise ValueError("未知平台")
        return {"skipped": sorted(store.set_publish_skip(topic_id, body.platform, skip=body.skip))}

    @app.get("/api/topics/{topic_id}/article")
    def get_article(topic_id: int) -> dict[str, Any]:
        draft = writer.read_draft(store.topic(topic_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="这个选题还没有文章草稿")
        return draft

    @app.put("/api/topics/{topic_id}/article")
    def put_article(topic_id: int, body: ArticleBody) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not body.markdown.strip():
            raise ValueError("正文不能为空")
        path = Path(topic["article_path"]) if topic.get("article_path") else drafts_root / f"topic-{topic_id}" / "article.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.markdown if body.markdown.endswith("\n") else body.markdown + "\n", encoding="utf-8")
        if not topic.get("article_path"):
            store.update_topic(topic_id, article_path=str(path), status="drafting" if topic["status"] == "todo" else topic["status"])
        return writer.read_draft(store.topic(topic_id)) or {}

    @app.get("/api/topics/{topic_id}/article.md")
    def download_article(topic_id: int) -> Response:
        draft = writer.read_draft(store.topic(topic_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="这个选题还没有文章草稿")
        return Response(
            draft["markdown"].encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''topic-{topic_id}.md", "Cache-Control": "no-store"},
        )

    @app.post("/api/topics/{topic_id}/handoff")
    def handoff(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if writer.read_draft(topic) is None:
            raise ValueError("还没有文章草稿，先写文章")
        if topic["status"] in ("todo", "drafting"):
            topic = store.update_topic(topic_id, status="ready")
        return {"topic": topic, "admin_url": store.settings()["yanxishi_admin_url"] or None}

    # -- processing board ------------------------------------------------------

    def shot_days() -> set[str]:
        days = set(store.checked_days("video_shot"))
        for account in store.accounts():
            if account["is_self"]:
                days.update(d for d in (today_plan._day(v["published_at"]) for v in store.videos(account["id"]) if not v["is_image_post"]) if d)
        # 10/20：抖音读不到作品的时候，他在「发」里手动登记的抖音也算那天出了摊（登记时说了是哪天）
        for t in store.topics(include_archived=True):
            rec = store.publish_records(t["id"]).get("douyin")
            day_ = today_plan._day(rec["published_at"]) if rec else None
            if day_:
                days.add(day_)
        return days

    def _in_flight() -> tuple[dict[str, Any], str] | None:
        """正在做的那条，如果它已经交给机器或别人了（剪辑 / 待发）：（选题, 阶段）。
        10/13：「正在做」从开始做一直到发出去，不是到 作者 手上的活做完为止——
        这期间别的选题不能接上来，否则同时有两条在流水线上。"""
        topic = store.focus_topic()
        if topic is None or board_mod.is_shipped(topic):
            return None
        project = None
        if topic.get("video_project"):
            try:
                project = video_project.inspect(video_root(), topic["video_project"])
            except VideoProjectError:
                project = None
        stage = board_mod.stage_for(topic, project, bool(store.publish_records(topic["id"])))
        return (topic, stage) if stage not in board_mod.MINE_STAGES else None

    def _guard_in_flight(topic_id: int, what: str) -> None:
        """正在做的这条还在剪辑 / 待发时，不能把它放下（放回选题池、暂缓、挪走）；「不做了」和「发布完毕」照旧可以。"""
        held = _in_flight()
        if held and held[0]["id"] == topic_id:
            label = dict(board_mod.STAGES)[held[1]]
            raise ValueError(f"《{held[0]['title'][:20]}》还在{label}，不能{what}。发出去一个平台就能在「发」里点「这条发完了，做下一条」，或者点「不做了」")

    def _pipeline_hold(topic_id: int) -> str | None:
        """10/19 作者：从开始写到发出去，整条流水线上只能有一条。正在做的那条没发完，别的都不能开始（没有「换成这条」）。"""
        focus = store.focus_topic()
        if focus is None or focus["id"] == topic_id or board_mod.is_shipped(focus):
            return None
        return f"《{focus['title'][:20]}》还没发完。一次只做一条：发出去一个平台以后，在「发」里点「这条发完了，做下一条」；不想做了在它的页面点「不做了」"

    def _claim_focus(topic_id: int) -> None:
        """开始做 topic_id。正在做的那条还没发完就拒绝：一次只有一条在流水线上。"""
        held = _pipeline_hold(topic_id)
        if held:
            raise ValueError(held)
        store.set_focus(topic_id)

    def _prep_hold(topic_id: int) -> str | None:
        """10/13 作者：一条做完再备下一条。正在做的那条没发完时，别的选题不替它出骨架、密度、口播稿。
        返回为什么不备；可以备（就是正在做的这条，或者现在没有正在做的）返回 None。"""
        focus = store.focus_topic()
        if focus is None or focus["id"] == topic_id or board_mod.is_shipped(focus):
            return None
        return f"《{focus['title'][:20]}》还没发完，先不备下一条的稿子：在「发」里点「这条发完了，做下一条」再来"

    def _check_prep(topic_id: int) -> None:
        reason = _prep_hold(topic_id)
        if reason:
            raise ValueError(reason)

    app.state.prep_hold = _prep_hold  # 口播稿那边（xline）也问它

    @app.get("/api/board")
    def get_board(day: str | None = None) -> dict[str, Any]:
        return _board_view(parse_day(day))

    def _board_view(target: date) -> dict[str, Any]:
        from . import board, opening, qa

        _sweep_shoot_list()  # 正在做 = 今天：先对齐清单和正在做的那条
        series_found = _sync_series()
        topics = store.topics()
        active = [t for t in topics if not board.is_shipped(t)]
        root = None
        try:
            root = video_root()
        except VideoProjectError:
            pass
        cards = []
        for topic in active:
            project = None
            if topic.get("video_project") and root is not None:
                try:
                    project = video_project.inspect(root, topic["video_project"])
                except VideoProjectError:
                    project = None
            card = board.card(topic, project, opening.load(drafts_root, topic["id"]), qa.load(drafts_root, topic["id"]),
                              published=bool(store.publish_records(topic["id"])))
            card["replicate"] = _speak_brief(topic["id"])
            if card["replicate"] and card["replicate"]["mode"] and not card["replicate"]["note_path"] and not topic.get("outline_path"):
                text = ("说这一集（语音输入），存进系列文件夹" if card["replicate"].get("series")
                        else "看着材料说一遍（语音输入），存成你自己的笔记" if card["replicate"].get("mode") == "oral"
                        else "对着拆解说一遍（语音输入），存进原始输出")
                card["next"] = {**(card.get("next") or {}), "text": text, "mine": True}
            cards.append(card)
        today_key = target.isoformat()
        focus = next((c for c in cards if c["focus"]), None)  # 到发出去为止都是正在做的那条，剪辑 / 待发也算
        snoozed = [c for c in cards if c["snoozed_until"] and c["snoozed_until"] > today_key and c is not focus]
        pool = [c for c in cards if c["mine"] and c is not focus and c not in snoozed]
        machine = [c for c in cards if not c["mine"] and c is not focus]
        # 系列：每集现在在哪（选题池 / 正在做 / 暂缓 / 剪辑待发 / 发了 / 不做了）
        where = {c["id"]: "pool" for c in pool} | {c["id"]: "snoozed" for c in snoozed} | {c["id"]: "machine" for c in machine}
        if focus:
            where[focus["id"]] = "focus"
        shipped = {t["id"] for t in topics if board.is_shipped(t)}
        for item in series_found:
            for ep in item["episodes"]:
                tid = ep.get("topic_id")
                ep["state"] = "archived" if ep.get("archived") else "shipped" if tid in shipped else where.get(tid, "pool")
        return {
            "stages": [{"key": k, "label": label} for k, label in board.STAGES],
            "milestones": [{"key": k, "label": label} for k, label in board.MILESTONES],
            "cards": cards,
            "focus": focus,
            "pool": pool,
            "machine": machine,
            "snoozed": snoozed,
            "series": series_found,
            "streak": today_plan.shooting_streak(target, shot_days()),
            "project_root_ok": root is not None,
        }

    # -- 今天：用 KPI 驱动 作者，一次只给一件事（driver.py） ------------------------

    def posted_days() -> set[str]:
        days: set[str] = set()
        for account in store.my_accounts():
            if account["platform"] == PLATFORM_DOUYIN:
                days.update(d for d in (today_plan._day(v["published_at"]) for v in store.videos(account["id"]) if not v["is_image_post"]) if d)
        # 10/20：抖音读不到作品的时候，他在「发」里手动登记的抖音也算那天出了摊（登记时说了是哪天）
        for t in store.topics(include_archived=True):
            rec = store.publish_records(t["id"]).get("douyin")
            day_ = today_plan._day(rec["published_at"]) if rec else None
            if day_:
                days.add(day_)
        return days

    READ_DAILIES = tuple(x for x in (("ai_daily", "AI 日报", "ai_daily"), ("kline_daily", "K 线日报", "kline"))  # (key, 名字, 进项里的 tab)
                         if x[0] in {src.key for src in vault.DAILY_SOURCES})  # 没配这份日报的（别人的库），今天就不提它

    def posted_titles() -> dict[str, list[str]]:
        """哪天在抖音发了哪几条（周历上过去的日子写的就是这个）。"""
        out: dict[str, list[str]] = {}
        for account in store.my_accounts():
            if account["platform"] != PLATFORM_DOUYIN:
                continue
            for v in store.videos(account["id"]):
                day = today_plan._day(v["published_at"])
                if day and not v["is_image_post"]:
                    out.setdefault(day, []).append(" ".join((v.get("title") or "").split())[:40] or "（没有标题）")
        return out

    def _sent_by_day() -> dict[str, list[dict[str, str]]]:
        """哪天往哪个平台发了哪条（不含抖音的新视频）：月历每一格写的就是这个。"""
        from . import backfill, copypack

        out: dict[str, list[dict[str, str]]] = {}
        for r in store.sent_rows():
            when = _local(r["at"])
            if when is None:
                continue
            title = backfill.split_douyin_title(r["title"] or "")["title"] or (r["title"] or "")[:30]
            out.setdefault(when.date().isoformat(), []).append(
                {"platform": r["platform"], "label": (copypack.PLATFORMS.get(r["platform"]) or {}).get("label", r["platform"]), "title": title[:40],
                 "marked": r["kind"] == "mark"})
        return out

    def _month(anchor: date, today: date) -> dict[str, Any]:
        """月历：这个月每一周（周一到周日，头尾带上邻月的几天）。每一天的内容和周历一样，多一项 sent（那天往哪些平台发了什么）。"""
        from . import driver

        first = anchor.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        weeks, start = [], driver.week_start(first)
        sent = _sent_by_day()
        queue = _queue_days(today)
        while start < nxt:
            week = _week(start, today, queue)
            for d in week["days"]:
                d["sent"] = sent.get(d["day"], [])
                d["in_month"] = d["day"][:7] == first.isoformat()[:7]
            weeks.append(week)
            start += timedelta(days=7)
        return {"month": first.isoformat()[:7], "prev": (first - timedelta(days=1)).replace(day=1).isoformat(), "next": nxt.isoformat(),
                "current": first.isoformat()[:7] == today.isoformat()[:7], "weeks": weeks}

    def _sweep_shoot_list() -> list[dict[str, Any]]:
        """清单里那条的选题发出去了，这条就划掉；正在做的那条放第一位（10/6 正在做 = 今天）。返回还没拍的。"""
        for note in store.shoot_list():
            if note.get("topic_id"):
                try:
                    if board_mod.is_shipped(store.topic(note["topic_id"])):
                        store.update_shoot_item(note["id"], done_at=now_iso())
                except StoreError:
                    store.update_shoot_item(note["id"], topic_id=None)
        schedule_mod.focus_first(store)
        return store.shoot_list()

    def _topic_name(note: dict[str, Any]) -> str:
        if note.get("topic_id"):
            try:
                return store.topic(note["topic_id"])["title"]
            except StoreError:
                pass
        return note["text"]

    def _queue_days(today: date, notes: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        """哪天拍哪条。10/19 作者 拿掉排期：只有正在做的那一条，摆在第一个空着的日子；以后的日子空着。
        「接下来要拍的」旧清单留在库里，不再往后排（driver.queue_days 只拿到正在做的那一行）。"""
        from . import driver

        notes = _sweep_shoot_list() if notes is None else notes
        focus = store.focus_topic()
        mine = [n for n in notes if focus is not None and n.get("topic_id") == focus["id"]][:1]
        return driver.queue_days(mine, today, today.isoformat() in posted_days())

    def _week(start: date, today: date, queue: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        """周历的一周（周一到周日）：过去每天算分的几项做没做到、减几分、发了哪条；今天和以后排了拍哪条、别的事。
        分数的规则和「今天」是同一套（driver.kpi_range）；以后哪天拍哪条是「接下来要拍的」按顺序摆出来的，不自动排。"""
        from . import driver

        end = start + timedelta(days=6)
        since, until, tkey = start.isoformat(), end.isoformat(), today.isoformat()
        kpi = kpi_config()
        titles = posted_titles()
        reads: dict[str, bool] = {}
        for i in range(7):
            d = start + timedelta(days=i)
            if d <= today and d.isoformat() >= kpi["read_started"]:
                ok = read_state(d)[1]
                if ok is not None:
                    reads[d.isoformat()] = ok
        filled = backfilled_days()
        days = driver.kpi_range(start, end, today, posted=set(titles) | filled, dms=store.dm_entries(since), started=kpi["started"],
                                x_replies=store.kpi_counts(since, "x_replies"), x_target=int(kpi["x_replies_daily"]),
                                reads=reads, read_started=kpi["read_started"], ship_started=min(titles) if titles else "9999",
                                money=money_days(since), money_started=kpi["money_started"], money_ended=kpi.get("money_ended", "9999"))
        queue = _queue_days(today) if queue is None else queue
        items = store.plan_items(since, until)
        skips = [r for r in store.driver_log(since, "skip") if r["day"] <= until]
        for d in days:
            key = d["day"]
            d["state"] = "today" if key == tkey else "past" if key < tkey else "future"
            d["demerits"] = driver.demerits([d])
            d["shipped"] = titles.get(key, [])
            d["backfilled"] = key in filled and not d["shipped"]  # 这天没发新的，补发了当天那几格
            n = queue.get(key) if key >= tkey else None
            # 一条内容只用一个名字：清单里那行字是加进清单那天写的，选题名后来改过就对不上，照选题名显示
            d["planned"] = [{"id": n["id"], "text": _topic_name(n), "topic_id": n["topic_id"], "done": False}] if n else []
            d["items"] = [{"id": it["id"], "text": it["text"], "done": bool(it["done_at"])} for it in items if it["day"] == key]
            d["skips"] = [{"what": r["key"], "reason": r["reason"]} for r in skips if r["day"] == key]
        counted = [d for d in days if d["ship"] in ("ok", "miss")]
        # 每周下限：一周至少这么多条新视频，少一条减 1 分。周过完才扣；定规矩之前的周不倒扣。
        new_videos, new_target = sum(len(titles.get(d["day"], [])) for d in days), int(kpi["new_weekly"])
        counts = since >= kpi["new_weekly_started"]
        new_short = max(0, new_target - new_videos) if counts and end < today else 0
        return {"start": since, "end": until, "prev": (start - timedelta(days=7)).isoformat(), "next": (start + timedelta(days=7)).isoformat(),
                "current": start == driver.week_start(today), "days": days,
                "shipped": sum(d["ship"] == "ok" for d in days), "ship_days": len(counted), "demerits": driver.demerits(days) + new_short,
                "new_videos": new_videos, "new_target": new_target, "new_short": new_short, "new_counts": counts,
                "x_target": int(kpi["x_replies_daily"])}

    def read_state(day: date) -> tuple[list[dict[str, Any]], bool | None]:
        """那天要读的日报：出了的才要读。返回每份的状态，和是不是都读完了（一份都没出 → None）。"""
        from .extras.dailies import kline_board

        checks = store.daily_checks(day.isoformat())
        try:
            found = {d["key"]: d["path"] for d in vault.dailies(vault_path(), day)}
        except vault.VaultError:
            found = {}
        # K 线日报有自己的 tab（kline_board），profile 里不一定把它列成日报来源：直接看那天的文件在不在
        if not found.get("kline_daily") and kline_board.KLINE_DIR.is_dir():
            tokens = vault.date_tokens(day)
            found["kline_daily"] = next((str(f) for f in sorted(kline_board.KLINE_DIR.iterdir())
                                         if f.suffix == ".md" and "kline-daily-newsletter" in f.name and any(t in f.name for t in tokens)), None)
        items = [{"key": k, "label": label, "tab": tab, "exists": bool(found.get(k)), "read_at": checks.get(k)}
                 for k, label, tab in READ_DAILIES]
        due = [i for i in items if i["exists"]]
        return items, (all(i["read_at"] for i in due) if due else None)

    def kpi_config() -> dict[str, Any]:
        from .store import DEFAULT_SETTINGS

        return {**DEFAULT_SETTINGS["kpi"], **(store.settings().get("kpi") or {})}

    # -- 今天出摊的两条路（9/30 作者）：发一条新视频，或者补发当天那几格旧内容 ------------------
    OUT_KEY = "out"
    bw_lock = threading.Lock()
    bw_run: dict[str, Any] = {"day": "", "items": [], "running": False}  # 补发工作台今天这一批发到哪了

    VIDEO_ONLY_FROM = "2026-10-05"  # 这天起出摊 = 发一条新视频（补发不算）

    def backfilled_days() -> set[str]:
        """没发新视频、但把当天排的补发格子都发完了的日子：也算出摊。"""
        return {r["day"] for r in store.driver_log("", "bfday")}

    def shipped_days() -> set[str]:
        """出摊了的日子 = 发了新视频的 ∪ 补发完成的。只给算分和连续天数用；
        「今天抖音发没发」「这一周几条新视频」还是只看 posted_days()。
        10/4 作者：「每天至少要拍一个视频」——从 VIDEO_ONLY_FROM 起补发不再顶出摊，以前的日子照旧算。"""
        return posted_days() | {d for d in backfilled_days() if d < VIDEO_ONLY_FROM}

    def _open_cells(sheet: dict[str, Any]) -> list[dict[str, Any]]:
        """现在就能发的格子（一条内容 × 一个平台）。不算：不补发的、发过的、还没打好包的、视频平台上没有成片的。"""
        from . import backfill, reach

        labels = {p["key"]: p["label"] for p in sheet["platforms"]}
        cells = []
        for r in sheet["videos"]:
            if r.get("cancelled") or not r["topic_id"] or not r["missing"]:
                continue
            try:
                if not _pack_view(r)["ready"]:
                    continue
            except StoreError:
                continue
            held = _evidence_pending(r["topic_id"]) or bool(_proof_hold(r["topic_id"]))
            for k in r["missing"]:
                if k not in reach.CORE:
                    continue  # 10/4 作者：B 站、YouTube、公众号降权，不用他挑、不算出摊；按排期自动发
                if backfill.KIND.get(k) == "视频" and not r.get("video"):
                    continue
                if held and k in EVIDENCE_HOLD:
                    continue
                cells.append({"video_id": r["video_id"], "topic_id": r["topic_id"], "platform": k, "label": labels.get(k, k),
                              "tier": "major" if k in reach.CORE else "minor", "title": r["headline"] or r["title"][:40]})
        return cells

    def _out_state(today_key: str, sheet: dict[str, Any]) -> dict[str, Any]:
        """今天不发新视频的话补哪几格：作者 在补发工作台自己挑（10/1 起，原来是每天随机抽 4 格）。
        一格发没发直接看全平台追踪（发布台、补发工作台发的有发布记录，外面发的他点「发了」）。
        挑够 4 格（kpi.backfill_cells）并且都发完，这一天记成出摊。"""
        from . import reach

        need = int(kpi_config()["backfill_cells"])
        labels = {p["key"]: p["label"] for p in sheet["platforms"]}
        rows = {r["video_id"]: r for r in sheet["videos"]}
        cells = []
        for row in store.backfill_plan(today_key):
            r = rows.get(row["video_id"])
            if r is None or r.get("cancelled"):
                continue
            cells.append({"slot": row["slot"], "video_id": row["video_id"], "topic_id": r["topic_id"], "platform": row["platform"],
                          "label": labels.get(row["platform"], row["platform"]), "tier": "major" if row["platform"] in reach.CORE else "minor",
                          "title": r["headline"] or r["title"][:40], "sent": row["platform"] not in r["missing"],
                          "marked": (r.get("done") or {}).get(row["platform"]) == "mark"})
        if len(cells) < need:
            # 追平到最后剩下的不够 4 格：有几格算几格，不能让他把能发的都发了还减分
            planned = {(c["video_id"], c["platform"]) for c in cells}
            avail = len(cells) + sum(1 for c in _open_cells(sheet) if (c["video_id"], c["platform"]) not in planned)
            need = min(need, avail) if avail else need
        done = len(cells) >= need and all(c["sent"] for c in cells)
        if done:
            store.driver_mark(today_key, OUT_KEY, "bfday")
        else:
            store.driver_unmark(today_key, OUT_KEY, "bfday")
        modes = [r for r in store.driver_log(today_key, "mode") if r["day"] == today_key]
        return {"mode": modes[-1]["reason"] if modes else None, "cells": cells, "sent": sum(c["sent"] for c in cells), "done": done,
                "need": need, "left": sum(1 for r in sheet["videos"] for k in r["missing"] if k in reach.CORE),
                "running": bw_run["running"] and bw_run["day"] == today_key}

    def _ship_action(cards: list[dict[str, Any]], desk: dict[str, Any], notes: list[dict[str, Any]], rung: str) -> dict[str, Any] | None:
        """出摊这一格现在该做什么：手上快发出去的先做完，再是正在做的那条；都没有就去选题挑一条。"""
        from . import driver

        prefix = "明天出摊：" if rung == "tomorrow" else ""
        topic = desk.get("topic")
        if topic and not any(r["key"] == "douyin" and r["shipped"] for r in desk.get("platforms") or []):
            ap = desk.get("approvals") or {}
            missing = [label for k, label in (("copy", "标题和描述"), ("cover", "封面")) if not ((ap.get(k) or {}).get("approved") and (ap.get(k) or {}).get("valid"))]
            if missing:
                return driver.item(rung, f"pack:{topic['id']}", f"{prefix}《{topic['title'][:24]}》：先把{'、'.join(missing)}定稿",
                                   why="成片好了，定完稿就能发。", go=f"pack/{topic['id']}", button="去定标题和封面")
            return driver.item(rung, f"douyin:{topic['id']}", f"{prefix}把《{topic['title'][:24]}》发到抖音",
                               why="标题和封面都定稿了。抖音页里打开上传文件夹，视频和封面都在里面。", go=f"platform/douyin/{topic['id']}", button="去抖音")
        by_id = {c["id"]: c for c in cards}
        near = [c for c in cards if c["stage"] in ("edit", "ready") and c["next"]["mine"]]
        if near:
            c = max(near, key=lambda c: c["milestone"])
            return driver.item(rung, f"card:{c['id']}", f"{prefix}{c['next']['text']}：《{c['title'][:24]}》", why="离发出最近的这条先做完。", go=f"work/{c['id']}")
        focus = next((c for c in cards if c["focus"] and c["next"]["mine"]), None)
        if focus:
            return driver.item(rung, f"card:{focus['id']}", f"{prefix}{focus['next']['text']}：《{focus['title'][:24]}》", why="正在做的这条。", go=f"work/{focus['id']}")
        # 10/19 作者 拿掉排期：不再从「接下来要拍的」旧清单里接下一条，开始做只有「做这条」一个入口
        return driver.item(rung, "notes:empty", f"{prefix}去选题挑一条", why="现在没有正在做的。在选题 →「我的选题」里点「做这条」。", go="input", button="去选题")

    def _ship_state(today_key: str, posted: set[str], desk: dict[str, Any], cards: list[dict[str, Any]], notes: list[dict[str, Any]]) -> dict[str, Any]:
        """A 出摊：今天这条发到哪些平台了（发视频 / 发文字），下一步是什么。
        今天抖音发了就以那条为准；没发就是发布台手上那条（离发出最近的）。"""
        from . import copypack, driver, reach

        topic = None
        if today_key in posted:
            me = store.self_account()
            vids = {v["video_id"] for v in store.videos(me["id"]) if today_plan._day(v["published_at"]) == today_key} if me else set()
            topic = next((t for t in store.topics() if t.get("published_video_id") in vids), None)
            if topic is None:
                # 没对上视频号的（9/29 那条就是）：抖音链接里带着视频号，照它找
                from .links import post_id

                topic = next((t for t in store.topics() if post_id("douyin", (store.publish_records(t["id"]).get("douyin") or {}).get("url")) in vids), None)
        if topic is None and desk.get("topic"):
            topic = store.topic(desk["topic"]["id"])
        records = store.publish_records(topic["id"]) if topic else {}
        rows = {r["key"]: r for r in desk.get("platforms") or []} if desk.get("topic") and topic and desk["topic"]["id"] == topic["id"] else {}
        accounts = store.settings()["platform_accounts"] or {}
        platforms = []
        for key in publish_desk_mod.SEQUENCE:
            on = bool((accounts.get(key) or {}).get("on")) if key in accounts else key in reach.CORE or key in ("bilibili", "youtube", "wechat_mp")
            if not on:
                continue
            shipped = key in records or (key == "douyin" and topic is not None and bool(topic.get("published_video_id")))
            platforms.append({"key": key, "label": (copypack.PLATFORMS.get(key) or {}).get("label", key), "form": reach.forms_for(topic, accounts)[key],
                              "core": key in reach.CORE, "shipped": shipped, "skipped": bool((rows.get(key) or {}).get("skipped")),
                              "draft": bool(((rows.get(key) or {}).get("job") or {}).get("draft")) and not shipped})
        done_today = today_key in posted
        nxt = _ship_action(cards, desk, notes, "tomorrow" if done_today else "ship")
        # 抖音发了、别的平台还没发完：下一步就是把剩下的发完（出摊 = send everything out）
        left = [p for p in platforms if not p["shipped"] and not p["skipped"] and p["core"]]  # 降权的三个自动发，不催他
        if done_today and topic and left and desk.get("topic") and desk["topic"]["id"] == topic["id"]:
            first = left[0]
            text = f"去{first['label']}后台点发布，回来点「发了」" if first["draft"] else f"发完剩下的平台：下一个是{first['label']}"
            nxt = driver.item("ship", f"rest:{topic['id']}", text, why=f"《{topic['title'][:24]}》抖音已经发了，还差 {len(left)} 个平台。", go=f"platform/{first['key']}/{topic['id']}", button=f"去{first['label']}")
        return {"done": done_today, "topic": {"id": topic["id"], "title": topic["title"]} if topic else None,
                "platforms": platforms, "next": nxt}

    @app.get("/api/today")
    def get_today() -> dict[str, Any]:
        from . import copypack, driver

        today = date.today()
        tkey = today.isoformat()
        kpi = kpi_config()
        posted = posted_days()
        since = (today - timedelta(days=driver.WINDOW)).isoformat()
        dms = store.dm_entries(since)
        xr = store.kpi_counts(since, "x_replies")
        reads = {}
        for i in range(driver.WINDOW):
            d = today - timedelta(days=i)
            if d.isoformat() >= kpi["read_started"]:
                ok = read_state(d)[1]
                if ok is not None:
                    reads[d.isoformat()] = ok
        sheet = get_backfill()
        out = _out_state(tkey, sheet)  # 先算：补发完成的话，今天也算出摊
        shipped = shipped_days()
        days = driver.kpi_days(today, posted=shipped, dms=dms, started=kpi["started"], x_replies=xr, x_target=int(kpi["x_replies_daily"]),
                               reads=reads, read_started=kpi["read_started"], money=money_days(since), money_started=kpi["money_started"], money_ended=kpi.get("money_ended", "9999"))
        reach = get_reach(14)
        notes = _sweep_shoot_list()
        cards = [c for c in get_board(None)["cards"] if not (c.get("snoozed_until") and c["snoozed_until"] > tkey)]
        desk = publish_desk(None)
        skipped = {r["key"] for r in store.driver_log(tkey, "skip") if r["day"] == tkey}
        done_keys = {r["key"] for r in store.driver_log("", "done")}

        # 先处理：机器卡住了、客户交付（有才出现）
        first: list[dict[str, Any]] = []
        try:
            load_cookie_file(cookie_path)
        except CookieFileError as exc:
            first.append(driver.item("blocker", "cookies", "抖音登录过期了：重新导出 cookies", why=str(exc)[:120], go="settings", button="去设置"))
        vs = vault_status(store.settings()["obsidian_vault"])
        if not vs["ok"]:
            first.append(driver.item("blocker", "vault", "Obsidian 连不上", why=vs["message"], go="settings", button="去设置"))
        stopped = (ops.last_full_sync or {}).get("stopped")
        if stopped:
            first.append(driver.item("blocker", "risk", "抖音要求验证：在你的浏览器里打开抖音完成验证", why=str(stopped)[:120], manual=True))
        topic = desk.get("topic")
        for row in desk.get("platforms") or []:
            if topic and (row.get("job") or {}).get("state") == "failed" and not row["shipped"]:
                first.append(driver.item("blocker", f"failed:{topic['id']}:{row['key']}", f"发{row['label']}失败了：去看一眼，点重试",
                                         why=((row["job"] or {}).get("message") or "")[:120], go=f"platform/{row['key']}/{topic['id']}"))
        cutoff = (today - timedelta(days=14)).isoformat()
        for c in _consult_rows():
            if c["stage"] == "done" and c.get("pdf") and (c.get("day") or "") >= cutoff:
                first.append(driver.item("client", f"consult:{c['slug']}", f"把「{c['name']}」的客户版 PDF 发过去",
                                         why=f"{c['day']} 的咨询，纪要已经出来了。发没发工作台看不到，发完点「发了」。",
                                         url=c["pdf"], button="打开 PDF", manual=True))

        # 10/4 起照清单顺序：最上面那条就是今天（或者今天发了以后，明天）要拍的
        target = (today + timedelta(days=1)).isoformat() if tkey in posted else tkey
        ship = _ship_state(tkey, posted, desk, cards, driver.plan_order(notes, target))
        if ship["next"] and ship["next"]["key"] in skipped:
            ship["next"] = None

        # 杂事：手填的平台今天的播放
        wrap: list[dict[str, Any]] = []
        manual = [p["label"] for p in reach.get("platforms") or [] if p["on"] and not p["auto"] and p.get("today") is None and p["key"] in copypack.PLATFORMS]
        if manual:
            wrap.append(driver.item("wrap", f"reach:{tkey}", f"填今天{'、'.join(manual)}的播放", why="1 分钟。概览页的格子里填。", go="output"))

        entry = dms.get(tkey)
        return {
            "day": tkey,
            "demerits": driver.demerits(days),
            "days": days,
            "first": driver.order(first, skipped=skipped, done=done_keys),
            "ship": {**ship, "notes": notes, "suggest": suggest_state()},
            "rd": {"items": read_state(today)[0]},
            "dm": {"entry": entry, "target": kpi["dm_daily"], "baseline_until": kpi["dm_baseline_until"]},
            "xr": {"count": xr.get(tkey), "target": int(kpi["x_replies_daily"])},
            # 10/9 变现动作：今天做了哪些（工作台看到的 + 他写的），本月收入（结果，给 Wendy 的账用）
            "mn": {"how": money_how(tkey).get(tkey, []), "started": kpi["money_started"],
                   "month": driver.month_money(store.revenue(today.replace(day=1).isoformat()), today, target=float(kpi["revenue_monthly"]),
                                               labels={s["key"]: s["label"] for s in money_sources()}) if feature_on("consults") else None},
            "reach": {"avg7": reach.get("avg7"), "target": kpi["reach_daily"], "by": kpi["reach_by"]},
            "wrap": driver.order(wrap, skipped=skipped, done=done_keys),
            "skipped": [r for r in store.driver_log(tkey, "skip") if r["day"] == tkey],
            # 周历：这一周（周一到周日）和他现在连着几天出摊 / 没出摊。上面的 days、demerits 还是最近 7 天，含义不变。
            "week": _week(driver.week_start(today), today),
            "streak": driver.ship_streak(today, shipped),
            # 今天出摊的两条路：发新视频，或者补发这几格（mode 是他早上选的，只决定卡片先给他看哪条路；算分只看结果）
            "out": out,
            # 10/5 起出摊只认新视频（补发不顶），页面不再问「今天发不发新视频」
            "video_only": tkey >= VIDEO_ONLY_FROM,
            # 现在在哪个阶段（追平）：旧内容还剩几格、连续出摊几天、出关没有
            "stage": driver.stage(backlog=out["left"], streak=driver.ship_streak(today, shipped), streak_target=int(kpi["ship_streak_target"])),
        }

    @app.get("/api/today/month")
    def get_month(start: str | None = None) -> dict[str, Any]:
        """月历：start 是那个月里的任意一天，不传就是这个月。"""
        from . import driver

        today = date.today()
        return {**_month(parse_day(start), today), "streak": driver.ship_streak(today, shipped_days())}

    @app.post("/api/today/mode")
    def set_today_mode(body: ModeBody) -> dict[str, Any]:
        """早上那个问题的回答：今天发新视频，还是补发。只决定卡片先给他看哪条路，随时能改；算分只看结果。"""
        if body.mode not in ("new", "backfill"):
            raise ValueError("只能选「发新视频」或「补发」")
        store.driver_mark(date.today().isoformat(), "mode", "mode", body.mode)
        return {"mode": body.mode}

    def _plan_cell(slot: int) -> dict[str, Any]:
        row = next((r for r in store.backfill_plan(date.today().isoformat()) if r["slot"] == slot), None)
        if row is None:
            raise ValueError("今天没有排这一格")
        return row

    @app.post("/api/today/cells/{slot}/sent")
    def cell_sent(slot: int, body: CellSentBody) -> dict[str, Any]:
        """这一格他在外面发了（或者点错了撤回）：记在全平台追踪里，和那边的「标已发」是同一笔。"""
        row = _plan_cell(slot)
        store.set_backfill_mark(row["video_id"], row["platform"], body.sent)
        return {"ok": True}

    # -- 补发工作台（10/1 作者）-------------------------------------------------------------
    # 「我要每天看大家的情绪和 mood……自己想好今天最适合发什么」：在一张和全平台追踪一样的表上点格子，
    # 点的顺序就是发的顺序；换个样子再给他看一遍，他点确认，工作台按顺序一格一格现场发。
    # 证据图找到了、他还没挑：这几个文字平台先不让发（发出去就改不了图了，10/2 那篇就是这么漏的）
    EVIDENCE_HOLD = ("x", "wechat_mp", "miniprogram")

    # B 站、YouTube、X 自己发出去；公众号进草稿箱（9/27 他定的，群发他点）；视频号（腾讯封了自动发布）、
    # 小红书没有自动通道：上传文件夹备好，他传完点「发了」。
    BW_HOW = {"bilibili": ("auto", "自动投稿，B 站审核后公开"), "youtube": ("auto", "自动上传，直接公开"),
              "x": ("auto", "自动发 X 图文文章（被拒就存草稿）"), "wechat_mp": ("draft", "存进公众号草稿箱，群发你点"),
              "channels": ("hand", "视频号不让自动发：上传文件夹备好，你传"), "xiaohongshu": ("hand", "上传文件夹备好，你传")}

    def _bw_how(key: str, default: tuple[str, str] = ("hand", "")) -> tuple[str, str]:
        """这个平台怎么发。试用版没有机器代发：一律「你来传」。"""
        if not feature_on("autopost"):
            return ("hand", "文案和文件备好，你去传，传完点「发了」")
        return BW_HOW.get(key, default)

    BW_UPLOAD = {"channels": "https://channels.weixin.qq.com/platform/post/create",
                 "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish"}

    def _bw_blocked(r: dict[str, Any], platform: str) -> str:
        from . import backfill

        if not r["topic_id"]:
            return "还没接上选题：在全平台追踪点「拿去补发」"
        if backfill.KIND.get(platform) == "视频" and not r.get("video"):
            return "作品库里没有成片"
        if platform in EVIDENCE_HOLD and _evidence_pending(r["topic_id"]):
            return "证据图还没挑：去打包页「插图」那一步，要哪几张、还是都不要"
        if platform in EVIDENCE_HOLD and _proof_hold(r["topic_id"]):
            return _proof_hold(r["topic_id"])
        return "包还没定稿：去打包页定稿"

    def _bw_pick(cells: list[dict[str, Any]], sheet: dict[str, Any], *, again: bool = False) -> list[dict[str, Any]]:
        """他点的格子，按点的顺序；每一格都得是现在就能发的、今天还没排的（again：今天排了还没发出去的，再发一次）。"""
        ready = {(c["video_id"], c["platform"]): c for c in _open_cells(sheet)}
        planned = {(r["video_id"], r["platform"]) for r in store.backfill_plan(date.today().isoformat())}
        out, seen = [], set()
        for c in cells:
            key = (str(c.get("video_id") or ""), str(c.get("platform") or ""))
            if key in seen:
                continue
            seen.add(key)
            if key in planned and not again:
                raise ValueError(f"{ready.get(key, {}).get('title', '这一条')}·{key[1]} 今天已经排上了")
            if key not in ready:
                raise ValueError("有一格现在发不了（发过了，或者包还没定稿），刷新一下再挑")
            out.append(ready[key])
        if not out:
            raise ValueError("先在表里点几格")
        return out

    def _bw_item(c: dict[str, Any]) -> dict[str, Any]:
        return {"video_id": c["video_id"], "topic_id": c["topic_id"], "platform": c["platform"], "label": c["label"], "title": c["title"],
                "how": _bw_how(c["platform"])[0], "upload_url": BW_UPLOAD.get(c["platform"]), "state": "waiting", "message": ""}

    def _bw_snapshot(sheet: dict[str, Any]) -> dict[str, Any]:
        """今天排上的每一格发到哪一步了。排了哪几格存在库里（重启也在）；正在发的进度只在内存里，
        重启以后没进度的格子显示「还没发出去」，能再点一次发。"""
        from . import publisher

        today_key = date.today().isoformat()
        out = _out_state(today_key, sheet)
        with bw_lock:
            if bw_run["day"] != today_key:
                bw_run.update(day=today_key, items=[], running=False)
            live = {(it["video_id"], it["platform"]): dict(it) for it in bw_run["items"]}
            running = bw_run["running"]
        rows = {r["video_id"]: r for r in sheet["videos"]}
        items = []
        for c in out["cells"]:
            it = live.get((c["video_id"], c["platform"]))
            if it is None:
                it = {**_bw_item(c), "state": "idle"}
                # 没有进度（服务重启过）：库里这一格最近一次发布还挂在「在发」，说明上次发到一半被打断——
                # 不给「现在发」，免得同一条发两遍（9/27 YouTube 上传被重启打断过）
                job = next((j for j in store.publish_jobs(c["topic_id"]) if j["platform"] == c["platform"]), None) if c["topic_id"] else None
                if job and job["state"] == "running" and not c["sent"]:
                    it.update(state="stuck", message="上次发到一半被打断了：先去平台后台看一眼有没有发出去")
                elif job and job["state"] == "failed" and not c["sent"]:
                    # 重启以后也要记得上次为什么没发出去——不然又是一句「还没发出去」，他不知道该干什么
                    it.update(state="failed", message=job.get("message") or "", failed_at=job.get("finished_at") or job.get("created_at"))
                elif job and job["state"] == "done" and (job.get("result") or {}).get("published") is False and not c["sent"]:
                    it.update(state="draft", message="")  # 公众号进了草稿箱：重启以后也说清，别让他再发一遍
            it["sent"] = c["sent"]
            if not it["sent"] and it["state"] in ("failed", "login"):
                can_login = bool((publisher_specs().get(c["platform"]) or {}).get("login_argv"))
                it["diag"] = publisher.login_fix(c["platform"]) if it["state"] == "login" else publisher.diagnose(c["platform"], it.get("message") or "", can_login=can_login)
                if it["diag"]["fix"] == "login":
                    it["login"] = _login_view(c["platform"])
                    if it["login"]["state"] == "ok" or (it["state"] == "failed" and _login_cached_ok(c["platform"], after=it.get("failed_at"))):
                        # 已经登好了：这一格是登录之前失败的，下一步是再发，不是再登一次
                        it["diag"] = {**publisher.diagnose(c["platform"], ""), "why": "登好了。这一格是登录之前没发出去的。", "todo": "点「再发一次」。"}
            if it["sent"] and c["topic_id"]:
                # 自动发出去的，链接在这儿就能点（10/3 作者）
                rec = store.publish_records(c["topic_id"]).get(c["platform"]) or {}
                it["url"] = rec.get("url") if str(rec.get("url") or "").startswith("http") else None
            # 他点「发了」记下的（不是工作台自己发出去的）：审核没过、发错了可以撤回
            it["marked"] = ((rows.get(c["video_id"]) or {}).get("done") or {}).get(c["platform"]) == "mark"
            items.append(it)
        return {"items": items, "running": running, "need": out["need"]}

    def _evidence_pending(topic_id: int | None) -> bool:
        try:
            from .extras.proof import evidence
        except ImportError:  # 试用版剪掉了证据这一块：没有要等的证据图
            return False
        if not topic_id or not feature_on("proof"):  # 证据关了（10/13）：不等证据图
            return False
        try:
            art = _article_path(store.topic(topic_id))
        except StoreError:
            return False
        return art is not None and art.is_file() and evidence.pending(art)

    @app.get("/api/backfill/desk")
    def backfill_desk() -> dict[str, Any]:
        """补发工作台那张表：一行一条还有平台没发的内容，一格一个平台——发过了 / 今天排上了 / 能挑 / 发不了（为什么）。"""
        sheet = get_backfill()
        today_key = date.today().isoformat()
        ready = {(c["video_id"], c["platform"]) for c in _open_cells(sheet)}
        planned = {(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key)}
        cols = [p for p in sheet["platforms"] if p["key"] != "douyin"]
        on_keys = _on_keys()
        rows = []
        done_rows = []  # 10/3 作者：发齐了的别消失，折起来，展开能看到每条发在了哪
        for r in sheet["videos"]:
            if r.get("cancelled"):
                continue
            cells = {}
            for p in cols:
                k, key = p["key"], (r["video_id"], p["key"])
                if r["done"].get(k) == "skip":
                    cells[k] = {"state": "skipped"}
                elif k not in r["missing"]:
                    cells[k] = {"state": "sent", "url": (r.get("links") or {}).get(k)}
                elif not p.get("core", True):
                    cells[k] = {"state": "auto"}  # 降权平台：不用他挑，按排期自动发
                elif key in planned:
                    cells[k] = {"state": "planned"}
                elif key in ready:
                    cells[k] = {"state": "open"}
                else:
                    cells[k] = {"state": "blocked", "why": _bw_blocked(r, k)}
            # 「发布完毕」只给打包、发布页还挂着的那几条（两周内、还没发完）——老的补发内容没有「结」这回事
            t = store.topic(r["topic_id"]) if r["topic_id"] else None
            closable = bool(t and _fresh(t) and _unfinished(t, on_keys))
            row = {"video_id": r["video_id"], "topic_id": r["topic_id"], "title": r["headline"] or r["title"][:40],
                   "published_at": r["published_at"], "likes": r.get("likes"), "multiple": r.get("multiple"), "cells": cells,
                   "closable": closable and bool(r["missing"]),
                   # 抖音这一格：每条都从抖音来（10/3 作者：抖音也放进表里，最左边）
                   "douyin": {"url": (r.get("links") or {}).get("douyin"), "hidden": bool(r.get("hidden_on_douyin"))}}
            # 只剩降权平台没发的，对他来说就是发齐了（那几格自动发）
            (rows if any(p["key"] in r["missing"] and p.get("core", True) for p in cols) else done_rows).append(row)
        run = _bw_snapshot(sheet)
        need = run.pop("need")
        return {"platforms": [{**p, "how": _bw_how(p["key"])[0], "how_text": _bw_how(p["key"])[1]} for p in cols],
                "rows": rows, "done_rows": done_rows, "need": need, "planned": len(planned), "run": run}

    @app.post("/api/backfill/desk/preview")
    def backfill_desk_preview(body: dict[str, Any]) -> dict[str, Any]:
        """确认之前换个样子再看一遍：按他点的顺序，每格发出去是什么样、怎么发。"""
        from . import copypack, publish_desk

        sheet = get_backfill()
        picked = _bw_pick(body.get("cells") or [], sheet)
        items = []
        for i, c in enumerate(picked, 1):
            topic = store.topic(c["topic_id"])
            rel = _release_for(topic) or {}
            urls = rel.get("cover_urls") or {}
            copy = copypack.read_copy(drafts_root, c["topic_id"]) or {}
            entry = publish_desk.own_entry(copy.get("platforms"), c["platform"], publish_desk.shared_entry(copy), _traffic(), _product_for(c["topic_id"]))
            how, how_text = _bw_how(c["platform"])
            article = None
            if c["platform"] in ("x", "wechat_mp"):
                pv = backfill_preview(c["topic_id"])
                article = {"title": pv["article_title"], "head": pv["article_head"][:2], "layout_url": pv["layout_url"]}
            cover = urls.get("wide") or urls.get("landscape") if c["platform"] in ("youtube", "bilibili", "wechat_mp", "x") else urls.get("portrait")
            items.append({"n": i, "video_id": c["video_id"], "topic_id": c["topic_id"], "platform": c["platform"], "label": c["label"],
                          "title": c["title"], "how": how, "how_text": how_text, "cover": cover or urls.get("portrait") or urls.get("landscape"),
                          "copy": entry, "article": article})
        out = _out_state(date.today().isoformat(), sheet)
        short = max(0, out["need"] - len(out["cells"]) - len(items))
        return {"items": items, "need": out["need"], "short": short}

    def _bw_run(items: list[dict[str, Any]]) -> None:
        """一格一格按顺序发：前一格发完才发下一格（一次只开一个浏览器）。"""
        # 试用版没有机器代发：每一格都只备好上传文件夹，他自己传
        modes = {**BACKFILL_AUTO, **BACKFILL_DRAFT} if feature_on("autopost") else {}
        for it in items:
            with bw_lock:
                it["state"] = "running"
            # 10/3：YouTube 登录早就过期了，工作台照样去发，回来一屏 traceback。先查一下，没登上就不发，等他点登录
            spec = publisher_specs().get(it["platform"]) or {}
            if it["platform"] in modes and spec.get("login_argv") and _login_ok(it["platform"], spec) is False:
                with bw_lock:
                    it.update(state="login", message="")
                continue
            try:
                if it["platform"] in modes:
                    job = prepare_publish(it["topic_id"], PublishJobBody(platform=it["platform"], mode=modes[it["platform"]], auto=True))["job"]
                    store.update_publish_job(job["id"], state="running", confirmed_at=now_iso())
                    _run_publish(job["id"])
                    job = store.publish_job(job["id"])
                    draft = (job.get("result") or {}).get("published") is False
                    state = "failed" if job["state"] != "done" else "draft" if draft else "done"
                    msg = job.get("message") or ("进了草稿箱，去后台点发布" if draft else "")
                else:
                    upload_folder(it["topic_id"], {"platform": it["platform"], "open": False})
                    state, msg = "hand", "文件夹备好了：视频、封面、文案.txt"
            except HTTPException as exc:
                state, msg = "failed", str(exc.detail)
            except Exception as exc:  # noqa: BLE001 - shown on the item
                state, msg = "failed", str(exc)
            with bw_lock:
                it.update(state=state, message=msg, failed_at=now_iso() if state == "failed" else None)
        with bw_lock:
            bw_run["running"] = False

    @app.post("/api/backfill/desk/drop")
    def backfill_desk_drop(body: dict[str, Any]) -> dict[str, Any]:
        """今天排了、还没发出去的一格，不发了：从今天的格子里拿掉（发出去的拿不掉）。"""
        today_key = date.today().isoformat()
        key = (str(body.get("video_id") or ""), str(body.get("platform") or ""))
        sheet = get_backfill()
        cell = next((c for c in _out_state(today_key, sheet)["cells"] if (c["video_id"], c["platform"]) == key), None)
        if cell is None:
            raise ValueError("今天没有排这一格")
        if cell["sent"]:
            raise ValueError("这一格已经发出去了")
        with bw_lock:
            if any((it["video_id"], it["platform"]) == key and it["state"] in ("waiting", "running") for it in bw_run["items"]):
                raise ValueError("这一格正在发")
            bw_run["items"] = [it for it in bw_run["items"] if (it["video_id"], it["platform"]) != key]
            store.set_backfill_plan(today_key, [(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key) if (r["video_id"], r["platform"]) != key])
        return {"ok": True}

    @app.post("/api/backfill/desk/go")
    def backfill_desk_go(body: dict[str, Any]) -> dict[str, Any]:
        """他点了确认：这几格排进今天，马上按顺序发。"""
        return _bw_start(_bw_pick(body.get("cells") or [], get_backfill(), again=True))

    def _login_cached_ok(key: str, *, after: str | None) -> bool:
        """失败之后的那次探测（登录后会真探一次，存在缓存里，重启也在）说登着：报登录过期的那次是登录之前的事。"""
        from . import channel_probe
        from .paths import config_dir

        spec = publisher_specs().get(key) or {}
        if not spec.get("login_argv"):
            return False
        hit = channel_probe._read_cache(config_dir() / "channel-probes.json").get(key) or {}
        return hit.get("ok") is True and bool(after) and str(hit.get("checked_at") or "") > str(after)


    # 10/3 作者：出了问题要能在这一页马上做、做完自己检测、自己再发。登录跑平台自己的登录命令（弹浏览器 / 扫码窗口），
    # 退出后真探测一次；登上了，就把这个平台今天没发出去的格子（发失败的、等登录的）再发一遍，只发一次。
    platform_logins: dict[str, dict[str, Any]] = {}
    LOGIN_TIMEOUT_SECONDS = 600

    def _login_view(key: str) -> dict[str, Any]:
        with bw_lock:
            cur = dict(platform_logins.get(key) or {"state": "idle", "message": ""})
        cur.pop("proc", None)
        return cur


    def _bw_start(picked: list[dict[str, Any]]) -> dict[str, Any]:
        today_key = date.today().isoformat()
        with bw_lock:
            # 重新发了：之前「登好了」那句作废，这次再要登录就重新给登录按钮
            for c in picked:
                if (platform_logins.get(c["platform"]) or {}).get("state") == "ok":
                    platform_logins.pop(c["platform"], None)
            if bw_run["running"] and bw_run["day"] == today_key:
                raise ValueError("上一批还在发，等它发完")
            if bw_run["day"] != today_key:
                bw_run.update(day=today_key, items=[])
            plan = [(r["video_id"], r["platform"]) for r in store.backfill_plan(today_key)]
            store.set_backfill_plan(today_key, plan + [(c["video_id"], c["platform"]) for c in picked if (c["video_id"], c["platform"]) not in plan])
            store.driver_mark(today_key, "mode", "mode", "backfill")
            items = [_bw_item(c) for c in picked]
            keys = {(c["video_id"], c["platform"]) for c in picked}
            bw_run["items"] = [it for it in bw_run["items"] if (it["video_id"], it["platform"]) not in keys] + items
            bw_run["running"] = True
        store.log_event("publish", "补发工作台：" + "、".join(f"《{c['title'][:16]}》→{c['label']}" for c in picked))
        threading.Thread(target=_bw_run, args=(items,), name="backfill-desk", daemon=True).start()
        return {"started": len(items)}

    @app.get("/api/today/week")
    def get_week(start: str | None = None) -> dict[str, Any]:
        """周历翻到别的周：start 是那一周里的任意一天。"""
        from . import driver

        today = date.today()
        return {**_week(driver.week_start(parse_day(start)), today), "streak": driver.ship_streak(today, shipped_days())}

    def _local(raw: str | None) -> datetime | None:
        """库里的时间（UTC 或带时区）→ 本机时间，好和「现在几点」比。"""
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (value if value.tzinfo else value.astimezone()).astimezone().replace(tzinfo=None)

    @app.post("/api/today/plan")
    def add_plan(body: PlanBody) -> dict[str, Any]:
        """周历上加一件不算分的事（「约两个博主诊断」）。"""
        return {"item": store.add_plan_item(parse_day(body.day).isoformat(), body.text or "")}

    @app.patch("/api/today/plan/{item_id}")
    def patch_plan(item_id: int, body: PlanBody) -> dict[str, Any]:
        store.set_plan_item_done(item_id, bool(body.done))
        return {"ok": True}

    @app.delete("/api/today/plan/{item_id}")
    def delete_plan(item_id: int) -> dict[str, Any]:
        store.delete_plan_item(item_id)
        return {"ok": True}

    # -- 流量视频：看到就想复刻的单条视频，先存下来（swipe.py，9/30 作者） -----------

    swipe_root = data_dir / "swipe"
    # 上次服务停的时候还在下的：线程没了，标成失败让他点重试
    for _row in store.swipe_videos():
        if _row["state"] == "downloading":
            store.update_swipe(_row["id"], state="failed", error="下到一半服务重启了，点重试")


    # -- 补发用到的：哪些平台自己发、哪些进草稿、哪些备文件夹（9/29 作者；10/1 起由补发工作台一格一格发） -------------------------
    # 自己发出去的：B 站（投稿，审核后公开）、YouTube（直接公开）、X（直接发，被拒就存草稿）。
    # 要 作者 点的：公众号（草稿，他群发才推送）、视频号、小红书（上传文件夹备好，他扫码传）。
    BACKFILL_AUTO = {"bilibili": "upload", "youtube": "public", "x": "article_publish"}
    BACKFILL_DRAFT = {"wechat_mp": "draft"}
    BACKFILL_FOLDER = ("channels", "xiaohongshu")
    PACK_KEYS = ("copy", "cover", "article", "figs", "wx")

    def _pack_view(row: dict[str, Any]) -> dict[str, Any]:
        from . import approvals

        topic = store.topic(row["topic_id"])
        rel = _release_for(topic) or {}
        st = _approval_state(topic, rel)
        ap = approvals.status(st["folder"], st["fps"])
        need = ("copy", "cover") if set(row["missing"]) <= {"xiaohongshu"} else tuple(k for k in PACK_KEYS if k not in _pack_skip())
        steps = {k: ("lock" if ap[k]["approved"] and ap[k]["valid"] else "made" if ap[k]["made"] else "no") for k in need}
        return {"topic_id": row["topic_id"], "video_id": row["video_id"], "title": row["headline"] or row["title"][:40],
                "multiple": row["multiple"], "published_at": row["published_at"], "missing": row["missing"],
                "ready": all(v == "lock" for v in steps.values()), "steps": steps,
                "machine": any(ap[k].get("by") == "machine" for k in need if ap[k]["approved"]),
                "cover": (rel.get("cover_urls") or {}).get("portrait")}

    @app.get("/api/today/backfill/{topic_id}/preview")
    def backfill_preview(topic_id: int) -> dict[str, Any]:
        """在「今天」里就地看一眼：三张封面、标题描述话题、文章开头、插图，完整排版另开一页。"""
        from urllib.parse import quote

        from . import copypack, illustrate as il, publish_desk

        topic = store.topic(topic_id)
        rel = _release_for(topic) or {}
        entry = publish_desk.shared_entry(copypack.read_copy(drafts_root, topic_id))
        art = writer.read_draft(topic)
        paras = []
        art_title = None
        if art:
            head = re.search(r"^#\s+(.+)$", art["markdown"], re.M)
            art_title = head.group(1).strip() if head else entry["title"]
            for block in re.split(r"\n\s*\n", art["markdown"]):
                b = block.strip()
                if not b or b.startswith("![") or b.startswith("# "):
                    continue
                paras.append(re.sub(r"[*#>`]", "", b))
                if len(paras) >= 4:
                    break
        figs = il.state(_article_path(topic))["images"] if art else []
        return {
            "topic_id": topic_id, "title": entry["title"], "body": entry["body"], "tags": entry["tags"],
            "covers": {k: v for k, v in (rel.get("cover_urls") or {}).items() if v},
            "article_title": art_title, "article_head": paras,
            "figs": [f"/api/topics/{topic_id}/article-file/{il.FOLDER}/{quote(f['file'])}" for f in figs],
            "layout_url": f"/api/topics/{topic_id}/wechat-preview.html" if art else None,
        }

    @app.put("/api/today/x-replies")
    def put_x_replies(body: CountBody) -> dict[str, Any]:
        day = body.day or date.today().isoformat()
        store.set_kpi_count(day, "x_replies", body.value)
        store.log_event("xr", f"{day} X 回复：{body.value} 条")
        return {"ok": True}

    @app.post("/api/today/notes")
    def add_note(body: ShootBody) -> dict[str, Any]:
        store.add_shoot_item(body.text or "", top=body.top, planned_day=parse_day(body.planned_day).isoformat() if body.planned_day else None)
        return {"notes": store.shoot_list()}

    @app.patch("/api/today/notes/{item_id}")
    def patch_note(item_id: int, body: ShootBody) -> dict[str, Any]:
        if body.move:
            return {"notes": store.move_shoot_item(item_id, 1 if body.move > 0 else -1)}
        if body.text is not None:
            store.update_shoot_item(item_id, text=body.text.strip()[:200] or store.shoot_item(item_id)["text"])
        if body.planned_day is not None:  # 周历：排到某一天；空字符串 = 不排了
            store.update_shoot_item(item_id, planned_day=parse_day(body.planned_day).isoformat() if body.planned_day else None)
        if body.at is not None:  # 日历上拖到某天：放到清单的那一位（正在做 = 今天，见 _place_note）
            _place_note(store.shoot_item(item_id), body.at)
        return {"notes": store.shoot_list()}

    # -- 选题拖进日历（10/5 作者）：日历上的日子就是「接下来要拍的」按顺序摆，拖到哪天 = 插到清单那一位 --
    def _queue_view(days: int) -> dict[str, Any]:
        from . import driver

        today = date.today()
        notes = _sweep_shoot_list()
        shipped_today = today.isoformat() in posted_days()
        queue = driver.queue_days(notes, today, shipped_today)
        first = today + timedelta(days=1 if shipped_today else 0)
        shown = [(first + timedelta(days=i)).isoformat() for i in range(days)]
        return {"today": today.isoformat(), "shipped_today": shipped_today,
                "days": [{"day": k, "note": queue.get(k)} for k in shown], "more": max(0, len(notes) - len(shown)), "notes": notes}

    @app.get("/api/today/queue")
    def get_queue(days: int = 14) -> dict[str, Any]:
        return _queue_view(min(max(days, 1), 60))

    @app.post("/api/today/queue")
    def queue_topics(body: QueueTopicsBody) -> dict[str, Any]:
        """选题池里的选题放进「接下来要拍的」：拖到某天就从那一位放；系列「整个排上」就是按集数接在最后。
        已经在清单里的那条只挪位置，不重复加。是他拖的、他点的，不自动加。"""
        open_by_topic = {n["topic_id"]: n for n in store.shoot_list() if n.get("topic_id")}
        at = body.at
        added = 0
        for tid in body.topic_ids:
            topic = store.topic(tid)
            if topic.get("archived_at") or board_mod.is_shipped(topic):
                continue
            note = open_by_topic.get(tid)
            if note is None:
                note = store.add_shoot_item(topic["title"], topic_id=tid)
                open_by_topic[tid] = note
                added += 1
            if at is not None:
                _place_note(note, at)
                at += 1
        if added:
            store.log_event("plan", f"{added} 条选题排进了「接下来要拍的」")
        return _queue_view(14)

    @app.delete("/api/today/notes/{item_id}")
    def delete_note(item_id: int) -> dict[str, Any]:
        store.delete_shoot_item(item_id)
        return {"notes": store.shoot_list()}

    # -- 02 排期（10/6 作者）：选题包拖进日历、回收站、一键写开头和骨架（schedule.py）---------------
    # 10/19 排期页拿掉了（页面用 GET /api/my-topics）；这几个接口和清单数据留着不删，「+ 口述一条」还走 /api/schedule/oral。
    # 日期仍不存：拖到第几天 = 放到「接下来要拍的」第几位，日历不留空档。正在做 = 今天。
    def _raw_folder() -> str:
        from .extras.xline import x_suggest

        return next((src.folder for src in vault.INBOX_SOURCES if src.key == "raw"), x_suggest.RAW_FOLDER)

    def _start_kind(card: dict[str, Any] | None) -> str:
        r = (card or {}).get("replicate")
        if not r:
            return "focus"
        if r.get("series") and not r.get("mode"):
            return "say"
        return "resume" if r.get("mode") else "replicate"

    def _pack(topic: dict[str, Any], card: dict[str, Any] | None, series_of: dict[int, tuple[str, int]], raw: str) -> dict[str, Any]:
        tid = topic["id"]
        with writing_lock:
            coupon_running = 60_000 + tid in writing
        name, n = series_of.get(tid, (None, None))
        return {
            "id": tid, "title": topic["title"], "series": name, "ep": n,
            "hook": schedule_mod.has_hooks(topic), "skeleton": bool(topic.get("outline_path")),
            "coupon": schedule_mod.coupon_path(drafts_root, tid).is_file(),
            "words": schedule_mod.own_words(topic, raw), "said": bool(((card or {}).get("replicate") or {}).get("note_path")),
            "own": bool(_script_runner()) and schedule_mod.content_mode(topic, raw, drafts_root)["mode"] == "own",
            "script": schedule_mod.script_path(drafts_root, tid).is_file(),
            "writing": topic.get("outline_state") == "running" or coupon_running,
            "failed": topic.get("outline_error") if topic.get("outline_state") == "failed" else None,
            "qa": (card or {}).get("qa"), "start": _start_kind(card), "focus": bool(topic.get("is_focus")),
            "held": bool(_prep_hold(tid)),
            "snoozed_until": topic.get("snoozed_until"), "archived_at": topic.get("archived_at"),
        }

    def _write_preview(cards: list[dict[str, Any]], topics: dict[int, dict[str, Any]], series_of: dict[int, tuple[str, int]],
                       order: list[int]) -> dict[str, Any]:
        mine = [{**topics[c["id"]], "_series": c["id"] in series_of} for c in cards
                if c["mine"] and c["id"] in topics and not _prep_hold(c["id"])]  # 一条做完再备下一条
        return schedule_mod.targets(mine, order, _raw_folder(), drafts_root, coupon=feature_on("coupon"), script=bool(_script_runner()))

    @app.get("/api/my-topics")
    def topic_pool() -> dict[str, Any]:
        """选题 →「我的选题」（10/19 作者 拿掉排期）：正在做的那一条、还没做的、不做了的。
        点「做这条」走 POST /api/topics/{id}/focus；「不做了 / 放回」走 PATCH archived。"""
        b = _board_view(date.today())
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        series_of = {ep["topic_id"]: (s["name"], ep["n"]) for s in b["series"] for ep in s["episodes"] if ep.get("topic_id")}
        raw = _raw_folder()
        focus = b["focus"]
        waiting = [c for c in b["pool"] + b["snoozed"] if c["id"] in topics and (not focus or c["id"] != focus["id"])]
        waiting.sort(key=lambda c: c["id"], reverse=True)
        trash = sorted((t for t in topics.values() if t.get("archived_at") and not board_mod.is_shipped(t)),
                       key=lambda t: t["archived_at"], reverse=True)[:40]
        return {
            "focus": {**_pack(topics[focus["id"]], focus, series_of, raw), "stage": focus.get("stage")} if focus and focus["id"] in topics else None,
            "pool": [_pack(topics[c["id"]], c, series_of, raw) for c in waiting],
            "trash": [_pack(t, None, series_of, raw) for t in trash],
            "held": _pipeline_hold(0),
        }

    @app.get("/api/schedule")
    def get_schedule() -> dict[str, Any]:
        today = date.today()
        b = _board_view(today)
        notes = store.shoot_list()
        shipped_today = today.isoformat() in posted_days()
        first = today + timedelta(days=1 if shipped_today else 0)
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        cards = {c["id"]: c for c in b["cards"]}
        series_of = {ep["topic_id"]: (s["name"], ep["n"]) for s in b["series"] for ep in s["episodes"] if ep.get("topic_id")}
        raw = _raw_folder()
        order = [n["topic_id"] for n in notes if n.get("topic_id")]
        queued = set(order)
        queue = []
        for i, n in enumerate(notes):
            tid = n.get("topic_id")
            queue.append({"id": n["id"], "text": n["text"], "topic_id": tid, "day": (first + timedelta(days=i)).isoformat(),
                          "pack": _pack(topics[tid], cards.get(tid), series_of, raw) if tid in topics else None})
        pool = [_pack(topics[c["id"]], c, series_of, raw) for c in b["pool"] if c["id"] not in queued and c["id"] in topics]
        if b["focus"] and b["focus"]["id"] not in queued:
            pool.insert(0, _pack(topics[b["focus"]["id"]], b["focus"], series_of, raw))
        snoozed = [_pack(topics[c["id"]], c, series_of, raw) for c in b["snoozed"] if c["id"] in topics]
        trash = sorted((t for t in topics.values() if t.get("archived_at") and not board_mod.is_shipped(t)),
                       key=lambda t: t["archived_at"], reverse=True)[:40]
        series = []
        for s in b["series"]:
            eps = s["episodes"]
            left = [e["topic_id"] for e in eps if e.get("state") in ("pool", "focus") and e.get("topic_id") not in queued]
            series.append({"name": s["name"], "total": len(eps), "said": sum(1 for e in eps if e.get("said")),
                           "shipped": sum(1 for e in eps if e.get("state") == "shipped"),
                           "queued": sum(1 for e in eps if e.get("topic_id") in queued), "left": left})
        preview = _write_preview(b["cards"], topics, series_of, order)
        with batch_lock:
            job = dict(batch)
        return {
            "today": today.isoformat(), "first": first.isoformat(), "shipped_today": shipped_today,
            "queue": queue, "pool": pool, "snoozed": snoozed, "series": series,
            "trash": [_pack(t, None, series_of, raw) for t in trash],
            "write": {"can": len(preview["ids"]), "held": _prep_hold(0), "skip": schedule_mod.skip_line(len(preview["unspoken"]), len(preview["others"]), len(preview["empty"])),
                      "job": _batch_public(job)},
        }

    def _place_note(note: dict[str, Any], at: int) -> None:
        """清单上的一行放到第 at 位（日历第 at 天）。正在做 = 今天：放到今天就开始做它；
        正在做的那条挪去别的日子，就先不做它，新的第一条接上。今天页和排期页拖日历都走这里。"""
        focus = store.focus_topic()
        if at <= 0:
            tid = _note_topic(note)
            _claim_focus(tid)  # 前一条还在剪辑 / 待发：拒绝，清单也不动
            store.place_shoot_item(note["id"], 0)
            if not focus or focus["id"] != tid:
                store.log_event("focus", f"开始做《{store.topic(tid)['title'][:30]}》（拖到今天）", tid)
        else:
            if focus and note.get("topic_id") == focus["id"]:
                _guard_in_flight(focus["id"], "挪去别的日子")
                store.set_focus(None)
            store.place_shoot_item(note["id"], at)
        schedule_mod.focus_first(store)

    def _note_topic(note: dict[str, Any]) -> int:
        """手写的一条（今天页「接下来要拍的」里写的）要变成能做、能扔的东西：先建成一个选题。"""
        if note.get("topic_id"):
            return int(note["topic_id"])
        topic = store.create_topic(note["text"], formats="video")
        store.update_shoot_item(note["id"], topic_id=topic["id"])
        return topic["id"]

    @app.post("/api/schedule/place")
    def schedule_place(body: ScheduleBody) -> dict[str, Any]:
        """拖到日历某一天。拖到今天 = 开始做它（正在做 = 今天）；正在做的那条拖去别的日子 = 先不做它。"""
        if body.at is None or (body.topic_id is None and body.note_id is None):
            raise ValueError("要说清楚拖的是哪一包、拖到哪天")
        _sweep_shoot_list()
        at = max(0, body.at)
        if body.note_id is not None:
            note = store.shoot_item(body.note_id)
        else:
            topic = store.topic(body.topic_id)
            if topic.get("archived_at"):
                raise ValueError("这包在回收站里：先拖回选题池")
            if board_mod.is_shipped(topic):
                raise ValueError("这条已经发出去了")
            note = next((n for n in store.shoot_list() if n.get("topic_id") == topic["id"]), None) \
                or store.add_shoot_item(topic["title"], topic_id=topic["id"])
        _place_note(note, at)
        return get_schedule()

    @app.post("/api/schedule/pool")
    def schedule_unplan(body: ScheduleBody) -> dict[str, Any]:
        """拖回选题池：不排了（从回收站拖回来也是这里）。"""
        if body.note_id is not None:
            tid = _note_topic(store.shoot_item(body.note_id))
        elif body.topic_id is not None:
            tid = body.topic_id
        else:
            raise ValueError("要说清楚拖的是哪一包")
        topic = store.topic(tid)
        if topic.get("archived_at"):
            patch_topic(tid, TopicBody(archived=False))
        if topic.get("is_focus"):
            _guard_in_flight(tid, "放回选题池")
            store.set_focus(None)
        schedule_mod.drop_notes(store, tid)
        schedule_mod.focus_first(store)
        return get_schedule()

    @app.post("/api/schedule/trash")
    def schedule_trash(body: ScheduleBody) -> dict[str, Any]:
        """扔进回收站 = 不做了（归档，笔记和文件都不删，随时拖回来）。"""
        if body.note_id is not None:
            tid = _note_topic(store.shoot_item(body.note_id))
        elif body.topic_id is not None:
            tid = body.topic_id
        else:
            raise ValueError("要说清楚扔的是哪一包")
        title = store.topic(tid)["title"]
        patch_topic(tid, TopicBody(archived=True))
        store.log_event("plan", f"《{title[:30]}》扔进了回收站", tid)
        schedule_mod.focus_first(store)
        return get_schedule()

    # 「写开头和骨架」：一包一包写（骨架 → 付息稿 → 下一包），进度存在 drafts 根下，重启后接着写。
    batch_lock = threading.Lock()
    batch: dict[str, Any] = {"running": False}

    def _batch_public(job: dict[str, Any]) -> dict[str, Any] | None:
        if not job.get("started_at"):
            return None
        current = job.get("current")
        try:
            current_title = store.topic(current)["title"] if current else None
        except StoreError:
            current_title = None
        return {"running": bool(job.get("running")), "total": job.get("total", 0), "done": job.get("done", 0),
                "current": current_title, "wrote": len(job.get("wrote") or []), "failed": job.get("failed") or [],
                "skip": job.get("skip") or "", "note": job.get("note"), "finished_at": job.get("finished_at")}

    def _batch_save() -> None:
        path = drafts_root / schedule_mod.STATE_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({k: v for k, v in batch.items() if k != "running"}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("schedule write state not saved: %s", exc)

    def _batch_one(tid: int) -> None:
        _check_prep(tid)  # 写的过程中正在做的换了：别替下一条备料
        from . import coupon

        topic = store.topic(tid)
        if topic.get("archived_at") or board_mod.is_shipped(topic):
            return
        run = _script_runner()
        if run and _own(topic):  # 10/12：有他原话的，准备的是口播稿（原话走第一轮），不写骨架、密度
            if schedule_mod.script_path(drafts_root, tid).is_file():
                return
            run(tid, "note" if schedule_mod.own_words(topic, _raw_folder()) else "transcript")
            return
        if not topic.get("outline_path"):
            with writing_lock:
                if -tid in writing:
                    raise writer.WriterError("这包正在单独写，跳过")
                writing.add(-tid)
            store.update_topic(tid, outline_state="running", outline_error=None)
            _outline_topic(tid, chain=False)
            topic = store.topic(tid)
            if not topic.get("outline_path"):
                raise writer.WriterError(f"骨架没写成：{topic.get('outline_error') or '原因不明'}")
        if schedule_mod.coupon_path(drafts_root, tid).is_file() or not feature_on("coupon"):
            return  # 10/9：付息稿关了，这包写完骨架就算写好
        try:
            coupon.load_framework()
        except Exception as exc:  # noqa: BLE001 - 框架文件不在：骨架写了，付息稿等他放好文件
            with batch_lock:
                batch["note"] = f"密度没排：{str(exc)[:120]}"
            return
        with writing_lock:
            if 60_000 + tid in writing:
                raise writer.WriterError("这包的密度正在单独排，跳过")
            writing.add(60_000 + tid)
        coupon_errors.pop(tid, None)
        _coupon_topic(tid)
        if not schedule_mod.coupon_path(drafts_root, tid).is_file():
            raise writer.WriterError(f"密度没排成：{coupon_errors.get(tid) or '原因不明'}")

    def _batch_run() -> None:
        while True:
            with batch_lock:
                if not batch.get("pending"):
                    break
                tid = batch["pending"][0]
                batch["current"] = tid
            try:
                _batch_one(tid)
                ok, err = True, None
            except Exception as exc:  # noqa: BLE001 - 一包失败接着写下一包，最后一起说
                ok, err = False, str(exc)[:200] or type(exc).__name__
            with batch_lock:
                batch["pending"].pop(0)
                batch["done"] = batch.get("done", 0) + 1
                batch["current"] = None
                if ok:
                    batch.setdefault("wrote", []).append(tid)
                else:
                    try:
                        title = store.topic(tid)["title"]
                    except StoreError:
                        title = f"#{tid}"
                    batch.setdefault("failed", []).append({"id": tid, "title": title, "error": err})
                _batch_save()
        with batch_lock:
            batch["running"] = False
            batch["finished_at"] = now_iso()
            _batch_save()
            wrote, failed, skip = len(batch.get("wrote") or []), len(batch.get("failed") or []), batch.get("skip")
        store.log_event("plan", f"准备稿子：写好 {wrote} 包" + (f"，{failed} 包没写成" if failed else "") + (f"；{skip}，跳过" if skip else ""))

    @app.post("/api/schedule/write")
    def schedule_write() -> dict[str, Any]:
        """他点了「写开头和骨架」：选题池和日历上所有有他原话、还缺骨架或付息稿的包，排好队一包一包写。"""
        outline_mod.load_framework()  # 框架文件缺了当场说清楚
        b = _board_view(date.today())
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        series_of = {ep["topic_id"]: (s["name"], ep["n"]) for s in b["series"] for ep in s["episodes"] if ep.get("topic_id")}
        order = [n["topic_id"] for n in _sweep_shoot_list() if n.get("topic_id")]
        preview = _write_preview(b["cards"], topics, series_of, order)
        skip = schedule_mod.skip_line(len(preview["unspoken"]), len(preview["others"]), len(preview["empty"]))
        with batch_lock:
            if batch.get("running"):
                return {"started": False, "message": "正在写，写完会告诉你", "job": _batch_public(dict(batch))}
            if not preview["ids"]:
                held = _prep_hold(0)
                return {"started": False, "message": held or "没有能写的包" + (f"：{skip}" if skip else ""), "job": None}
            batch.clear()
            batch.update({"running": True, "pending": list(preview["ids"]), "total": len(preview["ids"]), "done": 0,
                          "wrote": [], "failed": [], "skip": skip, "note": None, "started_at": now_iso(), "finished_at": None})
            _batch_save()
        store.log_event("plan", f"开始准备稿子：{len(preview['ids'])} 包" + (f"（{skip}，跳过）" if skip else ""))
        threading.Thread(target=_batch_run, name="schedule-write", daemon=True).start()
        return {"started": True, "message": f"开始写 {len(preview['ids'])} 包，一包几分钟" + (f"；{skip}，跳过" if skip else ""),
                "job": _batch_public(dict(batch))}

    def _schedule_write_resume() -> None:
        path = drafts_root / schedule_mod.STATE_FILE
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not state.get("pending") or state.get("finished_at"):
            return
        with batch_lock:
            if batch.get("running"):
                return
            batch.clear()
            batch.update(state, running=True, current=None)
        store.log_event("plan", f"写开头和骨架接着写：还剩 {len(state['pending'])} 包")
        threading.Thread(target=_batch_run, name="schedule-write", daemon=True).start()

    @app.post("/api/today/notes/{item_id}/start")
    def start_note(item_id: int) -> dict[str, Any]:
        """他点了「开始做」：用这条建一个选题、设成正在做，接着写提纲。是他点的，不是自动加。"""
        note = store.shoot_item(item_id)
        topic = note.get("topic_id") and store.topic(note["topic_id"])
        if not topic:
            topic = store.create_topic(note["text"], formats="video")
            store.update_shoot_item(item_id, topic_id=topic["id"])
        _claim_focus(topic["id"])
        store.log_event("focus", f"开始做《{topic['title'][:30]}》（从「接下来要拍的」）", topic["id"])
        return {"topic": store.topic(topic["id"])}

    @app.put("/api/today/dm")
    def put_dm(body: DmBody) -> dict[str, Any]:
        day = body.day or date.today().isoformat()
        if body.replied > body.received:
            raise ValueError("回了的不能比收到的多")
        store.set_dm(day, body.received, body.replied)
        store.log_event("dm", f"{day} 私信：收到 {body.received}，回了 {body.replied}")
        return {"ok": True}

    @app.post("/api/today/money")
    def mark_money(body: MoneyActionBody) -> dict[str, Any]:
        """今天的变现动作工作台看不到（发了报价、约了客户）：他写一句做了什么，就算做了。"""
        note = body.note.strip()
        if not note:
            raise ValueError("写一句做了什么：给谁发了报价、回了谁")
        day = date.today().isoformat()
        store.driver_mark(day, "money", "money", note[:200])
        store.log_event("money", f"变现动作：{note[:60]}")
        return {"ok": True}

    @app.get("/api/revenue")
    def get_revenue(since: str = "") -> dict[str, Any]:
        labels = {s["key"]: s["label"] for s in money_sources()}
        return {"rows": [{**r, "label": labels.get(r["source"], r["source"])} for r in store.revenue(since)], "sources": money_sources()}

    @app.post("/api/revenue")
    def add_revenue(body: RevenueBody) -> dict[str, Any]:
        day = body.day or date.today().isoformat()
        date.fromisoformat(day)
        row = store.add_revenue(day, body.amount, body.source.strip(), body.note)
        store.log_event("revenue", f"{day} 记了一笔 ¥{body.amount:,.0f}（{body.source}）")
        return row

    @app.delete("/api/revenue/{rid}")
    def delete_revenue(rid: int) -> dict[str, Any]:
        if not store.delete_revenue(rid):
            raise HTTPException(status_code=404, detail="没有这一笔")
        return {"ok": True}

    @app.post("/api/today/done")
    def mark_done(body: DriverMarkBody) -> dict[str, Any]:
        store.driver_mark(date.today().isoformat(), body.key, "done")
        return {"ok": True}

    @app.post("/api/today/skip")
    def mark_skip(body: DriverMarkBody) -> dict[str, Any]:
        reason = (body.reason or "").strip()
        if not reason:
            raise ValueError("跳过要写一句为什么")
        store.driver_mark(date.today().isoformat(), body.key, "skip", reason[:200])
        store.log_event("skip", f"跳过「{body.key}」：{reason[:120]}")
        return {"ok": True}

    # 「我今天不知道拍什么」：只有他点了才建议，从他自己的选题里挑一条，说为什么
    suggest_box: dict[str, Any] = {"state": None}

    def suggest_state() -> dict[str, Any] | None:
        return suggest_box["state"]

    @app.post("/api/today/suggest")
    def post_suggest() -> dict[str, Any]:
        from . import driver_suggest

        if (suggest_box["state"] or {}).get("running"):
            return suggest_box["state"]
        cards = [c for c in get_board(None)["cards"] if c["next"]["mine"]]
        if not cards:
            raise ValueError("「我的选题」是空的：先去选题挑几条点「加入选题」")
        suggest_box["state"] = {"running": True, "day": date.today().isoformat()}

        def run() -> None:
            try:
                pick = driver_suggest.suggest(cards, latest_adjustments(), write_fn=suggest_fn or writer.cli_write)
                suggest_box["state"] = {"running": False, "day": date.today().isoformat(), **pick}
            except Exception as exc:  # noqa: BLE001 - 一句话告诉他
                suggest_box["state"] = {"running": False, "day": date.today().isoformat(), "error": str(exc)[:200]}

        threading.Thread(target=run, name="today-suggest", daemon=True).start()
        return suggest_box["state"]

    @app.post("/api/today/suggest/take")
    def take_suggest() -> dict[str, Any]:
        st = suggest_box["state"] or {}
        if not st.get("topic_id"):
            raise ValueError("还没有建议")
        topic = store.topic(st["topic_id"])
        store.add_shoot_item(topic["title"], top=True, topic_id=topic["id"])
        suggest_box["state"] = None
        return {"notes": store.shoot_list()}

    # -- Anna 的标准 ----------------------------------------------------------


    # ---------------- 在哪找到我（10/6 作者：GitHub 和个人网站放进工作台，只给自己点） ----------------


    # -- 补发队列：抖音发过、别的平台还没发的旧视频 ------------------------------

    backfill_dl: dict[str, dict[str, Any]] = {}
    backfill_lock = threading.Lock()

    def _backfill_file(video_id: str) -> Path | None:
        from . import archive

        return archive.video_file(archive_root(), video_id)

    archive_state: dict[str, Any] = {}
    archive_lock = threading.Lock()

    def start_archive(limit: int | None = None) -> bool:
        """后台把没存的抖音视频存下来，一次一条。已经在跑就不再起一个。"""
        from .cli import archive_new_videos

        with archive_lock:
            if archive_state.get("state") == "downloading":
                return False
            if archive_root() is None:
                return False
            archive_state.clear()
            archive_state.update({"state": "downloading", "done": 0, "total": None})

        def progress(p: dict[str, Any]) -> None:
            with archive_lock:
                archive_state.update(p)

        def run() -> None:
            try:
                archive_new_videos(store, cookie_path=cookie_path, limit=limit, on_progress=progress)
            except Exception as exc:  # noqa: BLE001 - shown on the queue
                logger.warning("archive failed: %s", exc)
                with archive_lock:
                    archive_state.update({"state": "failed", "failed": {"error": str(exc)[:200]}})

        threading.Thread(target=run, name="douyin-archive", daemon=True).start()
        return True


    def _backfill_state() -> tuple[list[dict[str, Any]], dict[str, int], dict[int, dict[str, Any]]]:
        from . import backfill, copypack, publish_desk

        me = store.self_account()
        if me is None:
            return [], {}, {}
        keep = set(store.settings().get("tracker_keep") or [])
        public = {v["video_id"] for v in store.public_videos(me["id"])}
        # 抖音上藏起来的（私密）不在公开主页上；作者 点名要留的照样列（别的平台还要发）
        videos = [v for v in store.videos(me["id"]) if not v["is_image_post"] and (v["video_id"] in public or v["video_id"] in keep)]
        topics = store.topics(include_archived=True)
        records = {t["id"]: store.publish_records(t["id"]) for t in topics}
        copies = {}
        for t in topics:
            entry = publish_desk.shared_entry(copypack.read_copy(drafts_root, t["id"]))
            if entry["title"]:
                copies[t["id"]] = entry["title"]
        links = backfill.link_topics(videos, topics, records, copies)
        return videos, links, records

    @app.get("/api/backfill")
    def get_backfill() -> dict[str, Any]:
        from . import backfill, publish_desk

        videos, links, records = _backfill_state()
        me = store.self_account()
        median = store.account_median(me["id"]) if me else None
        rows_all = {p["key"]: p for p in _platform_rows()}
        on = {k: p for k, p in rows_all.items() if p.get("on") and k != "douyin"} or rows_all  # 除抖音外一个都没标开通时，全部列出
        # 列按发布顺序排（9/29：全平台追踪，和发布台同一个顺序）
        keys = tuple(k for k in publish_desk.SEQUENCE if k in backfill.PLATFORMS and k in on)
        rows = backfill.queue(videos, links=links, records=records, marks=store.backfill_marks(), median=median, platforms=keys, forms=platform_forms())
        keep = set(store.settings().get("tracker_keep") or [])
        cancelled = set(store.settings().get("tracker_cancel") or [])
        for r in rows:
            r["hidden_on_douyin"] = r["video_id"] in keep
            # 他说了不补发的：还列着（能点回来），但哪个平台都不算缺，不进补发、不算旧内容
            r["cancelled"] = r["video_id"] in cancelled
            if r["cancelled"]:
                r["missing"] = []
            # 10/3 作者：标了「不发」的格子（这一条这个平台以后也不发）不算缺
            for k in _skipped(r["video_id"], r["topic_id"]) & set(r["missing"]):
                r["missing"].remove(k)
                r["done"][k] = "skip"
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        try:
            egg_of = eggs_mod.by_video(vault.vault_root(vault_path()))  # 每条视频结尾送的鸡蛋（Obsidian 里的话术，10/14）
        except vault.VaultError:
            egg_of = {}
        for r in rows:
            r["egg"] = egg_of.get(r["video_id"])
            t = topics.get(r["topic_id"]) if r["topic_id"] else None
            has_master = bool(t and final_video_path(t))
            with backfill_lock:
                dl = dict(backfill_dl.get(r["video_id"]) or {})
            r["video"] = "master" if has_master and t.get("video_project") else "download" if (has_master or _backfill_file(r["video_id"])) else None
            r["download"] = dl or None
        from . import reach

        cols = {"douyin": {"key": "douyin", "label": "抖音", "kind": "视频", "missing": 0}}
        cols.update({k: {"key": k, "label": on[k].get("label", k), "kind": backfill.KIND[k], "missing": sum(1 for r in rows if k in r["missing"])} for k in keys})
        return {
            # 列照发布顺序（10/4）：X 先发，抖音 · 小红书 · 视频号同时传，降权的三个（core=False）在最右边、淡一点。
            # 抖音那一列是这条视频本身的链接。
            "platforms": [{**cols[k], "core": k in reach.CORE} for k in publish_desk.SEQUENCE if k in cols],
            "videos": rows,
            "fresh": _fresh_rows({r["topic_id"] for r in rows if r.get("topic_id")}),
            "order": "按发布时间从新到旧",
        }

    def _fresh_rows(listed: set[int]) -> list[dict[str, Any]]:
        """10/20 走查：新发的内容在别的平台发了、抖音那条还没同步到（或者抖音读不到作品），这张表里就没有它。
        这里把「已经发出去至少一个平台、还没对上抖音作品」的内容列在最上面，格子只说发没发，数等读到了再有。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        out = []
        for t in store.topics():
            if t["id"] in listed:
                continue
            recs = store.publish_records(t["id"])
            if not recs:
                continue
            # 看最近 30 天里有没有发过（老的一笔怪日期不该把整条挡掉）；日期写最近这一轮里最早的那次
            recent = [r.get("published_at") or "" for r in recs.values() if (r.get("published_at") or "") >= cutoff]
            if not recent:
                continue
            out.append({"topic_id": t["id"], "title": t["title"], "published_at": min(recent),
                        "done": {k: (r.get("url") or True) for k, r in recs.items()}})
        return sorted(out, key=lambda r: r["published_at"] or "", reverse=True)

    @app.get("/api/outbox/matrix")
    def outbox_matrix(limit: int = 8, offset: int = 0) -> dict[str, Any]:
        """已发出 · 概览：最近几条内容在每个平台的累计触达（9/29 改版）。
        抖音用同步到的播放；B 站、YouTube、X、小红书用每天读到的累计数，靠全平台追踪里存的链接对上帖子；
        视频号、公众号没有接口，只能说发没发。"""
        from . import links

        from . import approvals, backfill

        if not 1 <= limit <= 500 or offset < 0:
            raise HTTPException(status_code=422, detail="limit 需要在 1–500 之间，offset 不能小于 0")
        sheet = get_backfill()
        views = store.latest_post_views()
        accounts = store.settings()["platform_accounts"] or {}
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        marks = store.backfill_marks()
        warnings = _publication_warnings()
        xhs_titles: list[tuple[str, int]] | None = None
        vids = {v["video_id"]: v for v in (store.videos(store.self_account()["id"]) if store.self_account() else [])}
        rows = []
        for r in sheet["videos"][offset:offset + limit]:
            cells = {}
            topic = topics.get(r.get("topic_id"))
            forms = reach.forms_list(topic, accounts)
            if topic:
                approval_state = _approval_state(topic)
                ap = approvals.status(approval_state["folder"], approval_state["fps"])
                video = final_video_path(topic)
            for p in sheet["platforms"]:
                key = p["key"]
                if key == "douyin":
                    n = (vids.get(r["video_id"]) or {}).get("views")
                    cells[key] = {"state": "views", "views": n} if n is not None else {"state": "sent"}
                    cells[key]["publication_state"] = "published"
                    cells[key].update(metrics_complete=n is not None, missing_post_ids=[] if n is not None else [r["video_id"]],
                                      missing_forms=[] if n is not None else ["video"])
                    cells[key]["forms"] = [{"form": "video", "presentation": pp_mod.presentation_state({"sent": {
                        "url": f"https://www.douyin.com/video/{r['video_id']}", "at": r["published_at"], "how": "douyin"}}),
                        "metrics": {"views": n, "post_id": r["video_id"], "complete": n is not None, "source": "douyin" if n is not None else None}}]
                    continue
                if topic:
                    form_rows = _pp_form_rows(topic, key, forms[key], ap=ap, video=video)
                else:
                    form_rows = []
                    for form in forms[key]:
                        sent = pp_mod.sent_row(key, form, records={}, posts={}, marks=marks,
                                              topic={"published_video_id": r["video_id"]})
                        row = {"form": form, "sent": sent, "ready": False, "why": "尚未准备发布素材"}
                        form_rows.append({**row, "presentation": pp_mod.presentation_state(row)})
                published = [fr for fr in form_rows if fr["presentation"]["state"] == "published"]
                skipped = r["done"].get(key) == "skip" or not forms[key]
                cell = {**pp_mod.publication_metrics(key, form_rows, views), "old_url": (r.get("old_links") or {}).get(key),
                        "publication_warnings": [w for w in warnings if w["platform"] == key and r.get("topic_id") in w["topic_ids"]]}
                if not published:
                    states = [fr["presentation"]["state"] for fr in form_rows]
                    state = next((st for st in ("running", "awaiting_confirm", "unknown", "draft", "failed", "wait", "not_ready", "ready") if st in states), "not_ready")
                    cells[key] = {**cell, "state": "skip" if skipped else "none", "publication_state": "skip" if skipped else state}
                    continue
                # Multiple forms may mirror one public post; count its snapshot only once.
                pids = {links.post_id(key, fr["sent"].get("url")) for fr in published}
                counts = [views[(key, pid)] for pid in pids if pid and (key, pid) in views]
                n = sum(counts) if counts else None
                if n is None and key == "xiaohongshu":
                    # 小红书的数是截图读的，存的是「时间|标题前几个字」，没有帖子编号：按标题最像的那条对
                    titles = xhs_titles if xhs_titles is not None else store.latest_post_titles("xiaohongshu")
                    xhs_titles = titles
                    scored = [(backfill.similarity(t.rstrip("…. "), r["headline"] or r["title"]), v) for t, v in titles]
                    best = max(scored, default=(0, None))
                    n = best[1] if best[0] >= 0.6 else None
                    cell.update(pp_mod.publication_metrics(key, form_rows, views, title_match=n))
                cell["publication_state"] = "published" if len(published) == len(form_rows) else "partial"
                cells[key] = {**cell, "state": "views", "views": n} if n is not None else {**cell, "state": "sent", "no_api": key in ("channels", "wechat_mp")}
            total = sum(c["views"] for c in cells.values() if c.get("state") == "views" and c.get("views"))
            missing_platforms = [key for key, cell in cells.items() if not cell["metrics_complete"]]
            rows.append({"video_id": r["video_id"], "topic_id": r.get("topic_id"), "title": r["headline"] or r["title"][:30], "published_at": r["published_at"],
                         "multiple": r["multiple"], "cells": cells, "total": total,
                         "metrics_complete": not missing_platforms, "missing_platforms": missing_platforms})
        return {"platforms": sheet["platforms"], "rows": rows, "publication_warnings": warnings,
                "metrics_complete": all(row["metrics_complete"] for row in rows),
                "coverage": {"total": len(sheet["videos"]), "returned": len(rows), "limit": limit, "offset": offset,
                             "has_more": offset + len(rows) < len(sheet["videos"]),
                             "complete": offset == 0 and len(rows) == len(sheet["videos"])}}

    @app.post("/api/backfill/{video_id}/mark")
    def mark_backfill(video_id: str, body: BackfillMarkBody) -> dict[str, Any]:
        """作者 在工作台之外已经发过这个平台：记一笔，不建选题。"""
        from . import backfill

        if body.platform not in backfill.PLATFORMS:
            raise ValueError("没有这个平台")
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        store.set_backfill_mark(video_id, body.platform, body.done)
        return {"ok": True}

    @app.post("/api/backfill/{video_id}/skip")
    def skip_backfill(video_id: str, body: BackfillSkipBody) -> dict[str, Any]:
        """这一条这个平台不发（10/3 作者：从发布页搬到补发工作台）。不算缺，补发不再挑它；点回来就恢复。"""
        from . import backfill

        if body.platform not in backfill.PLATFORMS:
            raise ValueError("没有这个平台")
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        if body.skip and (video_id, body.platform) in {(r["video_id"], r["platform"]) for r in store.backfill_plan(date.today().isoformat())}:
            raise ValueError("今天排了这一格，先在「今天在发的」里点「不发这格」")
        skips = {k: list(v) for k, v in (store.settings().get("tracker_skip") or {}).items()}
        current = [p for p in skips.get(video_id, []) if p != body.platform]
        if body.skip:
            current.append(body.platform)
        if current:
            skips[video_id] = current
        else:
            skips.pop(video_id, None)
        store.update_settings({"tracker_skip": skips})
        return {"ok": True, "skip": body.skip}

    @app.post("/api/backfill/{video_id}/cancel")
    def cancel_backfill(video_id: str, body: BackfillCancelBody) -> dict[str, Any]:
        """这条旧视频不补发了（没有时效性了）。只是不再往别的平台补，抖音上那条不动；点回来就恢复。"""
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        current = [v for v in (store.settings().get("tracker_cancel") or []) if v != video_id]
        store.update_settings({"tracker_cancel": current + [video_id] if body.cancel else current})
        return {"ok": True, "cancelled": body.cancel}

    @app.post("/api/backfill/{video_id}/take")
    def take_backfill(video_id: str) -> dict[str, Any]:
        """拿这条旧视频去补发：接上（或新建）选题、种一份文案、接上成片，然后交给发布台。
        不发布任何东西——每个平台照旧在发布台上点确认。"""
        from . import backfill, copypack

        video = store.video(video_id)
        if video is None:
            raise ValueError("找不到这条抖音视频")
        _, links, _ = _backfill_state()
        tid = links.get(video_id)
        split = backfill.split_douyin_title(video.get("title") or "")
        me = store.self_account()
        if tid is None:
            topic = store.create_topic(split["title"] or "抖音旧视频", account_id=me["id"] if me else None, memo="补发：抖音发过的旧视频")
            tid = topic["id"]
            store.log_event("pool", f"《{topic['title'][:30]}》拿去补发", tid)
        topic = store.topic(tid)
        if not topic.get("published_video_id"):
            topic = store.update_topic(tid, published_video_id=video_id)
        if "douyin" not in store.publish_records(tid):
            store.set_publish_record(tid, "douyin", published=True, url=f"https://www.douyin.com/video/{video_id}")
        if copypack.read_copy(drafts_root, tid) is None:
            copypack.save_copy(drafts_root, tid, {"douyin": {"title": split["title"], "body": split["body"], "tags": split["tags"]}})
        if final_video_path(topic) is None:
            f = _backfill_file(video_id)
            if f is not None:
                topic = store.update_topic(tid, video_file=str(f))
        return {"topic_id": tid, "has_video": final_video_path(store.topic(tid)) is not None}

    def _run_backfill_download(video_id: str) -> None:
        from . import archive

        try:
            root = archive_root()
            if root is None:
                raise RuntimeError("作品库没配置，或者那块硬盘没插")
            search = [Path(p).expanduser() for p in store.settings().get("local_video_roots") or []]
            me = store.self_account()
            own = store.public_videos(me["id"]) if me else [store.video(video_id)]
            r = archive.archive_pending(own, root=root, cookie_path=cookie_path, search=search, delay=0, download=True, only={video_id})
            if r["failed"]:
                raise RuntimeError(r["failed"][0]["error"])
            f = archive.video_file(root, video_id)
            if f is None:
                raise RuntimeError("没找到这条的成片")
            for t in store.topics(include_archived=True):
                if t.get("published_video_id") == video_id and not t.get("video_project"):
                    store.update_topic(t["id"], video_file=str(f))
            with backfill_lock:
                backfill_dl[video_id] = {"state": "done"}
        except Exception as exc:  # noqa: BLE001 - shown on the queue
            logger.warning("backfill download %s failed: %s", video_id, exc)
            with backfill_lock:
                backfill_dl[video_id] = {"state": "failed", "error": str(exc)[:200] or type(exc).__name__}

    @app.post("/api/backfill/{video_id}/download")
    def download_backfill(video_id: str) -> dict[str, Any]:
        """作者 点了才下，一次只下一条：抖音风控的时候不能一口气抓一串。"""
        if store.video(video_id) is None:
            raise ValueError("找不到这条抖音视频")
        with backfill_lock:
            if any(v.get("state") == "downloading" for v in backfill_dl.values()):
                raise ValueError("正在下另一条，等它下完")
            backfill_dl[video_id] = {"state": "downloading"}
        threading.Thread(target=_run_backfill_download, args=(video_id,), name=f"backfill-{video_id}", daemon=True).start()
        return {"started": True}


    # -- 进项「作者 原始输出」里直接新建一篇（rawnote.py，10/5 作者）-------------------------


    # -- 积木：主线 blocks/ 每块都在；加购 extras/ 在就挂上 --------------------------
    from . import blocks, extras

    here = locals()
    # 试用版剪掉了一部分 helper，清单里缺的就不给（完整版里 test_block_api_names_all_exist 保证一样不缺）
    shared = {name: here[name] for name in BLOCK_API if name in here}
    app.state.blocks = blocks.register_all(app, shared)  # 主线：左栏每站的积木（blocks/）
    app.state.extras = extras.register_all(app, shared)  # 加购：试用版里没有（extras/）

    # -- frontend -----------------------------------------------------------

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def _edition_gate(request: Any, call_next: Any) -> Any:
        # 试用版关掉的功能，接口也关：不只是藏按钮（#526）
        cut = edition.blocked(request.url.path, profile)
        if cut:
            return JSONResponse(status_code=404, content={"error": f"试用版没有「{edition.FEATURES[cut].label}」"})
        return await call_next(request)

    @app.middleware("http")
    async def _block_cross_site_writes(request: Any, call_next: Any) -> Any:
        # The app is reachable through a password proxy, so a browser holding those credentials must not
        # let another site trigger writes (start an agent run, confirm a publish). A custom header forces a
        # CORS preflight that this app never grants; the Origin, when sent, must be this host.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-content-studio") != "1":
                return JSONResponse(status_code=403, content={"error": "请求缺少工作台标识，已拒绝"})
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlparse

                if urlparse(origin).netloc != request.headers.get("host", ""):
                    return JSONResponse(status_code=403, content={"error": "跨站请求，已拒绝"})
        return await call_next(request)

    @app.middleware("http")
    async def _revalidate_static(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Local app that changes often: always revalidate so a restart never serves stale JS.
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.store = store
    app.state.freeze_day = _freeze_day  # 日结：测试和手动补救用（平时由 23:55 的收尾线程调）
    try:
        store.normalize_publish_links()
    except Exception:  # noqa: BLE001 - 换不了就下次再换，不挡启动
        logger.warning("normalize publish links failed", exc_info=True)
    app.state.worker = worker
    app.state.ops = ops
    return app
