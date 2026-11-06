from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_studio import hot
from content_studio.store import StudioStore

def test_benchmark_breakouts_split_recent_and_week(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    account = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/x", external_id="x", status="ok")
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    def iso(delta):
        return (now - delta).isoformat()
    base = dict(platform="抖音", duration_seconds=60, is_top=0, is_image_post=0, comments=0, shares=0, collects=0, views=None)
    videos = [dict(base, video_id=str(i), title=f"v{i}", published_at=iso(timedelta(days=20 + i)), likes=100) for i in range(5)]
    videos.append(dict(base, video_id="hot1", title="hot", published_at=iso(timedelta(hours=10)), likes=5000))
    videos.append(dict(base, video_id="hot2", title="old", published_at=iso(timedelta(days=4)), likes=3000))
    store.upsert_videos(account["id"], videos)
    result = hot.benchmark_breakouts(store, threshold=5, now=now)
    assert [v["video_id"] for v in result["items"]] == ["hot1"]
    assert result["fallback"] == []
    assert [v["video_id"] for v in hot.benchmark_breakouts(store, threshold=5, now=now + timedelta(days=2))["fallback"]] == ["hot1", "hot2"]
    store.close()


def test_rename_note_prefix_follows_a_renamed_vault_folder(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "rename.sqlite3")
    store.set_triage("Clippings/a.md", "topic")
    store.set_triage("003_原始输出/b.md", "shot")
    topic = store.create_topic(title="t", note_paths=["Clippings/a.md", "003_原始输出/b.md"])
    assert store.rename_note_prefix("Clippings", "002_clippings") == 2
    assert set(store.triage()) == {"002_clippings/a.md", "003_原始输出/b.md"}
    assert store.topic(topic["id"])["note_paths"] == ["002_clippings/a.md", "003_原始输出/b.md"]
    assert store.rename_note_prefix("Clippings", "002_clippings") == 0
    store.close()


def test_merge_anna_threads_folds_pages_into_one_conversation(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "anna.sqlite3")
    store.append_anna("input", {"role": "park", "text": "进项的问题", "at": "2026-09-19T01:00:00+00:00"}, session_id="s-in")
    store.append_anna("work:3", {"role": "park", "text": "视频的问题", "at": "2026-09-19T00:30:00+00:00"}, session_id="s-w")
    store.append_anna("input", {"role": "anna", "text": "答", "at": "2026-09-19T01:00:10+00:00", "actions": []})
    assert store.merge_anna_threads("main") == 2
    main = store.anna_chat("main")
    assert [m["text"] for m in main["messages"]] == ["视频的问题", "进项的问题", "答"]
    assert [m["scope"] for m in main["messages"]] == ["work:3", "input", "input"] and main["session_id"] is None
    assert store.merge_anna_threads("main") == 0 and store.anna_chat("input")["messages"] == []
    store.close()
