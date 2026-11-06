from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from content_studio.creator_metrics import (
    CreatorMetricsStore,
    CreatorMetricsSyncer,
    RiskControlError,
    load_cookie_file,
)


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _item(video_id: int, published_at: datetime, title: str, *, likes: str = "1646") -> dict:
    return {
        "id": video_id,
        "description": title,
        "create_time": int(published_at.timestamp()),
        "metrics": {
            "view_count": "81825",
            "completion_rate": "0.009243",
            "completion_rate_5s": "0.370092",
            "cover_click_rate": "0.310511",
            "bounce_rate_2s": "0.385793",
            "avg_view_second": "25.364939",
            "like_count": likes,
            "share_count": "257",
            "comment_count": "42",
            "favorite_count": "1431",
            "homepage_visit_count": "1579",
            "subscribe_count": "410",
        },
    }


def _transport(responses: list[dict]):
    seen_cursors: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("max_cursor", "0")
        seen_cursors.append(cursor)
        index = 0 if cursor == "0" else 1
        return httpx.Response(200, json=responses[index], request=request)

    return httpx.MockTransport(handler), seen_cursors


def test_sync_persists_recent_records_and_maps_creator_metrics(tmp_path: Path) -> None:
    page_one = {
        "status_code": 0,
        "has_more": True,
        "max_cursor": 123,
        "items": [
            _item(101, datetime(2026, 9, 12, tzinfo=timezone.utc), "recent one"),
            _item(102, datetime(2026, 3, 1, tzinfo=timezone.utc), "outside window"),
        ],
    }
    page_two = {
        "status_code": 0,
        "has_more": False,
        "max_cursor": 123,
        "items": [_item(103, datetime(2026, 8, 1, tzinfo=timezone.utc), "recent two")],
    }
    transport, seen_cursors = _transport([page_one, page_two])
    store = CreatorMetricsStore(tmp_path / "creator.sqlite3")
    client = httpx.Client(transport=transport)

    summary = CreatorMetricsSyncer(
        client=client,
        store=store,
        now=lambda: NOW,
        sleep=lambda _seconds: None,
    ).sync(days=90)

    assert summary.seen == 3
    assert summary.stored == 2
    assert summary.skipped_outside_window == 1
    assert seen_cursors == ["0", "123"]
    assert store.path.stat().st_mode & 0o077 == 0

    records = store.list_records()
    assert [record.video_id for record in records] == ["101", "103"]
    first = records[0]
    assert first.view_count == 81825
    assert first.completion_rate_5s == pytest.approx(0.370092)
    assert first.cover_click_rate == pytest.approx(0.310511)
    assert first.bounce_rate_2s == pytest.approx(0.385793)
    assert first.avg_view_second == pytest.approx(25.364939)
    assert first.fan_increment == 410
    assert first.fetched_at.endswith("+00:00")


def test_repeated_sync_upserts_without_duplicate_rows(tmp_path: Path) -> None:
    response = {
        "status_code": 0,
        "has_more": False,
        "max_cursor": 0,
        "items": [_item(101, datetime(2026, 9, 12, tzinfo=timezone.utc), "same video")],
    }
    transport, _ = _transport([response, response])
    store = CreatorMetricsStore(tmp_path / "creator.sqlite3")
    client = httpx.Client(transport=transport)
    syncer = CreatorMetricsSyncer(
        client=client,
        store=store,
        now=lambda: NOW,
        sleep=lambda _seconds: None,
    )

    first = syncer.sync(days=90)
    second = syncer.sync(days=90)

    assert first.inserted == 1
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 1
    assert store.count() == 1


def test_cookie_loader_accepts_browser_export_list(tmp_path: Path) -> None:
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            [
                {"name": " sessionid ", "value": " abc ", "domain": ".douyin.com"},
                {"name": "ttwid", "value": "xyz", "domain": ".douyin.com"},
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)

    assert load_cookie_file(path) == {"sessionid": "abc", "ttwid": "xyz"}


def test_sync_stops_on_risk_control_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status_code": 1, "message": "captcha required"}, request=request)

    store = CreatorMetricsStore(tmp_path / "creator.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        syncer = CreatorMetricsSyncer(
            client=client,
            store=store,
            now=lambda: NOW,
            sleep=lambda _seconds: None,
        )
        with pytest.raises(RiskControlError):
            syncer.sync(days=90)
