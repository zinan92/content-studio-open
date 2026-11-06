from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .paths import config_dir
import sqlite3
import statistics
import threading
from typing import Any, Iterator


DEFAULT_STORE_PATH = config_dir() / "data/studio.sqlite3"

JOB_STAGES = ("queued", "downloading", "transcribing", "analyzing", "done", "failed")
ACTIVE_STAGES = ("downloading", "transcribing", "analyzing")
TOPIC_STATUSES = ("todo", "drafting", "ready", "published")
TOPIC_FORMATS = ("article", "video", "both")

DEFAULT_SETTINGS: dict[str, Any] = {
    "threshold": 5.0,
    "auto_enqueue_limit": 2,
    "auto_enqueue_threshold": 2.0,  # 9/29 作者：点赞到自己中位数 2 倍才自动拆
    "sync_pages": 3,
    "sync_delay_seconds": 1.5,
    "obsidian_vault": "",
    "yanxishi_admin_url": "",
    "video_projects_root": "",
    # 作品库：自己发过的每条抖音视频一个文件夹（通常在外接硬盘上）。
    "douyin_archive": "",
    # 在本机找原片时扫哪些目录（按时长和日期配对，找到就不用从抖音下）。
    "local_video_roots": [],
    # {platform: {"on": bool, "handle": str}} — which platforms 作者 has opened accounts on.
    "platform_accounts": {},
    # {platform: [话题]} — 各平台的流量话题（活动、扶持计划），每条视频自动带上、排在内容话题前面。
    # 9/29 作者：抖音那四个是他每条都带的；别的平台他还不知道，在打包页里填一次就记住。
    "traffic_tags": {},
    # X 每天发多少（10/9 作者：「明明可以变成 200，也可以变成 500」——不写死）。
    # long = 长的总数，post_share = 其中长帖（他的短句合并成一条纯文字）的比例，其余是长文（带配图的文章）；
    # 两种测一周看哪种流量好。own_short = 他自己原话的短帖（默认每天 10 条）。hot = 热点短帖草稿上限。
    # 10/9 晚 作者：只留长帖和长文，每天 5 + 5；热点也写成长帖，hot = 每天最多写几篇热点长帖给他挑（勾的算在 5 篇长帖里）。
    "x_auto_send": {"short": True, "quote": True, "reply": True},
    # 10/19 作者：「X 后台每天排短帖、长文的那套也关掉」。关着时不排、不写、不发短帖 / 长帖长文 / 引用 / 回复，也不花 AI 额度；
    # X 的实时数据照常读（复盘、X 页的数据要用）。要重新开：PUT /api/settings {"x_daily": true}。
    "x_daily": False,
    # 10/12 作者：每天至少 100 条帖子（原创 + 引用）——短帖 70、引用 30；长文长帖不再自动排（long 0），
    # 改成每天 10 篇候选他点「发文 / 长帖 / 拆解 / 不发」
    # 10/12 晚：流量线短帖（反常识暴论）20、repost 10；发帖目标 100 照旧（x_kpi.posts）
    "x_counts": {"long": 0, "post_share": 0.67, "own_short": 100, "hot": 100, "articles": 4},  # 10/12 晚：短帖、repost 各 100，长文 3~5（默认 4）
    # 10/12 作者：写作流程是 park-writing 模块里定的（module.yaml），这里只存他选哪个默认、另存了哪些（最多 2 个）：
    # default = 做长文时走哪个流程，custom = {名字: [步骤 id]}（顺序固定，只存开了哪些）。
    # max_change_pct：改动预算（对原文，默认 20%，设置里 / 批注视图顶上能改；最多 50）
    "write_flow": {"default": "流程1", "custom": {}, "max_change_pct": 20},
    # 10/19 作者：「这次怎么剪」上一次怎么勾的（Hook / 动效 / 字幕 / 版式 / 背景音乐），下一条默认照它。空 = 用 cutplan.DEFAULT。
    "cut_plan_default": {},
    # 今日复盘里的 X 涨粉直线目标。
    "x_follow_target": {"start_day": "2026-01-01", "start": 0, "end_day": "2026-12-31", "end": 1000},
    # 抖音涨粉目标（默认是示例，在设置里改）。和 X 一个样子：从哪天、多少起，到哪天、多少
    "douyin_follow_target": {"start_day": "2026-01-01", "start": 0, "end_day": "2026-12-31", "end": 1000},
    # X 每天看两个动作：发帖条数和曝光；回复上限只管工作台自己发多少
    "x_kpi": {"posts": 100, "impressions": 200000, "quotes": 20, "replies_min": 100, "replies_max": 200, "articles": 2, "long_total": 3},
    "reply_gap_minutes": 4,
    "park_writing_skill": "~/.claude/skills/park-writing/SKILL.md",
    # 各平台被删、被限流的记录（10/6 作者：哪条、哪种形式、平台说了什么，以后看哪些话在这个平台不能说）：{platform: [{id, at, text, title, topic_id, form}]}
    "platform_notes": {},
    # 抖音上设成私密（比如被判违规藏起来）但别的平台还要发的视频：全平台追踪照样列出来（9/29 作者）。
    "tracker_keep": [],
    # 不补发的旧视频（9/30 作者：半年前的实操、没有时效性的，不再往别的平台补）：全平台追踪里划掉，不算旧内容。
    "tracker_cancel": [],
    # 某条某个平台不发（10/3 作者：补发工作台里标「不发」）：{抖音作品 id: [平台]}。不算缺，补发不挑它。
    "tracker_skip": {},
    # 各平台主页的名字、简介、链接（profiles.py）：{platform: {name, bio, link, applied: {name, bio, link, at}}}
    "profiles": {},
    # 写文章用哪个写作 skill（设置里选）。空 = 不用 skill，只整理原话（10/4 作者自己选的）。
    "writer_skill": "",
    # 用户在「设置 · 流程」里关掉的组件（edition.SWITCHES 里的 key）。10/9 作者：流程固定，只能开关组件。
    "components_off": [],
    # 9/29 作者：KPI 由 Claude 定，作者 照做。出摊和回私信算他的分；触达和收到私信是结果。
    # reach_daily 是 7 天平均的目标，reach_by 之前要到；dm_daily 在 dm_baseline_until 摸底完再定（0 = 还没定）。
    "kpi": {"started": "2026-09-29", "reach_daily": 10000, "reach_by": "2026-10-31", "reach_next": 20000,
            "dm_daily": 0, "dm_baseline_until": "2026-10-06",
            # X 互动：每天在别人的帖子下面回这么多条（9/29 作者 先定 20；9/30 降到 10）
            "x_replies_daily": 10,
            # 读日报从这天起算分（9/30 作者）
            "read_started": "2026-09-30",
            # 追平阶段（9/30 作者）：出关要连续出摊这么多天；不发新视频的日子补发这么多格
            "ship_streak_target": 14, "backfill_cells": 4,
            # 每周至少这么多条新视频，少一条减 1 分；从这一周（周一）起算，之前不倒扣
            "new_weekly": 3, "new_weekly_started": "2026-10-05",
            # 10/9 作者（变现流程板）：每天一个变现动作，没做减 1 分，从这天起算；本月收入目标（结果，不算分）
            "money_started": "2026-10-10", "money_ended": "2026-10-11",
            # 本月收入目标（默认是示例，在设置里改）
            "revenue_monthly": 10000},
}

