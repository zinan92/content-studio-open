"""core/places.py：东西放在哪，只认 store 里的设置和启动时给的目录。"""
from __future__ import annotations

from datetime import date

import pytest

from content_studio.core.dates import parse_day
from content_studio.core.places import Places
from content_studio.store import StudioStore


def test_parse_day() -> None:
    assert parse_day(None) == date.today()
    assert parse_day("2026-10-08") == date(2026, 10, 8)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_day("10/8")


def test_places_follow_settings_and_given_dirs(tmp_path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    places = Places(store, drafts_root=tmp_path / "drafts", data_dir=tmp_path / "data", report_dirs=[tmp_path / "data"])
    store.update_settings({"obsidian_vault": str(tmp_path / "vault")})
    assert places.vault_path() == str(tmp_path / "vault")
    assert places.topic_dir(7) == tmp_path / "drafts" / "topic-7"
    assert places.article_path({"article_path": "/a/b.md"}).name == "b.md" and places.article_path({}) is None
    report = tmp_path / "data" / "reports" / "123" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}")
    assert places.report_file("123") == report
    assert places.report_file("../x") is None and places.report_file("456") is None
    topic = store.create_topic(title="没关联视频项目")
    with pytest.raises(ValueError, match="还没有关联视频项目"):
        places.linked_project(topic["id"])
    assert places.final_video_path(topic) is None
    base = places.media_base(topic)
    assert base == tmp_path / "drafts" / f"topic-{topic['id']}" and base.is_dir()
    store.close()
