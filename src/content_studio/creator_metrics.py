from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import stat
import time
from typing import Any, Callable

import httpx


WORK_LIST_URL = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
CREATOR_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class CreatorMetricsError(RuntimeError):
    """Base error for creator metrics synchronization."""


class CookieFileError(CreatorMetricsError):
    """The cookie file is missing, unsafe, or invalid."""


class CreatorAuthError(CreatorMetricsError):
    """The creator session is missing or no longer authenticated."""


class RiskControlError(CreatorMetricsError):
    """Douyin returned a CAPTCHA or risk-control response."""


def load_cookie_file(path: Path) -> dict[str, str]:
    """Load a browser-export cookie JSON file without logging its values."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CookieFileError(f"cookie file does not exist: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CookieFileError(
            f"cookie file must be private (mode 600 or stricter): {path}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CookieFileError(f"cookie file is not valid JSON: {path}") from exc

    if isinstance(raw, list):
        cookies = {
            str(item["name"]).strip(): str(item["value"]).strip()
            for item in raw
            if isinstance(item, dict) and item.get("name") and item.get("value")
        }
    elif isinstance(raw, dict):
        cookies = {
            str(name).strip(): str(value).strip()
            for name, value in raw.items()
            if name and value
        }
    else:
        cookies = {}

    if not cookies:
        raise CookieFileError(f"cookie file contains no usable cookies: {path}")
    return cookies


def _as_int(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _iso_timestamp(value: Any) -> str | None:
    timestamp = _as_int(value)
    if timestamp is None or timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class CreatorVideoMetric:
    """One creator backend record with canonical field names."""

    video_id: str
    title: str
    published_at: str
    fetched_at: str
    view_count: int | None
    completion_rate: float | None
    completion_rate_5s: float | None
    cover_click_rate: float | None
    bounce_rate_2s: float | None
    avg_view_second: float | None
    like_count: int | None
    share_count: int | None
    comment_count: int | None
    favorite_count: int | None
    homepage_visit_count: int | None
    fan_increment: int | None
    raw_json: str

    @classmethod
    def from_item(cls, item: dict[str, Any], fetched_at: str) -> CreatorVideoMetric | None:
        video_id = str(item.get("id") or item.get("aweme_id") or "").strip()
        published_at = _iso_timestamp(item.get("create_time"))
        if not video_id or not published_at:
            return None
        metrics = item.get("metrics") or {}
        return cls(
            video_id=video_id,
            title=str(item.get("description") or item.get("desc") or "").strip(),
            published_at=published_at,
            fetched_at=fetched_at,
            view_count=_as_int(metrics.get("view_count")),
            completion_rate=_as_float(metrics.get("completion_rate")),
            completion_rate_5s=_as_float(metrics.get("completion_rate_5s")),
            cover_click_rate=_as_float(metrics.get("cover_click_rate")),
            bounce_rate_2s=_as_float(metrics.get("bounce_rate_2s")),
            avg_view_second=_as_float(metrics.get("avg_view_second")),
            like_count=_as_int(metrics.get("like_count")),
            share_count=_as_int(metrics.get("share_count")),
            comment_count=_as_int(metrics.get("comment_count")),
            favorite_count=_as_int(metrics.get("favorite_count")),
            homepage_visit_count=_as_int(metrics.get("homepage_visit_count")),
            fan_increment=_as_int(metrics.get("subscribe_count")),
            raw_json=json.dumps(item, ensure_ascii=False, sort_keys=True),
        )


class CreatorMetricsStore:
    """SQLite store for local, idempotent creator metric records."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_video_metrics (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                view_count INTEGER,
                completion_rate REAL,
                completion_rate_5s REAL,
                cover_click_rate REAL,
                bounce_rate_2s REAL,
                avg_view_second REAL,
                like_count INTEGER,
                share_count INTEGER,
                comment_count INTEGER,
                favorite_count INTEGER,
                homepage_visit_count INTEGER,
                fan_increment INTEGER,
                raw_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CreatorMetricsStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def upsert(self, record: CreatorVideoMetric) -> bool:
        """Insert a record; return False when an existing row was updated."""
        exists = self._connection.execute(
            "SELECT 1 FROM creator_video_metrics WHERE video_id = ?",
            (record.video_id,),
        ).fetchone()
        self._connection.execute(
            """
            INSERT INTO creator_video_metrics (
                video_id, title, published_at, fetched_at, view_count,
                completion_rate, completion_rate_5s, cover_click_rate,
                bounce_rate_2s, avg_view_second, like_count, share_count,
                comment_count, favorite_count, homepage_visit_count,
                fan_increment, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title = excluded.title,
                published_at = excluded.published_at,
                fetched_at = excluded.fetched_at,
                view_count = excluded.view_count,
                completion_rate = excluded.completion_rate,
                completion_rate_5s = excluded.completion_rate_5s,
                cover_click_rate = excluded.cover_click_rate,
                bounce_rate_2s = excluded.bounce_rate_2s,
                avg_view_second = excluded.avg_view_second,
                like_count = excluded.like_count,
                share_count = excluded.share_count,
                comment_count = excluded.comment_count,
                favorite_count = excluded.favorite_count,
                homepage_visit_count = excluded.homepage_visit_count,
                fan_increment = excluded.fan_increment,
                raw_json = excluded.raw_json
            """,
            (
                record.video_id,
                record.title,
                record.published_at,
                record.fetched_at,
                record.view_count,
                record.completion_rate,
                record.completion_rate_5s,
                record.cover_click_rate,
                record.bounce_rate_2s,
                record.avg_view_second,
                record.like_count,
                record.share_count,
                record.comment_count,
                record.favorite_count,
                record.homepage_visit_count,
                record.fan_increment,
                record.raw_json,
            ),
        )
        self._connection.commit()
        return exists is None

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM creator_video_metrics"
        ).fetchone()
        return int(row["count"])

    def list_records(self) -> list[CreatorVideoMetric]:
        rows = self._connection.execute(
            "SELECT * FROM creator_video_metrics ORDER BY published_at DESC, video_id"
        ).fetchall()
        return [
            CreatorVideoMetric(
                video_id=row["video_id"],
                title=row["title"],
                published_at=row["published_at"],
                fetched_at=row["fetched_at"],
                view_count=row["view_count"],
                completion_rate=row["completion_rate"],
                completion_rate_5s=row["completion_rate_5s"],
                cover_click_rate=row["cover_click_rate"],
                bounce_rate_2s=row["bounce_rate_2s"],
                avg_view_second=row["avg_view_second"],
                like_count=row["like_count"],
                share_count=row["share_count"],
                comment_count=row["comment_count"],
                favorite_count=row["favorite_count"],
                homepage_visit_count=row["homepage_visit_count"],
                fan_increment=row["fan_increment"],
                raw_json=row["raw_json"],
            )
            for row in rows
        ]