# 9/20 作者 把对标和老师合成一类；9/30 又分开：老师是学理念的，对标是看要不要复刻的。
# 处理方式一样（新发的他都自己看），但进项里分两栏；一个人只有一个身份，两样都是的算对标。
KIND_SELF = "self"
KIND_BENCHMARK = "benchmark"
KIND_TEACHER = "teacher"
ACCOUNT_KINDS = (KIND_SELF, KIND_BENCHMARK, KIND_TEACHER)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    external_id TEXT,
    nickname TEXT,
    follower_count INTEGER,
    total_favorited INTEGER,
    signature TEXT,
    is_self INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'benchmark',
    status TEXT NOT NULL,
    last_error TEXT,
    added_at TEXT NOT NULL,
    last_synced_at TEXT,
    UNIQUE(platform, external_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_profile_url ON accounts(profile_url);
CREATE TABLE IF NOT EXISTS videos (
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    published_at TEXT,
    duration_seconds REAL,
    is_top INTEGER NOT NULL DEFAULT 0,
    is_image_post INTEGER NOT NULL DEFAULT 0,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    collects INTEGER,
    views INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (platform, video_id)
);
CREATE INDEX IF NOT EXISTS videos_account ON videos(account_id, published_at);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    video_id TEXT,
    source TEXT NOT NULL,
    stage TEXT NOT NULL,
    error TEXT,
    report_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_stage ON jobs(stage, id);
CREATE TABLE IF NOT EXISTS report_archive (
    video_id TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_checks (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS backfill_marks (
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    marked_at TEXT NOT NULL,
    PRIMARY KEY (video_id, platform)
);
CREATE TABLE IF NOT EXISTS daily_picks (
    item_key TEXT PRIMARY KEY,
    topic_id INTEGER NOT NULL,
    issue TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_triage (
    path TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    note_paths TEXT NOT NULL DEFAULT '[]',
    formats TEXT NOT NULL DEFAULT 'both',
    status TEXT NOT NULL DEFAULT 'todo',
    memo TEXT,
    article_path TEXT,
    published_url TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS briefings (
    day TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    error TEXT,
    data TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_snapshots (
    video_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    collects INTEGER,
    views INTEGER,
    PRIMARY KEY (video_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS publish_records (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    url TEXT,
    published_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, platform)
);
CREATE TABLE IF NOT EXISTS publish_posts (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    form TEXT NOT NULL,
    url TEXT,
    published_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, platform, form)
);
CREATE TABLE IF NOT EXISTS publish_skips (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    skipped_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, platform)
);
CREATE TABLE IF NOT EXISTS reviews (
    week TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    error TEXT,
    data TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_snapshots (
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    views INTEGER NOT NULL,
    PRIMARY KEY (platform, post_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS x_post_metrics (
    post_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('post', 'reply', 'quote')),
    impressions INTEGER, bookmarks INTEGER, likes INTEGER, replies INTEGER,
    reposts INTEGER, quotes INTEGER, profile_clicks INTEGER,
    text60 TEXT, posted_at TEXT,
    PRIMARY KEY (post_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS reach_entries (
    day TEXT NOT NULL,
    platform TEXT NOT NULL,
    views INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, platform)
);
-- 全网粉丝（10/5 作者）：一天一个平台一个数。source = auto（工作台自己读的）/ manual（他填的）/ backup（从库备份里找回的老数）
CREATE TABLE IF NOT EXISTS follower_counts (
    day TEXT NOT NULL,
    platform TEXT NOT NULL,
    followers INTEGER NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, platform)
);
-- 日结（10/3 作者：每天收尾把概览冻结存档）：一天一行，存过不改。kind = live / late / rebuilt（dayclose.py）
CREATE TABLE IF NOT EXISTS day_close (
    day TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    frozen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shoot_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    position REAL NOT NULL,
    topic_id INTEGER,
    created_at TEXT NOT NULL,
    done_at TEXT,
    planned_day TEXT
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS backfill_plan (
    day TEXT NOT NULL,
    slot INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    PRIMARY KEY (day, slot)
);
CREATE TABLE IF NOT EXISTS wendy_thread (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    who TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dm_entries (
    day TEXT PRIMARY KEY,
    received INTEGER NOT NULL,
    replied INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_marks (
    video_id TEXT PRIMARY KEY,
    seen_at TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS swipe_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    content_dir TEXT,
    info TEXT,
    note TEXT,
    collection TEXT,
    topic_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kpi_counts (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    value INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, key)
);
CREATE TABLE IF NOT EXISTS driver_log (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL,
    PRIMARY KEY (day, key, kind)
);
CREATE TABLE IF NOT EXISTS x_followers_hourly (
    at TEXT PRIMARY KEY,
    followers INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    topic_id INTEGER
);
CREATE INDEX IF NOT EXISTS events_at ON events(at DESC);
CREATE TABLE IF NOT EXISTS anna_chats (
    scope TEXT PRIMARY KEY,
    session_id TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    project TEXT NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL,
    log_path TEXT,
    exit_path TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS publish_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    mode TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL,
    result TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StoreError(RuntimeError):
    """A store operation violated a product rule (duplicate, missing row...)."""


class StudioStore:
    """SQLite-backed state for accounts, videos, teardown jobs and settings."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _migrate(self) -> None:
        """Add columns introduced after a table was first created (SQLite has no IF NOT EXISTS for columns)."""
        wanted = {"shoot_list": {"planned_day": "TEXT"}, "feed_marks": {"opened_at": "TEXT"}, "publish_records": {"form": "TEXT"}, "accounts": {"kind": "TEXT NOT NULL DEFAULT 'benchmark'"}, "topics": {"write_state": "TEXT", "write_error": "TEXT", "outline_path": "TEXT", "outline_state": "TEXT", "outline_error": "TEXT", "video_project": "TEXT", "published_video_id": "TEXT", "copy_state": "TEXT", "copy_error": "TEXT", "is_focus": "INTEGER NOT NULL DEFAULT 0", "snoozed_until": "TEXT", "manual_stage": "TEXT", "closed_at": "TEXT", "video_file": "TEXT", "platform_forms": "TEXT"}}
        for table, columns in wanted.items():
            existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                    if (table, name) == ("accounts", "kind"):
                        # Rows written before kinds existed: 作者's own account, everything else 对标.
                        self._conn.execute("UPDATE accounts SET kind = CASE is_self WHEN 1 THEN 'self' ELSE 'benchmark' END")

    # -- events: what happened in the workbench, so Anna is not told only about one page ----

    def log_event(self, kind: str, text: str, topic_id: int | None = None) -> None:
        """One line of history. Anna reads these so she knows a topic just moved, a sync
        finished, a teardown landed — none of which is visible in the page 作者 happens to
        be looking at. Never let logging break the action it describes."""
        try:
            with self.tx() as conn:
                conn.execute(
                    "INSERT INTO events(at, kind, text, topic_id) VALUES(?, ?, ?, ?)",
                    (now_iso(), kind, text[:300], topic_id),
                )
        except sqlite3.Error:
            pass

    def events(self, limit: int = 25) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM events ORDER BY at DESC, id DESC LIMIT ?", (limit,))

    def prune_events(self, keep: int = 500) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)", (keep,))

    # -- Anna (resident editor) chats, one thread per page ---------------------

    def anna_chat(self, scope: str) -> dict[str, Any]:
        row = self._row("SELECT * FROM anna_chats WHERE scope = ?", (scope,))
        if row is None:
            return {"scope": scope, "session_id": None, "messages": [], "updated_at": None}
        return {**row, "messages": json.loads(row["messages"] or "[]")}

    def append_anna(self, scope: str, message: dict[str, Any], *, session_id: str | None = None, keep: int = 60) -> dict[str, Any]:
        chat = self.anna_chat(scope)
        messages = (chat["messages"] + [message])[-keep:]
        sid = session_id if session_id is not None else chat["session_id"]
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO anna_chats(scope, session_id, messages, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET session_id = excluded.session_id, messages = excluded.messages, updated_at = excluded.updated_at",
                (scope, sid, json.dumps(messages, ensure_ascii=False), now_iso()),
            )
        return self.anna_chat(scope)

    def merge_anna_threads(self, into: str = "main") -> int:
        """Fold the old one-thread-per-page chats into one conversation, oldest first.

        Each message keeps the page it was said on (`scope`) so its action buttons still
        point at the right video. The CLI session starts fresh: the old ones each only
        knew one page.
        """
        rows = self._rows("SELECT scope, messages FROM anna_chats WHERE scope != ?", (into,))
        if not rows:
            return 0
        merged = list(self.anna_chat(into)["messages"])
        for row in rows:
            for message in json.loads(row["messages"] or "[]"):
                merged.append({**message, "scope": message.get("scope") or row["scope"]})
        merged.sort(key=lambda m: m.get("at") or "")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO anna_chats(scope, session_id, messages, updated_at) VALUES (?, NULL, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET messages = excluded.messages, updated_at = excluded.updated_at",
                (into, json.dumps(merged[-60:], ensure_ascii=False), now_iso()),
            )
            conn.execute("DELETE FROM anna_chats WHERE scope != ?", (into,))
        return len(rows)

    def clear_anna(self, scope: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM anna_chats WHERE scope = ?", (scope,))

    def rename_note_prefix(self, old_prefix: str, new_prefix: str) -> int:
        """Follow a renamed vault folder: triage rows and topic note_paths keep pointing at the notes."""
        changed = 0
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE inbox_triage SET path = ? || substr(path, ?) WHERE path LIKE ? || '/%'",
                (new_prefix, len(old_prefix) + 1, old_prefix),
            )
            changed += cursor.rowcount
            for row in conn.execute("SELECT id, note_paths FROM topics").fetchall():
                paths = json.loads(row["note_paths"] or "[]")
                moved = [f"{new_prefix}/{p[len(old_prefix) + 1:]}" if p.startswith(f"{old_prefix}/") else p for p in paths]
                if moved != paths:
                    conn.execute("UPDATE topics SET note_paths = ? WHERE id = ?", (json.dumps(moved, ensure_ascii=False), row["id"]))
                    changed += 1
        return changed

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def _row(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # -- report archive ---------------------------------------------------

    def archived_reports(self) -> dict[str, str]:
        return {row["video_id"]: row["archived_at"] for row in self._rows("SELECT video_id, archived_at FROM report_archive")}

    def archive_report(self, video_id: str) -> str:
        archived_at = now_iso()
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO report_archive(video_id, archived_at) VALUES (?, ?) ON CONFLICT(video_id) DO NOTHING",
                (video_id, archived_at),
            )
        return self.archived_reports()[video_id]

    def unarchive_report(self, video_id: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM report_archive WHERE video_id = ?", (video_id,))

    # -- daily checks & inbox triage --------------------------------------

    def daily_checks(self, day: str) -> dict[str, str]:
        return {row["key"]: row["checked_at"] for row in self._rows("SELECT key, checked_at FROM daily_checks WHERE day = ?", (day,))}

    def checked_days(self, key: str) -> set[str]:
        return {row["day"] for row in self._rows("SELECT day FROM daily_checks WHERE key = ?", (key,))}

    def set_daily_check(self, day: str, key: str, checked: bool) -> dict[str, str]:
        with self.tx() as conn:
            if checked:
                conn.execute(
                    "INSERT INTO daily_checks(day, key, checked_at) VALUES (?, ?, ?) ON CONFLICT(day, key) DO NOTHING",
                    (day, key, now_iso()),
                )
            else:
                conn.execute("DELETE FROM daily_checks WHERE day = ? AND key = ?", (day, key))
        return self.daily_checks(day)

    def triage(self) -> dict[str, dict[str, str]]:
        return {row["path"]: dict(row) for row in self._rows("SELECT path, status, updated_at FROM inbox_triage")}

    def backfill_marks(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in self._rows("SELECT video_id, platform FROM backfill_marks"):
            out.setdefault(r["video_id"], set()).add(r["platform"])
        return out

    def set_backfill_mark(self, video_id: str, platform: str, done: bool) -> None:
        with self.tx() as conn:
            if done:
                conn.execute("INSERT OR REPLACE INTO backfill_marks(video_id, platform, marked_at) VALUES (?, ?, ?)", (video_id, platform, now_iso()))
            else:
                conn.execute("DELETE FROM backfill_marks WHERE video_id = ? AND platform = ?", (video_id, platform))

    def daily_picks(self) -> dict[str, int]:
        return {r["item_key"]: r["topic_id"] for r in self._rows("SELECT item_key, topic_id FROM daily_picks")}

    def add_daily_pick(self, item_key: str, topic_id: int, issue: str) -> None:
        with self.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO daily_picks(item_key, topic_id, issue, created_at) VALUES (?, ?, ?, ?)",
                         (item_key, topic_id, issue, now_iso()))

    def set_triage(self, path: str, status: str | None) -> None:
        # back = 捡回来：从「暂不拍 / 拍过了」回到还没处理。标过「不做了」的选题占着这篇笔记时，
        # 光清掉状态它还会落回暂不拍，所以要一个明确的「捡回来」。
        if status not in (None, "topic", "ignored", "shot", "back"):
            raise StoreError("处理状态只能是 拿来做、拍过了、暂不拍 或 捡回来")
        with self.tx() as conn:
            if status is None:
                conn.execute("DELETE FROM inbox_triage WHERE path = ?", (path,))
            else:
                conn.execute(
                    "INSERT INTO inbox_triage(path, status, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
                    (path, status, now_iso()),
                )

    # -- topics -----------------------------------------------------------

    def _topic_row(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "note_paths": json.loads(row["note_paths"] or "[]"), "platform_forms": json.loads(row.get("platform_forms") or "{}")}

    def topic(self, topic_id: int) -> dict[str, Any]:
        row = self._topic_row(self._row("SELECT * FROM topics WHERE id = ?", (topic_id,)))
        if row is None:
            raise StoreError("选题不存在")
        return row

    def topics(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        return [self._topic_row(r) for r in self._rows(f"SELECT * FROM topics {where} ORDER BY updated_at DESC, id DESC")]

    def recover_interrupted_writes(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE topics SET write_state = 'failed', write_error = '上次写作被中断（服务重启），点重试' WHERE write_state = 'running'"
            )
            count = cursor.rowcount
            cursor = conn.execute(
                "UPDATE topics SET outline_state = 'failed', outline_error = '上次生成被中断（服务重启），点重试' WHERE outline_state = 'running'"
            )
            count += cursor.rowcount
            cursor = conn.execute(
                "UPDATE topics SET copy_state = 'failed', copy_error = '上次生成被中断（服务重启），点重试' WHERE copy_state = 'running'"
            )
        return count + cursor.rowcount

    def review(self, week: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM reviews WHERE week = ?", (week,))
        return {**row, "data": json.loads(row["data"]) if row["data"] else None} if row else None

    def set_review(self, week: str, *, state: str, error: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.review(week)
        payload = json.dumps(data, ensure_ascii=False) if data is not None else (json.dumps(current["data"], ensure_ascii=False) if current and current["data"] else None)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO reviews(week, state, error, data, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(week) DO UPDATE SET state = excluded.state, error = excluded.error, data = excluded.data, updated_at = excluded.updated_at",
                (week, state, error, payload, now_iso()),
            )
        return self.review(week)

    def normalize_publish_links(self) -> int:
        """已经存下的后台链接一次换成公开链接（9/29 以前 YouTube 存的是 Studio 编辑页、抖音存的是创作者中心）。"""
        from .links import public_url

        changed = 0
        with self.tx() as conn:
            for r in conn.execute("SELECT topic_id, platform, url FROM publish_records WHERE url IS NOT NULL").fetchall():
                fixed = public_url(r["platform"], r["url"])
                if fixed != r["url"]:
                    conn.execute("UPDATE publish_records SET url = ? WHERE topic_id = ? AND platform = ?", (fixed, r["topic_id"], r["platform"]))
                    changed += 1
        return changed

    def latest_post_titles(self, platform: str) -> list[tuple[str, int]]:
        """某个平台每条帖子最近一次的（标题，累计数）。小红书是截图读的，没有帖子编号，只能按标题对。"""
        rows = self._rows(
            "SELECT title, views FROM post_snapshots s WHERE platform = ? AND fetched_at = "
            "(SELECT MAX(fetched_at) FROM post_snapshots t WHERE t.platform = s.platform AND t.post_id = s.post_id)", (platform,))
        return [(r["title"] or "", r["views"]) for r in rows if r["views"] is not None]

    def latest_post_views(self) -> dict[tuple[str, str], int]:
        """每个平台每条帖子最近一次读到的累计播放 / 曝光 / 阅读。"""
        rows = self._rows(
            "SELECT platform, post_id, views FROM post_snapshots s WHERE fetched_at = "
            "(SELECT MAX(fetched_at) FROM post_snapshots t WHERE t.platform = s.platform AND t.post_id = s.post_id)"
        )
        return {(r["platform"], r["post_id"]): r["views"] for r in rows if r["views"] is not None}

    def sent_rows(self) -> list[dict[str, Any]]:
        """每一格是哪天发出去的（月历用）：发布台记的（选题 × 平台），和当天补发的格子里他点了「发了」的。
        全平台追踪里补记的「以前在外面发过」不算——那不是这一天发的。抖音不算，那是新视频。"""
        return self._rows(
            """SELECT r.platform AS platform, r.published_at AS at, t.title AS title, 'record' AS kind
                 FROM publish_records r JOIN topics t ON t.id = r.topic_id WHERE r.platform != 'douyin'
               UNION ALL
               SELECT m.platform, m.marked_at, v.title, 'mark' FROM backfill_marks m JOIN videos v ON v.video_id = m.video_id
                WHERE EXISTS (SELECT 1 FROM backfill_plan p WHERE p.video_id = m.video_id AND p.platform = m.platform)"""
        )

    def publish_records(self, topic_id: int) -> dict[str, dict[str, Any]]:
        return {r["platform"]: r for r in self._rows("SELECT * FROM publish_records WHERE topic_id = ?", (topic_id,))}

    def set_publish_record(self, topic_id: int, platform: str, *, published: bool, url: str | None = None, form: str | None = None, at: str | None = None) -> dict[str, dict[str, Any]]:
        from .links import public_url
        from .reach import form_of, forms_for

        url = public_url(platform, url)  # 后台页换成别人点得开的公开链接（links.py）
        # 记下发的是什么形式（视频 / 图文 / 文字）：平台改了发什么以后，旧形式的那条不算这一格发过了
        accounts = self.settings().get("platform_accounts")
        form = form or forms_for(self.topic(topic_id), accounts).get(platform) or form_of(platform, accounts)
        with self.tx() as conn:
            if published:
                conn.execute(
                    "INSERT INTO publish_records(topic_id, platform, url, published_at, form) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(topic_id, platform) DO UPDATE SET url = excluded.url, form = excluded.form",
                    (topic_id, platform, url, at or now_iso(), form),
                )
                if at:
                    conn.execute("UPDATE publish_records SET published_at = ? WHERE topic_id = ? AND platform = ?", (at, topic_id, platform))
            else:
                conn.execute("DELETE FROM publish_records WHERE topic_id = ? AND platform = ?", (topic_id, platform))
        return self.publish_records(topic_id)

    def publish_skips(self, topic_id: int) -> set[str]:
        """这一条决定不发的平台（发布台的顺序里跳过它）。"""
        return {r["platform"] for r in self._rows("SELECT platform FROM publish_skips WHERE topic_id = ?", (topic_id,))}

    def set_publish_skip(self, topic_id: int, platform: str, *, skip: bool) -> set[str]:
        with self.tx() as conn:
            if skip:
                conn.execute("INSERT OR IGNORE INTO publish_skips(topic_id, platform, skipped_at) VALUES (?, ?, ?)", (topic_id, platform, now_iso()))
            else:
                conn.execute("DELETE FROM publish_skips WHERE topic_id = ? AND platform = ?", (topic_id, platform))
        return self.publish_skips(topic_id)

    # -- 平台页（10/6）：一条内容在一个平台可以发几种形式，每种各记一笔 ------------------------

    def publish_posts(self, topic_id: int) -> dict[tuple[str, str], dict[str, Any]]:
        """{(平台, 形式): 记录}。平台级的 publish_records 照旧（老页面和补发都读它）；这里是每种形式各一笔。"""
        return {(r["platform"], r["form"]): r for r in self._rows("SELECT * FROM publish_posts WHERE topic_id = ?", (topic_id,))}

    def set_publish_post(self, topic_id: int, platform: str, form: str, *, published: bool, url: str | None = None, at: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
        from .links import public_url

        url = public_url(platform, url)
        with self.tx() as conn:
            if published:
                conn.execute(
                    "INSERT INTO publish_posts(topic_id, platform, form, url, published_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(topic_id, platform, form) DO UPDATE SET url = COALESCE(excluded.url, publish_posts.url)",
                    (topic_id, platform, form, url, at or now_iso()),
                )
                if at:  # 补登：照他说的那天算，不是登记的这天
                    conn.execute("UPDATE publish_posts SET published_at = ? WHERE topic_id = ? AND platform = ? AND form = ?", (at, topic_id, platform, form))
            else:
                conn.execute("DELETE FROM publish_posts WHERE topic_id = ? AND platform = ? AND form = ?", (topic_id, platform, form))
        return self.publish_posts(topic_id)

    def platform_posts(self, platform: str) -> list[dict[str, Any]]:
        """这个平台发过的每一笔（形式级 + 平台级合在一起），带选题标题，新的在前。"""
        rows = self._rows(
            """SELECT p.topic_id AS topic_id, t.title AS title, p.platform AS platform, p.form AS form, p.url AS url, p.published_at AS published_at
                 FROM publish_posts p JOIN topics t ON t.id = p.topic_id WHERE p.platform = ?
               UNION ALL
               SELECT r.topic_id AS topic_id, t.title AS title, r.platform AS platform, COALESCE(r.form, '') AS form, r.url AS url, r.published_at AS published_at
                 FROM publish_records r JOIN topics t ON t.id = r.topic_id
                WHERE r.platform = ? AND NOT EXISTS (SELECT 1 FROM publish_posts q WHERE q.topic_id = r.topic_id AND q.platform = r.platform)
               ORDER BY published_at DESC""",
            (platform, platform),
        )
        return rows

    def create_run(self, topic_id: int, project: str) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO workflow_runs(topic_id, project, state, started_at) VALUES (?, ?, 'starting', ?)", (topic_id, project, now_iso())
            )
        return int(cursor.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"pid", "state", "log_path", "exit_path", "started_at", "finished_at"}
        if set(fields) - allowed:
            raise StoreError("不可更新的运行字段")
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE workflow_runs SET {assignments} WHERE id = ?", (*fields.values(), run_id))
        return self._row("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)) or {}

    def runs(self, *, topic_id: int | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        where, params = [], []
        if topic_id is not None:
            where.append("topic_id = ?")
            params.append(topic_id)
        if active_only:
            where.append("state IN ('starting', 'running')")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._rows(f"SELECT * FROM workflow_runs {clause} ORDER BY id DESC", tuple(params))

    def _publish_job(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "payload": json.loads(row["payload"]), "result": json.loads(row["result"]) if row["result"] else None}

    def create_publish_job(self, topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.tx() as conn:
            conn.execute("UPDATE publish_jobs SET state = 'superseded' WHERE topic_id = ? AND platform = ? AND state = 'awaiting_confirm'", (topic_id, payload["platform"]))
            cursor = conn.execute(
                "INSERT INTO publish_jobs(topic_id, platform, mode, payload, state, created_at) VALUES (?, ?, ?, ?, 'awaiting_confirm', ?)",
                (topic_id, payload["platform"], payload["mode"], json.dumps(payload, ensure_ascii=False), now_iso()),
            )
        return self.publish_job(int(cursor.lastrowid))

    def publish_job(self, job_id: int) -> dict[str, Any]:
        job = self._publish_job(self._row("SELECT * FROM publish_jobs WHERE id = ?", (job_id,)))
        if job is None:
            raise StoreError("发布任务不存在")
        return job

    def last_publish_job(self, platform: str) -> dict[str, Any] | None:
        """这个平台最近一次发布（不管哪一条）。用来判断通道是不是断了：最近一次是登录类失败就提示重新连接。"""
        row = self._row("SELECT * FROM publish_jobs WHERE platform = ? AND state NOT IN ('superseded', 'cancelled') ORDER BY id DESC LIMIT 1", (platform,))
        return self._publish_job(row) if row else None

    def publish_jobs(self, topic_id: int) -> list[dict[str, Any]]:
        return [self._publish_job(r) for r in self._rows("SELECT * FROM publish_jobs WHERE topic_id = ? AND state != 'superseded' ORDER BY id DESC LIMIT 20", (topic_id,))]

    def update_publish_job(self, job_id: int, **fields: Any) -> dict[str, Any]:
        if set(fields) - {"state", "result", "message", "confirmed_at", "finished_at"}:
            raise StoreError("不可更新的发布字段")
        if "result" in fields and fields["result"] is not None:
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as conn:
            conn.execute(f"UPDATE publish_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
        return self.publish_job(job_id)

    def recover_interrupted_publishes(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE publish_jobs SET state = 'unknown', message = '服务重启时发布还在进行，结果不确定：去平台后台确认' WHERE state = 'running'"
            )
        return cursor.rowcount

    def topic_for_note(self, path: str) -> dict[str, Any] | None:
        for topic in self.topics(include_archived=True):
            if path in topic["note_paths"]:
                return topic
        return None

    def create_topic(
        self,
        title: str,
        *,
        note_paths: list[str] | None = None,
        formats: str = "both",
        account_id: int | None = None,
        memo: str | None = None,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise StoreError("选题标题不能为空")
        if formats not in TOPIC_FORMATS:
            raise StoreError("形式只能是 文章、视频 或 两者")
        stamp = now_iso()
        from .reach import FORM_CHOICES, default_forms

        # 一开始就定好每个平台发什么（10/5 作者）：按现在的默认记下来，以后改默认不影响已经在做的这条
        accounts = self.settings().get("platform_accounts")
        forms = {key: default_forms(key, accounts) for key in FORM_CHOICES}
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO topics(account_id, title, note_paths, formats, memo, created_at, updated_at, platform_forms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, title[:200], json.dumps(note_paths or [], ensure_ascii=False), formats, memo, stamp, stamp, json.dumps(forms)),
            )
            topic_id = cursor.lastrowid
        return self.topic(topic_id)

    def freeze_platform_forms(self) -> int:
        """把每一条还没记下的平台形式按现在的默认补记上（10/7）。

        选题创建时只记了四大平台；公众号、B 站、YouTube 跟着设置里的默认走。之后要改默认（X 默认加发文章），
        先把老的这些按改之前的样子定住，免得已经在做、已经发完的内容突然多出一堆「X · 文章 待发」、自动档开始补写文章。
        只补缺的，不改记过的；返回补了几条。"""
        from .reach import FORM_CHOICES, default_forms

        accounts = self.settings().get("platform_accounts")
        changed = 0
        for row in self._rows("SELECT id, platform_forms FROM topics"):
            try:
                have = json.loads(row["platform_forms"] or "{}")
            except ValueError:
                have = {}
            missing = {key: default_forms(key, accounts) for key in FORM_CHOICES if key not in have}
            if missing:
                with self.tx() as conn:
                    conn.execute("UPDATE topics SET platform_forms = ? WHERE id = ?", (json.dumps({**have, **missing}), row["id"]))
                changed += 1
        return changed

    def update_topic(self, topic_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"title", "formats", "status", "memo", "article_path", "published_url", "account_id", "archived_at", "note_paths", "write_state", "write_error", "outline_path", "outline_state", "outline_error", "video_project", "published_video_id", "copy_state", "copy_error", "is_focus", "snoozed_until", "manual_stage", "closed_at", "video_file", "platform_forms"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的选题字段：{sorted(unknown)}")
        current = self.topic(topic_id)
        if "status" in fields:
            if fields["status"] not in TOPIC_STATUSES:
                raise StoreError("状态只能是 待写、草稿、待发、已发")
            if fields["status"] == "published" and current["status"] != "published":
                fields["published_at"] = now_iso()
            if fields["status"] != "published":
                fields["published_at"] = None
        if "formats" in fields and fields["formats"] not in TOPIC_FORMATS:
            raise StoreError("形式只能是 文章、视频 或 两者")
        if "title" in fields and not str(fields["title"] or "").strip():
            raise StoreError("选题标题不能为空")
        if "note_paths" in fields:
            fields["note_paths"] = json.dumps(fields["note_paths"] or [], ensure_ascii=False)
        if "platform_forms" in fields:
            from .reach import FORM_CHOICES

            # 10/6：一个平台可以同时发几种（X 视频 + 文字）。单个字符串也收，存成列表；至少留一种
            forms = {}
            for k, v in (fields["platform_forms"] or {}).items():
                wanted = [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])]
                bad = [x for x in wanted if x not in FORM_CHOICES.get(k, ())]
                if bad or not wanted:
                    raise StoreError(f"这些平台不能这样发：{ {k: v} }")
                forms[k] = list(dict.fromkeys(wanted))
            fields["platform_forms"] = json.dumps({**current["platform_forms"], **forms})
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.tx() as conn:
            conn.execute(f"UPDATE topics SET {assignments} WHERE id = ?", (*fields.values(), topic_id))
        return self.topic(topic_id)

    def set_focus(self, topic_id: int | None) -> None:
        """At most one topic is in focus: the single video 作者 is writing or recording right now."""
        with self.tx() as conn:
            conn.execute("UPDATE topics SET is_focus = 0 WHERE is_focus = 1")
            if topic_id is not None:
                conn.execute("UPDATE topics SET is_focus = 1, snoozed_until = NULL, updated_at = ? WHERE id = ?", (now_iso(), topic_id))

    def focus_topic(self) -> dict[str, Any] | None:
        return self._row("SELECT * FROM topics WHERE is_focus = 1 AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 1")

    # -- settings ---------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        values = dict(DEFAULT_SETTINGS)
        for row in self._rows("SELECT key, value FROM settings"):
            if row["key"] in values:
                values[row["key"]] = json.loads(row["value"])
        for key in ("x_auto_send", "x_counts", "write_flow"):
            values[key] = {**DEFAULT_SETTINGS[key], **values[key]}
        # 10/12 作者：「每天发 10 个太少了，要发 50 个」——本机存过的 10 改成 50，只改这一次（标记单独存一行，之后他改成多少就是多少）
        if values["x_counts"].get("own_short") == 10 and not self._rows("SELECT 1 FROM settings WHERE key = 'x_counts_migrated_1012'"):
            values["x_counts"] = {**values["x_counts"], "own_short": 50}
            try:
                with self.tx() as conn:
                    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts', ?)", (json.dumps(values["x_counts"]),))
                    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts_migrated_1012', 'true')")
            except sqlite3.Error:
                pass
        # 10/12 晚 作者：短帖、repost 都改成每天 100，长文 3~5；本机存过的数量改这一次，之后他改成多少就是多少
        if not self._rows("SELECT 1 FROM settings WHERE key = 'x_counts_migrated_1012b'"):
            values["x_counts"] = {**values["x_counts"], "own_short": 100, "hot": 100, "articles": 4}
            try:
                with self.tx() as conn:
                    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts', ?)", (json.dumps(values["x_counts"]),))
                    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts_migrated_1012b', 'true')")
            except sqlite3.Error:
                pass
        return values

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        cleaned: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                raise StoreError(f"未知设置项：{key}")
            kind = type(DEFAULT_SETTINGS[key])
            try:
                cleaned[key] = kind(value)
            except (TypeError, ValueError) as exc:
                raise StoreError(f"设置项 {key} 的值无效") from exc
        if "x_auto_send" in cleaned:
            if any(k not in DEFAULT_SETTINGS["x_auto_send"] or not isinstance(v, bool)
                   for k, v in cleaned["x_auto_send"].items()):
                raise StoreError("X 自动发送开关只能是 short、quote、reply 的布尔值")
            cleaned["x_auto_send"] = {**current["x_auto_send"], **cleaned["x_auto_send"]}
        if "write_flow" in cleaned:
            flow = {**current["write_flow"], **cleaned["write_flow"]}
            custom = flow.get("custom")
            if not isinstance(flow.get("default"), str) or not isinstance(custom, dict) or len(custom) > 2 \
                    or any(not isinstance(k, str) or not 0 < len(k.strip()) <= 20 or not isinstance(v, list)
                           or any(not isinstance(i, str) for i in v) for k, v in custom.items()):
                raise StoreError("写作流程：default 是流程名，custom 最多存 2 个（名字 20 字以内，值是步骤 id 的列表）")
            pct = flow.get("max_change_pct", 20)
            if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 1 <= int(pct) <= 50:
                raise StoreError("改动预算要在 1% 到 50% 之间")
            cleaned["write_flow"] = {"default": flow["default"], "custom": {k.strip(): list(v) for k, v in custom.items()},
                                     "max_change_pct": int(pct)}
        if "components_off" in cleaned:
            from .edition import SWITCHES

            wrong = [k for k in cleaned["components_off"] if k not in SWITCHES]
            if wrong:
                raise StoreError(f"这个组件不能开关：{wrong[0]}")
            cleaned["components_off"] = sorted(set(cleaned["components_off"]))
        if cleaned.get("yanxishi_admin_url"):
            cleaned["yanxishi_admin_url"] = cleaned["yanxishi_admin_url"].strip()
            if not cleaned["yanxishi_admin_url"].startswith("https://"):
                raise StoreError("研习室后台地址需要以 https:// 开头")
        if "obsidian_vault" in cleaned:
            cleaned["obsidian_vault"] = cleaned["obsidian_vault"].strip()
            if not cleaned["obsidian_vault"]:
                raise StoreError("Obsidian 库路径不能为空")
        if "traffic_tags" in cleaned:
            cleaned["traffic_tags"] = {
                str(k): list(dict.fromkeys(str(t).strip().lstrip("#").strip() for t in (v or []) if str(t).strip().lstrip("#").strip()))
                for k, v in cleaned["traffic_tags"].items()
            }
        for key, label in (("x_follow_target", "X"), ("douyin_follow_target", "抖音")):
            if key not in cleaned:
                continue
            target = {**current[key], **cleaned[key]}
            try:
                start = datetime.strptime(target["start_day"], "%Y-%m-%d")
                end = datetime.strptime(target["end_day"], "%Y-%m-%d")
                target["start_day"], target["end_day"] = start.date().isoformat(), end.date().isoformat()
                target["start"], target["end"] = int(target["start"]), int(target["end"])
                if end <= start or not 0 <= target["start"] <= target["end"]:
                    raise ValueError
            except (ValueError, TypeError, KeyError) as exc:
                raise StoreError(f"{label} 涨粉目标需填写递增日期和非负粉丝数") from exc
            cleaned[key] = {k: target[k] for k in ("start_day", "start", "end_day", "end")}
        if "x_kpi" in cleaned:
            target = {**DEFAULT_SETTINGS["x_kpi"], **current.get("x_kpi", {}), **cleaned["x_kpi"]}
            try:
                target = {k: int(target[k]) for k in DEFAULT_SETTINGS["x_kpi"]}
                if any(n < 0 for n in target.values()) or target["replies_max"] < target["replies_min"]:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise StoreError("X KPI 需填非负整数，回复上限不能低于下限") from exc
            cleaned["x_kpi"] = target
        if "reply_gap_minutes" in cleaned and cleaned["reply_gap_minutes"] < 1:
            raise StoreError("回复间隔至少 1 分钟")
        if "x_counts" in cleaned:
            merged = {**DEFAULT_SETTINGS["x_counts"], **current.get("x_counts", {}), **cleaned["x_counts"]}
            try:
                merged = {"long": int(merged["long"]), "post_share": float(merged["post_share"]),
                          "own_short": int(merged["own_short"]), "hot": int(merged["hot"]),
                          "articles": int(merged["articles"])}
            except (TypeError, ValueError) as exc:
                raise StoreError("X 每天发多少要填数字") from exc
            if not 0 <= merged["long"] <= 50 or not 0 <= merged["own_short"] <= 200 or not 0 <= merged["hot"] <= 200 or not 0 <= merged["articles"] <= 10:
                raise StoreError("X 每天：长的 0–50 篇，短帖 0–200 条，repost 0–200 条，长文 0–10 篇")
            if not 0 <= merged["post_share"] <= 1:
                raise StoreError("长帖占比在 0 到 1 之间")
            cleaned["x_counts"] = merged
            with self.tx() as conn:  # 他自己存过一次，就不再做 10→50 的迁移
                conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts_migrated_1012', 'true')")
        if "threshold" in cleaned and not 1 <= cleaned["threshold"] <= 100:
            raise StoreError("爆款门槛需在 1× 到 100× 之间")
        if "auto_enqueue_limit" in cleaned and not 0 <= cleaned["auto_enqueue_limit"] <= 50:
            raise StoreError("自动入队上限需在 0 到 50 之间")
        if "auto_enqueue_threshold" in cleaned and not 1 <= cleaned["auto_enqueue_threshold"] <= 100:
            raise StoreError("自动拆解门槛需在 1× 到 100× 之间")
        if "sync_pages" in cleaned and not 1 <= cleaned["sync_pages"] <= 5:
            raise StoreError("同步页数需在 1 到 5 之间")
        if "sync_delay_seconds" in cleaned and cleaned["sync_delay_seconds"] < 1.5:
            raise StoreError("页间间隔不得小于 1.5 秒")
        with self.tx() as conn:
            for key, value in cleaned.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        current.update(cleaned)
        return current

    # -- accounts ---------------------------------------------------------

    def add_account(
        self,
        *,
        platform: str,
        profile_url: str,
        external_id: str | None,
        status: str,
        is_self: bool = False,
        kind: str | None = None,
    ) -> dict[str, Any]:
        duplicate = self._row("SELECT id FROM accounts WHERE profile_url = ?", (profile_url,))
        if duplicate is None and external_id:
            duplicate = self._row(
                "SELECT id FROM accounts WHERE platform = ? AND external_id = ?", (platform, external_id)
            )
        if duplicate is not None:
            raise StoreError("这个账号已经在库里了")
        kind = KIND_SELF if is_self else (kind or KIND_BENCHMARK)
        if kind not in ACCOUNT_KINDS:
            raise StoreError(f"不认识的账号类型：{kind}")
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts(platform, profile_url, external_id, is_self, kind, status, added_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (platform, profile_url, external_id, int(is_self), kind, status, now_iso()),
            )
            account_id = cursor.lastrowid
        return self.account(account_id)

    def account(self, account_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if row is None:
            raise StoreError("账号不存在")
        return row

    def accounts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM accounts ORDER BY is_self DESC, id")

    def followed_accounts(self) -> list[dict[str, Any]]:
        """Everyone 作者 follows. 2026-09-20: 对标 and 老师 collapsed back into one category —
        he treats them the same, and the reason to split them (keeping 老师 breakouts out of the
        daily recommendation) went away when the recommendation itself was removed."""
        return [a for a in self.accounts() if not a["is_self"]]

    def self_account(self, account_id: int | None = None) -> dict[str, Any] | None:
        if account_id is not None:
            return self._row("SELECT * FROM accounts WHERE is_self = 1 AND id = ?", (account_id,))
        return self._row("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id LIMIT 1")

    def my_accounts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM accounts WHERE is_self = 1 ORDER BY id")

    def update_account(self, account_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"nickname", "follower_count", "total_favorited", "signature", "status", "last_error", "last_synced_at", "external_id", "kind"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的账号字段：{sorted(unknown)}")
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE accounts SET {assignments} WHERE id = ?", (*fields.values(), account_id))
        return self.account(account_id)

    def delete_account(self, account_id: int) -> None:
        account = self.account(account_id)
        if account["is_self"]:
            raise StoreError("不能移除自己的账号")
        with self.tx() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # -- videos -----------------------------------------------------------

    def upsert_videos(self, account_id: int, videos: list[dict[str, Any]]) -> int:
        fetched_at = now_iso()
        with self.tx() as conn:
            for video in videos:
                conn.execute(
                    """
                    INSERT INTO videos(platform, video_id, account_id, title, published_at, duration_seconds, is_top,
                                       is_image_post, likes, comments, shares, collects, views, fetched_at)
                    VALUES(:platform, :video_id, :account_id, :title, :published_at, :duration_seconds, :is_top,
                           :is_image_post, :likes, :comments, :shares, :collects, :views, :fetched_at)
                    ON CONFLICT(platform, video_id) DO UPDATE SET
                        account_id = excluded.account_id, title = excluded.title, published_at = excluded.published_at,
                        duration_seconds = excluded.duration_seconds, is_top = excluded.is_top,
                        is_image_post = excluded.is_image_post, likes = excluded.likes, comments = excluded.comments,
                        shares = excluded.shares, collects = excluded.collects,
                        views = COALESCE(NULLIF(excluded.views, 0), videos.views), fetched_at = excluded.fetched_at
                    """,
                    {**video, "account_id": account_id, "fetched_at": fetched_at},
                )
                conn.execute(
                    "INSERT OR IGNORE INTO video_snapshots(video_id, fetched_at, likes, comments, shares, collects, views) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (video["video_id"], fetched_at, video.get("likes"), video.get("comments"), video.get("shares"), video.get("collects"), video.get("views")),
                )
        return len(videos)

    def videos(self, account_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM videos WHERE account_id = ? ORDER BY published_at DESC", (account_id,)
        )

    PUBLIC_WINDOW_SECONDS = 3600

    def public_videos(self, account_id: int) -> list[dict[str, Any]]:
        """还挂在公开主页上的作品。同步读的是公开主页，每次把看到的都刷新 fetched_at；
        设成私密或删掉的，从此停在最后一次被看到的时间（作者 9/27：只看公开的作品）。"""
        rows = self.videos(account_id)
        stamps = [r["fetched_at"] for r in rows if r.get("fetched_at")]
        if not stamps:
            return rows
        latest = datetime.fromisoformat(max(stamps))
        return [r for r in rows if r.get("fetched_at")
                and (latest - datetime.fromisoformat(r["fetched_at"])).total_seconds() <= self.PUBLIC_WINDOW_SECONDS]

    def account_snapshots(self, account_id: int, since_day: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT s.video_id, s.fetched_at, s.views, v.published_at FROM video_snapshots s JOIN videos v ON v.video_id = s.video_id "
            "WHERE v.account_id = ? AND v.is_image_post = 0 AND s.fetched_at >= ? ORDER BY s.fetched_at",
            (account_id, since_day),
        )

    def add_post_snapshots(self, platform: str, posts: list[dict[str, Any]], fetched_at: str) -> None:
        """B站 / X / 研习室 每条内容这一次读到的累计数（platform_stats.sync 写）。"""
        with self.tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO post_snapshots(platform, post_id, title, published_at, fetched_at, views) VALUES (?, ?, ?, ?, ?, ?)",
                [(platform, str(p["post_id"]), p.get("title"), p.get("published_at"), fetched_at, int(p["views"])) for p in posts],
            )

    def add_x_post_metrics(self, posts: list[dict[str, Any]], fetched_at: str) -> None:
        with self.tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO x_post_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(str(p["post_id"]), fetched_at, p.get("kind", "post"),
                  p.get("impressions", p.get("views")), p.get("bookmarks"), p.get("likes"),
                  p.get("replies"), p.get("reposts"), p.get("quotes"), p.get("profile_clicks"),
                  (p.get("text60") or p.get("title") or "")[:60],
                  p.get("posted_at", p.get("published_at"))) for p in posts],
            )

    def x_post_metrics(self, since_day: str = "0001-01-01") -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM x_post_metrics WHERE fetched_at >= ? ORDER BY fetched_at", (since_day,))

    def post_snapshots(self, platform: str, since_day: str) -> list[dict[str, Any]]:
        """Same shape as account_snapshots, so reach.daily_views works on both."""
        return self._rows(
            "SELECT post_id AS video_id, fetched_at, views, published_at FROM post_snapshots WHERE platform = ? AND fetched_at >= ? ORDER BY fetched_at",
            (platform, since_day),
        )

    def post_synced_at(self) -> dict[str, str]:
        return {row["platform"]: row["at"] for row in self._rows("SELECT platform, MAX(fetched_at) AS at FROM post_snapshots GROUP BY platform")}

    def day_close(self, day: str) -> dict[str, Any] | None:
        row = self._row("SELECT day, kind, data, frozen_at FROM day_close WHERE day = ?", (day,))
        return {**row, "data": json.loads(row["data"])} if row else None

    def day_closes(self, limit: int = 60) -> list[dict[str, Any]]:
        rows = self._rows("SELECT day, kind, data, frozen_at FROM day_close ORDER BY day DESC LIMIT ?", (limit,))
        return [{**r, "data": json.loads(r["data"])} for r in rows]

    def add_day_close(self, day: str, kind: str, data: dict[str, Any]) -> bool:
        """存一天的日结。已经存过就不动（存档不改），返回有没有新存。"""
        with self.tx() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO day_close(day, kind, data, frozen_at) VALUES (?, ?, ?, ?)",
                               (day, kind, json.dumps(data, ensure_ascii=False), now_iso()))
            return cur.rowcount > 0

    def first_snapshot_at(self) -> str | None:
        row = self._row("SELECT MIN(at) AS at FROM (SELECT MIN(fetched_at) AS at FROM video_snapshots UNION ALL SELECT MIN(fetched_at) FROM post_snapshots)")
        return row["at"] if row else None

    def reach_entries(self, since_day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT day, platform, views FROM reach_entries WHERE day >= ? ORDER BY day", (since_day,))

    def set_reach(self, day: str, platform: str, views: int | None) -> None:
        with self.tx() as conn:
            if views is None:
                conn.execute("DELETE FROM reach_entries WHERE day = ? AND platform = ?", (day, platform))
            else:
                conn.execute(
                    "INSERT INTO reach_entries(day, platform, views, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(day, platform) DO UPDATE SET views = excluded.views, updated_at = excluded.updated_at",
                    (day, platform, int(views), now_iso()),
                )

    def follower_counts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT day, platform, followers, source FROM follower_counts ORDER BY day, platform")

    def set_followers(self, day: str, platform: str, followers: int, source: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO follower_counts(day, platform, followers, source, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(day, platform) DO UPDATE SET followers = excluded.followers, source = excluded.source, updated_at = excluded.updated_at",
                (day, platform, int(followers), source, now_iso()),
            )

    # -- 今天：接下来要拍的、私信数、跳过和做完 ------------------------------

    def shoot_list(self, include_done: bool = False) -> list[dict[str, Any]]:
        where = "" if include_done else "WHERE done_at IS NULL"
        return self._rows(f"SELECT * FROM shoot_list {where} ORDER BY done_at IS NOT NULL, position, id")

    def shoot_item(self, item_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM shoot_list WHERE id = ?", (item_id,))
        if row is None:
            raise StoreError("这一条已经不在清单里了")
        return row

    def add_shoot_item(self, text: str, *, top: bool = False, topic_id: int | None = None, planned_day: str | None = None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise StoreError("写一句要拍什么")
        edge = self._row(f"SELECT {'MIN' if top else 'MAX'}(position) AS p FROM shoot_list WHERE done_at IS NULL")
        base = edge["p"] if edge and edge["p"] is not None else 0.0
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO shoot_list(text, position, topic_id, created_at, planned_day) VALUES (?, ?, ?, ?, ?)",
                               (text[:200], base - 1 if top else base + 1, topic_id, now_iso(), planned_day))
        return self.shoot_item(cur.lastrowid)

    def update_shoot_item(self, item_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"text", "position", "topic_id", "done_at", "planned_day"}
        if set(fields) - allowed:
            raise StoreError(f"不可更新的字段：{sorted(set(fields) - allowed)}")
        self.shoot_item(item_id)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE shoot_list SET {cols} WHERE id = ?", (*fields.values(), item_id))
        return self.shoot_item(item_id)

    def move_shoot_item(self, item_id: int, step: int) -> list[dict[str, Any]]:
        """上移（-1）或下移（+1）一格：和相邻那条交换位置。"""
        items = self.shoot_list()
        idx = next((i for i, it in enumerate(items) if it["id"] == item_id), None)
        if idx is None:
            raise StoreError("这一条已经不在清单里了")
        other = idx + step
        if 0 <= other < len(items):
            a, b = items[idx], items[other]
            with self.tx() as conn:
                conn.execute("UPDATE shoot_list SET position = ? WHERE id = ?", (b["position"], a["id"]))
                conn.execute("UPDATE shoot_list SET position = ? WHERE id = ?", (a["position"], b["id"]))
        return self.shoot_list()

    def place_shoot_item(self, item_id: int, index: int) -> list[dict[str, Any]]:
        """把这一条放到清单的第 index 位（从 0 数），后面的往后挪一位。日历上拖到某天就是这个。"""
        items = self.shoot_list()
        me = next((it for it in items if it["id"] == item_id), None)
        if me is None:
            raise StoreError("这一条已经不在清单里了")
        rest = [it for it in items if it["id"] != item_id]
        rest.insert(max(0, min(index, len(rest))), me)
        with self.tx() as conn:
            for i, it in enumerate(rest):
                conn.execute("UPDATE shoot_list SET position = ? WHERE id = ?", (float(i), it["id"]))
        return self.shoot_list()

    def delete_shoot_item(self, item_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM shoot_list WHERE id = ?", (item_id,))

    # -- Wendy 卡片里的对话（不放进 anna_chats：那张表启动时会把别的线程并进 Anna 的）------

    def wendy_thread(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM wendy_thread ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def add_wendy(self, who: str, text: str, *, source: str = "desk") -> dict[str, Any]:
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO wendy_thread(at, who, source, text) VALUES (?, ?, ?, ?)", (now_iso(), who, source, text[:4000]))
        return self._row("SELECT * FROM wendy_thread WHERE id = ?", (cur.lastrowid,))

    def last_touch(self, day: str) -> str | None:
        """他这一天在工作台里最后一次动静是几点：勾了日报、填了私信或 X 的数、写了跳过理由或做完了、
        勾了周历上的事、在卡片里回了 Wendy。都没有就是 None。（Wendy 催不催看这个。）"""
        row = self._row(
            """SELECT MAX(t) AS t FROM (
                 SELECT MAX(checked_at) AS t FROM daily_checks WHERE day = :day
                 UNION ALL SELECT MAX(updated_at) FROM dm_entries WHERE day = :day
                 UNION ALL SELECT MAX(updated_at) FROM kpi_counts WHERE day = :day
                 UNION ALL SELECT MAX(at) FROM driver_log WHERE day = :day AND kind != 'nudge'
                 UNION ALL SELECT MAX(done_at) FROM plan_items WHERE substr(done_at, 1, 10) >= :prev
                 UNION ALL SELECT MAX(at) FROM wendy_thread WHERE who = 'park' AND substr(at, 1, 10) >= :prev
               )""",
            {"day": day, "prev": (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()},
        )
        return row["t"] if row else None

    # -- 周历上不算分的事（「约两个博主诊断」这种）：哪天、做什么、做完没有 --------------

    def plan_items(self, since_day: str, until_day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM plan_items WHERE day >= ? AND day <= ? ORDER BY day, id", (since_day, until_day))

    def add_plan_item(self, day: str, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise StoreError("写一句这天要做什么")
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO plan_items(day, text, created_at) VALUES (?, ?, ?)", (day, text[:200], now_iso()))
        return self._row("SELECT * FROM plan_items WHERE id = ?", (cur.lastrowid,))

    def set_plan_item_done(self, item_id: int, done: bool) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE plan_items SET done_at = ? WHERE id = ?", (now_iso() if done else None, item_id))

    def delete_plan_item(self, item_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM plan_items WHERE id = ?", (item_id,))

    def dm_entries(self, since_day: str) -> dict[str, dict[str, int]]:
        return {r["day"]: {"received": r["received"], "replied": r["replied"]}
                for r in self._rows("SELECT * FROM dm_entries WHERE day >= ?", (since_day,))}

    # -- 收入账本（10/9）：一笔一行；source 是 consult 或产品清单里的 key。先手动记，以后接 Stripe 回调 --
    def revenue(self, since_day: str = "") -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM revenue WHERE day >= ? ORDER BY day, id", (since_day,))

    def add_revenue(self, day: str, amount: float, source: str, note: str = "") -> dict[str, Any]:
        if not amount or amount <= 0:
            raise StoreError("金额要大于 0")
        if not source:
            raise StoreError("选一个来源")
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO revenue(day, amount, source, note, created_at) VALUES (?, ?, ?, ?, ?)",
                               (day, float(amount), source, note.strip()[:200], now_iso()))
            rid = cur.lastrowid
        return self._rows("SELECT * FROM revenue WHERE id = ?", (rid,))[0]

    def delete_revenue(self, rid: int) -> bool:
        with self.tx() as conn:
            return conn.execute("DELETE FROM revenue WHERE id = ?", (rid,)).rowcount > 0

    def set_dm(self, day: str, received: int, replied: int) -> None:
        if received < 0 or replied < 0:
            raise StoreError("私信数不能是负数")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO dm_entries(day, received, replied, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET received = excluded.received, replied = excluded.replied, updated_at = excluded.updated_at",
                (day, int(received), int(replied), now_iso()),
            )

    # -- 老师和对标新发的视频：看过了没有、记了一句什么 --------------------------

    def feed_marks(self) -> dict[str, dict[str, Any]]:
        return {r["video_id"]: r for r in self._rows("SELECT * FROM feed_marks")}

    def set_feed_mark(self, video_id: str, *, seen: bool | None = None, note: str | None = None, opened: bool | None = None) -> None:
        """只有他点「看过了」才算看过。点「去看」只记成点开过（9/30 作者：看完觉得好，接下来要复刻或拆解，
        这一条不能自己消失；觉得没用他再点看过了）。记一句也不算看过。"""
        with self.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO feed_marks(video_id) VALUES (?)", (video_id,))
            if opened:
                conn.execute("UPDATE feed_marks SET opened_at = ? WHERE video_id = ?", (now_iso(), video_id))
            if seen is not None:
                conn.execute("UPDATE feed_marks SET seen_at = ? WHERE video_id = ?", (now_iso() if seen else None, video_id))
            if note is not None:
                conn.execute("UPDATE feed_marks SET note = ? WHERE video_id = ?", (note.strip()[:300] or None, video_id))

    # -- 流量视频（swipe.py） -------------------------------------------------

    def _swipe(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {**row, "info": json.loads(row["info"]) if row.get("info") else {}}

    def swipe_videos(self) -> list[dict[str, Any]]:
        return [self._swipe(r) for r in self._rows("SELECT * FROM swipe_videos ORDER BY id DESC")]

    def swipe_video(self, swipe_id: int) -> dict[str, Any]:
        row = self._swipe(self._row("SELECT * FROM swipe_videos WHERE id = ?", (swipe_id,)))
        if row is None:
            raise StoreError("这条流量视频已经不在了")
        return row

    def add_swipe(self, url: str, platform: str, note: str | None = None) -> dict[str, Any]:
        dup = self._row("SELECT id FROM swipe_videos WHERE url = ?", (url,))
        if dup:
            raise StoreError("这条已经存过了")
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO swipe_videos(url, platform, state, note, created_at) VALUES (?, ?, 'downloading', ?, ?)",
                               (url, platform, (note or "").strip()[:300] or None, now_iso()))
        return self.swipe_video(cur.lastrowid)

    def update_swipe(self, swipe_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"state", "error", "content_dir", "info", "note", "collection", "topic_id"}
        if set(fields) - allowed:
            raise StoreError(f"不可更新的字段：{sorted(set(fields) - allowed)}")
        if "info" in fields and fields["info"] is not None:
            fields["info"] = json.dumps(fields["info"], ensure_ascii=False)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE swipe_videos SET {cols} WHERE id = ?", (*fields.values(), swipe_id))
        return self.swipe_video(swipe_id)

    def delete_swipe(self, swipe_id: int) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM swipe_videos WHERE id = ?", (swipe_id,))

    def swipe_count_since(self, platform: str, since_iso: str) -> int:
        row = self._row("SELECT COUNT(*) AS n FROM swipe_videos WHERE platform = ? AND created_at >= ?", (platform, since_iso))
        return int(row["n"]) if row else 0

    def kpi_counts(self, since_day: str, key: str) -> dict[str, int]:
        return {r["day"]: int(r["value"]) for r in self._rows("SELECT day, value FROM kpi_counts WHERE key = ? AND day >= ?", (key, since_day))}

    def set_kpi_count(self, day: str, key: str, value: int) -> None:
        if value < 0:
            raise StoreError("数不能是负数")
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO kpi_counts(day, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (day, key, int(value), now_iso()),
            )

    def driver_mark(self, day: str, key: str, kind: str, reason: str | None = None) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO driver_log(day, key, kind, reason, at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(day, key, kind) DO UPDATE SET reason = excluded.reason, at = excluded.at",
                (day, key, kind, reason, now_iso()),
            )

    def driver_unmark(self, day: str, key: str, kind: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM driver_log WHERE day = ? AND key = ? AND kind = ?", (day, key, kind))

    # -- 当天补发哪几格：作者 在补发工作台挑的，按他点的顺序存（10/1 起；原来是早上随机抽）--------------------

    def backfill_plan(self, day: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM backfill_plan WHERE day = ? ORDER BY slot", (day,))

    def set_backfill_plan(self, day: str, cells: list[tuple[str, str]]) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM backfill_plan WHERE day = ?", (day,))
            conn.executemany("INSERT INTO backfill_plan(day, slot, video_id, platform) VALUES (?, ?, ?, ?)",
                             [(day, i, v, p) for i, (v, p) in enumerate(cells)])

    def driver_log(self, since_day: str = "", kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self._rows("SELECT * FROM driver_log WHERE day >= ? AND kind = ? ORDER BY at", (since_day, kind))
        return self._rows("SELECT * FROM driver_log WHERE day >= ? ORDER BY at", (since_day,))

    def snapshots(self, video_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM video_snapshots WHERE video_id = ? ORDER BY fetched_at", (video_id,))

    def video(self, video_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM videos WHERE video_id = ?", (video_id,))

    def account_median(self, account_id: int) -> float | None:
        likes = [
            row["likes"]
            for row in self._rows(
                "SELECT likes FROM videos WHERE account_id = ? AND is_top = 0 AND likes IS NOT NULL", (account_id,)
            )
        ]
        return float(statistics.median(likes)) if likes else None

    def followed_posts(self, days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
        """What the accounts 作者 follows published recently, newest first.

        Keyed on published_at, never on when the workbench first saw the video: a newly added
        teacher's first sync pulls their whole back catalogue, and that must not land in 进项.
        """
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        posts = []
        for account in self.followed_accounts():
            for video in self.videos(account["id"]):
                if (video["published_at"] or "") >= cutoff:
                    posts.append({**video, "account_nickname": account["nickname"], "account_id": account["id"]})
        posts.sort(key=lambda v: v["published_at"] or "", reverse=True)
        return posts

    def outliers(self, threshold: float) -> list[dict[str, Any]]:
        results = []
        for account in self.followed_accounts():
            median = self.account_median(account["id"])
            if not median:
                continue
            for video in self.videos(account["id"]):
                if video["likes"] is None or video["is_image_post"]:
                    continue
                multiple = video["likes"] / median
                if multiple >= threshold:
                    results.append({**video, "multiple": round(multiple, 1), "account_nickname": account["nickname"], "account_median": median})
        results.sort(key=lambda item: item["multiple"], reverse=True)
        return results

    # -- jobs -------------------------------------------------------------

    def enqueue(self, *, url: str, video_id: str | None, source: str, retry_failed: bool = False) -> tuple[dict[str, Any], bool]:
        """Queue a teardown unless the same video is already queued, running or done.

        9/29：以前失败过的视频，自动同步每次都当新爆款再排一次——同一条（没有人声，转写永远是空的）
        10 天里用 作者 的抖音登录下载了 37 次。自动入队（retry_failed=False）碰到失败过的就不再排；
        只有 作者 手动加、手动点重试才会再跑。"""
        if video_id:
            existing = self._row(
                "SELECT * FROM jobs WHERE video_id = ? AND stage != 'failed' ORDER BY id DESC LIMIT 1", (video_id,)
            )
            if existing is not None:
                return existing, False
            if not retry_failed:
                failed = self._row("SELECT * FROM jobs WHERE video_id = ? AND stage = 'failed' ORDER BY id DESC LIMIT 1", (video_id,))
                if failed is not None:
                    return failed, False
        stamp = now_iso()
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs(url, video_id, source, stage, created_at, updated_at) VALUES(?, ?, ?, 'queued', ?, ?)",
                (url, video_id, source, stamp, stamp),
            )
            job_id = cursor.lastrowid
        return self.job(job_id), True

    def job(self, job_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise StoreError("任务不存在")
        return row

    def jobs(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))

    def job_for_video(self, video_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM jobs WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,))

    def update_job(self, job_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"stage", "error", "report_path", "video_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"不可更新的任务字段：{sorted(unknown)}")
        if "stage" in fields and fields["stage"] not in JOB_STAGES:
            raise StoreError(f"未知任务阶段：{fields['stage']}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.tx() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?", (*fields.values(), now_iso(), job_id)
            )
        return self.job(job_id)

    def next_queued_job(self) -> dict[str, Any] | None:
        return self._row("SELECT * FROM jobs WHERE stage = 'queued' ORDER BY id LIMIT 1")

    def recover_interrupted_jobs(self) -> int:
        """Jobs left mid-stage by a crash go back to the queue; finished work is kept."""
        placeholders = ",".join("?" for _ in ACTIVE_STAGES)
        with self.tx() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET stage = 'queued', updated_at = ? WHERE stage IN ({placeholders})",
                (now_iso(), *ACTIVE_STAGES),
            )
        return cursor.rowcount

    def cancel_job(self, job_id: int) -> None:
        job = self.job(job_id)
        if job["stage"] != "queued":
            raise StoreError("只能取消还在排队的任务")
        with self.tx() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ? AND stage = 'queued'", (job_id,))

    def retry_job(self, job_id: int) -> dict[str, Any]:
        job = self.job(job_id)
        if job["stage"] != "failed":
            raise StoreError("只有失败的任务可以重试")
        return self.update_job(job_id, stage="queued", error=None)
