from __future__ import annotations

from datetime import datetime, timezone

from pathlib import Path

import pytest

from content_studio.store import StudioStore
from content_studio.worker import TeardownWorker, WorkerConfig, normalize_video_url


@pytest.fixture
def store(tmp_path: Path) -> StudioStore:
    value = StudioStore(tmp_path / "studio.sqlite3")
    yield value
    value.close()


def _config(tmp_path: Path) -> WorkerConfig:
    return WorkerConfig(
        cookie_path=tmp_path / "cookies.json",
        data_dir=tmp_path / "data",
        downloads_dir=tmp_path / "downloads",
        creator_db=None,
        glossary_path=None,
    )


def test_normalize_video_url_accepts_share_text_and_rejects_profiles() -> None:
    assert normalize_video_url("复制打开抖音 https://www.douyin.com/video/123?x=1 看看") == (
        "https://www.douyin.com/video/123",
        "123",
    )
    assert normalize_video_url("https://www.douyin.com/user/abc?modal_id=456") == (
        "https://www.douyin.com/video/456",
        "456",
    )
    assert normalize_video_url("https://v.douyin.com/AbC/") == ("https://v.douyin.com/AbC/", None)
    with pytest.raises(ValueError, match="账号主页"):
        normalize_video_url("https://www.douyin.com/user/abc")
    with pytest.raises(ValueError, match="只支持抖音"):
        normalize_video_url("https://www.bilibili.com/video/1")


def test_worker_walks_stages_and_records_report(store: StudioStore, tmp_path: Path) -> None:
    stages: list[str] = []

    def process(url: str, **kwargs) -> dict:
        for stage in ("downloading", "transcribing", "analyzing"):
            kwargs["on_stage"](stage)
            stages.append(store.job(1)["stage"])
        return {"content_id": "123", "report_json": "/r/123/report.json"}

    store.enqueue(url="https://www.douyin.com/video/123", video_id="123", source="手动")
    worker = TeardownWorker(store, _config(tmp_path), process_fn=process)
    assert worker.drain() == 1
    assert stages == ["downloading", "transcribing", "analyzing"]
    job = store.job(1)
    assert job["stage"] == "done"
    assert job["report_path"] == "/r/123/report.json"


def test_failure_is_recorded_and_retry_requeues(store: StudioStore, tmp_path: Path) -> None:
    def boom(url: str, **kwargs) -> dict:
        kwargs["on_stage"]("downloading")
        raise RuntimeError("下载失败：CDN 超时")

    store.enqueue(url="https://www.douyin.com/video/1", video_id="1", source="手动")
    TeardownWorker(store, _config(tmp_path), process_fn=boom).drain()
    job = store.job(1)
    assert job["stage"] == "failed"
    assert "CDN 超时" in job["error"]
    assert store.retry_job(1)["stage"] == "queued"


def test_duplicate_video_is_not_queued_twice_but_failed_one_can_be_requeued(store: StudioStore) -> None:
    first, created = store.enqueue(url="u", video_id="1", source="手动")
    assert created
    again, created_again = store.enqueue(url="u", video_id="1", source="手动")
    assert not created_again and again["id"] == first["id"]
    store.update_job(first["id"], stage="failed", error="x")
    _, auto_after_failure = store.enqueue(url="u", video_id="1", source="对标爆款")
    assert not auto_after_failure  # 9/29：自动的不再重排失败过的
    _, created_after_failure = store.enqueue(url="u", video_id="1", source="手动", retry_failed=True)
    assert created_after_failure


def test_interrupted_jobs_are_recovered_but_done_jobs_are_kept(store: StudioStore) -> None:
    running, _ = store.enqueue(url="a", video_id="1", source="手动")
    done, _ = store.enqueue(url="b", video_id="2", source="手动")
    store.update_job(running["id"], stage="transcribing")
    store.update_job(done["id"], stage="done")
    assert store.recover_interrupted_jobs() == 1
    assert store.job(running["id"])["stage"] == "queued"
    assert store.job(done["id"])["stage"] == "done"


def test_worker_uses_library_median_as_baseline(store: StudioStore, tmp_path: Path) -> None:
    from content_studio.accounts import add_account, normalize_post

    account = add_account(store, "https://www.douyin.com/user/MS4wLjABAAAAx")
    posts = [
        {"aweme_id": str(i), "desc": "t", "create_time": int(datetime.now(timezone.utc).timestamp()) - 86400, "duration": 60000, "statistics": {"digg_count": likes}}
        for i, likes in enumerate([100, 300, 5000], start=1)
    ]
    store.upsert_videos(account["id"], [normalize_post(post) for post in posts])
    seen: dict = {}

    def process(url: str, **kwargs) -> dict:
        seen["baseline"] = kwargs["baseline_fn"](Path("."), Path("."), Path("."))
        return {"content_id": "3", "report_json": "r"}

    store.enqueue(url="https://www.douyin.com/video/3", video_id="3", source="对标")
    TeardownWorker(store, _config(tmp_path), process_fn=process).drain()
    assert seen["baseline"]["median_likes"] == 300.0


def test_only_queued_jobs_can_be_cancelled(store: StudioStore) -> None:
    from content_studio.store import StoreError

    queued, _ = store.enqueue(url="a", video_id="1", source="手动")
    running, _ = store.enqueue(url="b", video_id="2", source="手动")
    store.update_job(running["id"], stage="downloading")
    store.cancel_job(queued["id"])
    assert store.job_for_video("1") is None
    with pytest.raises(StoreError):
        store.cancel_job(running["id"])


def test_auto_enqueue_does_not_retry_a_video_that_failed(tmp_path) -> None:
    """9/29：一条没人声的视频转写永远是空的，自动同步每次都把它当新爆款再排——10 天用 作者 的登录下了 37 次。
    自动入队碰到失败过的不再排；手动加（retry_failed=True）照样能再跑。"""
    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "s.sqlite3")
    job, new = store.enqueue(url="https://www.douyin.com/video/1", video_id="1", source="对标爆款 · A")
    store.update_job(job["id"], stage="failed", error="transcript has no usable lines")
    again, new = store.enqueue(url="https://www.douyin.com/video/1", video_id="1", source="对标爆款 · A")
    assert new is False and again["id"] == job["id"]
    manual, new = store.enqueue(url="https://www.douyin.com/video/1", video_id="1", source="手动添加", retry_failed=True)
    assert new is True and manual["stage"] == "queued"