@dataclass(frozen=True)
class SyncSummary:
    seen: int
    stored: int
    inserted: int
    updated: int
    skipped_outside_window: int
    skipped_invalid: int
    fetched_at: str
    cutoff: str


class CreatorMetricsSyncer:
    """Serial, manually-triggered client for the creator work list endpoint."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        store: CreatorMetricsStore,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
        endpoint: str = WORK_LIST_URL,
    ) -> None:
        self.client = client
        self.store = store
        self.now = now
        self.sleep = sleep
        self.endpoint = endpoint

    def sync(self, *, days: int = 90, delay_seconds: float = 1.0, page_size: int = 12) -> SyncSummary:
        if days <= 0:
            raise ValueError("days must be positive")
        if page_size <= 0:
            raise ValueError("page_size must be positive")

        now = self.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        fetched_at = now.isoformat()
        cutoff_dt = now - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        cursor = "0"
        seen_ids: set[str] = set()
        seen = stored = inserted = updated = skipped_old = skipped_invalid = 0

        while True:
            response = self.client.get(
                self.endpoint,
                params={
                    "scene": "star_atlas",
                    "device_platform": "android",
                    "status": "0",
                    "count": str(page_size),
                    "max_cursor": cursor,
                    "cookie_enabled": "true",
                    "screen_width": "1280",
                    "screen_height": "720",
                    "browser_language": "zh-CN",
                    "browser_platform": "MacIntel",
                    "browser_name": "Mozilla",
                    "browser_version": DEFAULT_USER_AGENT,
                    "browser_online": "true",
                    "timezone_name": "Asia/Shanghai",
                    "aid": "1128",
                    "support_h265": "1",
                },
                headers={"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT},
            )
            data = self._read_response(response)
            items = data.get("items") or []
            if not isinstance(items, list):
                raise CreatorMetricsError("creator work list returned an invalid items field")

            for item in items:
                if not isinstance(item, dict):
                    skipped_invalid += 1
                    continue
                seen += 1
                video_id = str(item.get("id") or item.get("aweme_id") or "").strip()
                if video_id and video_id in seen_ids:
                    continue
                if video_id:
                    seen_ids.add(video_id)
                published_at = _iso_timestamp(item.get("create_time"))
                if published_at is None:
                    skipped_invalid += 1
                    continue
                if datetime.fromisoformat(published_at) < cutoff_dt:
                    skipped_old += 1
                    continue
                record = CreatorVideoMetric.from_item(item, fetched_at)
                if record is None:
                    skipped_invalid += 1
                    continue
                if self.store.upsert(record):
                    inserted += 1
                else:
                    updated += 1
                stored += 1

            next_cursor = str(data.get("max_cursor") or "0")
            if not bool(data.get("has_more")) or next_cursor == cursor:
                break
            cursor = next_cursor
            if delay_seconds > 0:
                self.sleep(delay_seconds)

        return SyncSummary(
            seen=seen,
            stored=stored,
            inserted=inserted,
            updated=updated,
            skipped_outside_window=skipped_old,
            skipped_invalid=skipped_invalid,
            fetched_at=fetched_at,
            cutoff=cutoff,
        )

    @staticmethod
    def _read_response(response: httpx.Response) -> dict[str, Any]:
        body = response.text[:4000].lower()
        if any(marker in body for marker in ("captcha", "验证码", "风控", "risk control")):
            raise RiskControlError("Douyin returned a CAPTCHA or risk-control response; stop and retry after manual review")
        if response.status_code in (401, 403):
            raise CreatorAuthError("creator session is not authenticated; log in again and re-export cookies")
        if response.status_code >= 400:
            raise CreatorMetricsError(f"creator work list request failed with HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise CreatorAuthError("creator session returned a non-JSON response; log in again and re-export cookies") from exc
        if not isinstance(data, dict):
            raise CreatorMetricsError("creator work list returned a non-object response")
        status_code = data.get("status_code")
        if status_code not in (None, 0):
            message = str(data.get("message") or data.get("status_msg") or "creator request was rejected").lower()
            if any(marker in message for marker in ("captcha", "验证码", "风控", "risk")):
                raise RiskControlError("Douyin returned a CAPTCHA or risk-control response; stop and retry after manual review")
            raise CreatorAuthError("creator session was rejected; log in again and re-export cookies")
        return data
