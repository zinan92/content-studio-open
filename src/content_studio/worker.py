from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
import threading
from typing import Any, Callable

from .pipeline import DEFAULT_GLOSSARY_PATH, _content_id_from_url, _default_baseline, _secure_dir, drop_partial, process_url
from .store import StudioStore
from .structure import load_glossary


logger = logging.getLogger(__name__)

ProcessFn = Callable[..., dict[str, Any]]


def video_id_from_url(url: str) -> str | None:
    return _content_id_from_url(url) or (
        re.search(r"modal_id=(\d+)", url).group(1) if re.search(r"modal_id=(\d+)", url) else None
    )


def normalize_video_url(raw: str) -> tuple[str, str | None]:
    """Accept a Douyin video link (or share text containing one)."""
    match = re.search(r"https?://\S+", raw or "")
    url = (match.group(0) if match else (raw or "")).strip().rstrip("，。,")
    if not url:
        raise ValueError("请粘贴抖音视频链接")
    if not re.search(r"(douyin\.com|iesdouyin\.com)", url):
        raise ValueError("目前只支持抖音视频链接（douyin.com 或 v.douyin.com）")
    if "/user/" in url and "modal_id=" not in url:
        raise ValueError("这是账号主页链接。拆解需要单条视频链接；加对标账号请去「对标雷达」")
    video_id = video_id_from_url(url)
    if video_id:
        return f"https://www.douyin.com/video/{video_id}", video_id
    return url, None


@dataclass
class WorkerConfig:
    cookie_path: Path
    data_dir: Path
    downloads_dir: Path
    creator_db: Path | None
    glossary_path: Path | None = DEFAULT_GLOSSARY_PATH
    whisper_model: str = "turbo"
    extra: dict[str, Any] = field(default_factory=dict)


class TeardownWorker:
    """Runs queued teardown jobs one at a time on a background thread."""

    def __init__(self, store: StudioStore, config: WorkerConfig, process_fn: ProcessFn = process_url) -> None:
        self.store = store
        self.config = config
        self.process_fn = process_fn
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_job_id: int | None = None
        # Called with the finished job once a teardown succeeds; the web layer uses it to write
        # the transcript into 作者's vault. A failure here must never fail the job.
        self.on_done: Callable[[dict[str, Any]], None] | None = None

    def _baseline_for(self, video_id: str | None) -> Callable[[Path, Path, Path], dict[str, Any] | None]:
        video = self.store.video(video_id) if video_id else None
        if video:
            median = self.store.account_median(video["account_id"])
            if median:
                count = len([v for v in self.store.videos(video["account_id"]) if not v["is_top"]])
                return lambda *_args: {"median_likes": median, "post_count": count, "excludes_pinned": True}
        return _default_baseline

    def run_one(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = job["id"]
        self.current_job_id = job_id
        try:
            data_dir = _secure_dir(self.config.data_dir)
            downloads_dir = _secure_dir(self.config.downloads_dir)
            result = self.process_fn(
                job["url"],
                cookie_path=self.config.cookie_path,
                data_dir=data_dir,
                downloads_dir=downloads_dir,
                whisper_model=self.config.whisper_model,
                baseline_fn=self._baseline_for(job.get("video_id")),
                creator_db=self.config.creator_db,
                glossary=load_glossary(self.config.glossary_path),
                on_stage=lambda stage: self.store.update_job(job_id, stage=stage),
                **self.config.extra,
            )
        except Exception as exc:  # noqa: BLE001 - every failure is shown on the job
            logger.warning("teardown job %s failed: %s", job_id, exc)
            try:
                freed = drop_partial(_secure_dir(self.config.downloads_dir), job.get("video_id") or _content_id_from_url(job["url"]))
                if freed:
                    logger.info("teardown job %s: dropped %.1f MB of partial download", job_id, freed / 1e6)
            except OSError as cleanup_exc:  # noqa: BLE001 - the job already failed
                logger.warning("teardown job %s: could not clean partial download: %s", job_id, cleanup_exc)
            return self.store.update_job(job_id, stage="failed", error=str(exc)[:500] or type(exc).__name__)
        finally:
            self.current_job_id = None
        done = self.store.update_job(
            job_id,
            stage="done",
            error=None,
            video_id=result.get("content_id") or job.get("video_id"),
            report_path=result.get("report_json"),
        )
        if self.on_done is not None:
            try:
                self.on_done(done)
            except Exception as exc:  # noqa: BLE001 - the teardown itself succeeded
                logger.warning("teardown job %s: after-done hook failed: %s", job_id, exc)
        return done

    def drain(self, max_jobs: int | None = None) -> int:
        """Process queued jobs synchronously (used by the CLI and tests)."""
        count = 0
        while max_jobs is None or count < max_jobs:
            job = self.store.next_queued_job()
            if job is None or self._stop.is_set():
                break
            self.run_one(job)
            count += 1
        return count

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        recovered = self.store.recover_interrupted_jobs()
        if recovered:
            logger.info("re-queued %s interrupted teardown jobs", recovered)
        self._thread = threading.Thread(target=self._loop, name="teardown-worker", daemon=True)
        self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.drain()
            except Exception:  # noqa: BLE001 - keep the worker alive
                logger.exception("teardown worker loop error")
            self._wake.wait(timeout=5.0)
            self._wake.clear()
