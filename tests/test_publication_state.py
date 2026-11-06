"""Presentation reads receipts and flags conflicting links without changing history."""
from __future__ import annotations

import pytest

from content_studio import platform_page as pp
from tests.test_web import client  # noqa: F401


@pytest.mark.parametrize("fields,state", [
    ({"ready": False, "why": "没有成片"}, "not_ready"),
    ({"ready": True}, "ready"),
    ({"ready": True, "plan": "wait", "plan_note": "等抖音先发"}, "wait"),
    ({"ready": False, "job": {"state": "running"}}, "running"),
    ({"ready": True, "job": {"state": "awaiting_confirm"}}, "awaiting_confirm"),
    ({"ready": True, "job": {"state": "unknown"}}, "unknown"),
    ({"ready": False, "job": {"state": "done", "draft": True}}, "draft"),
    ({"ready": True, "job": {"state": "failed"}, "plan": "retry"}, "failed"),
    ({"ready": True, "job": {"state": "done"}}, "ready"),
    ({"sent": {"url": None, "how": "mark"}, "job": {"state": "failed"}}, "published"),
])
def test_presentation_preserves_delivery_evidence_independently_of_preparation(fields, state):
    result = pp.presentation_state(fields)
    assert result["state"] == state
    assert result["plan"] == fields.get("plan")
    assert result["plan_note"] == fields.get("plan_note")


def test_duplicate_posts_merge_mirrors_but_keep_source_provenance():
    first = {"topic_id": 1, "title": "第一条", "platform": "x", "form": "text", "url": "https://x.com/a/status/123"}
    mirror = {**first, "source": "publish_records"}
    post = {**first, "source": "publish_posts"}
    assert pp.duplicate_publications([post, mirror, {**post, "form": "video"}]) == []
    other = {**first, "topic_id": 2, "source": "publish_records", "url": "https://twitter.com/b/status/123?ref=share"}
    groups = pp.duplicate_publications([post, mirror, other, {**other, "platform": "youtube"}])
    assert len(groups) == 1
    assert groups[0]["post_id"] == "123" and groups[0]["topic_ids"] == [1, 2]
    assert groups[0]["publications"][0]["sources"] == ["publish_posts", "publish_records"]
    assert other["url"].endswith("?ref=share")  # no repair or mutation


def test_duplicate_warning_reads_both_tables_without_changing_links(client):
    store = client.app.state.store
    a, b = (store.create_topic(title)["id"] for title in ("第一条", "第二条"))
    store.set_publish_post(a, "x", "text", published=True, url="https://x.com/a/status/123")
    # A different legacy form must not disappear merely because a form-level row exists.
    store.set_publish_record(a, "x", published=True, form="video", url="https://x.com/a/status/456")
    store.set_publish_record(b, "x", published=True, form="text", url="https://twitter.com/b/status/456")
    before = [store.publish_records(tid) for tid in (a, b)]
    warnings = client.get("/api/platform/x").json()["publication_warnings"]
    assert len(warnings) == 1 and warnings[0]["post_id"] == "456"
    assert warnings[0]["topic_ids"] == [a, b]
    assert client.get(f"/api/topics/{a}/pack").json()["publication_warnings"] == warnings
    assert [store.publish_records(tid) for tid in (a, b)] == before


def _matrix_topic(client):
    from tests.test_web import SEC, _wait_sync

    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    client.put("/api/platform/x/settings", json={"on": True})
    store = client.app.state.store
    tid = store.create_topic("作品5")["id"]
    store.update_topic(tid, published_video_id="5")
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video"]}})
    return store, tid


def _x_cell(client):
    response = client.get("/api/outbox/matrix")
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["rows"] if row["video_id"] == "5")["cells"]["x"]


def test_matrix_never_turns_skip_or_an_old_form_link_into_publication(client):
    store, tid = _matrix_topic(client)
    store.set_publish_record(tid, "x", published=True, form="text", url="https://x.com/a/status/123")
    cell = _x_cell(client)
    assert cell["state"] == "none" and cell["publication_state"] == "not_ready"
    assert cell["forms"][0]["presentation"]["state"] == "not_ready"
    store.set_publish_skip(tid, "x", skip=True)
    cell = _x_cell(client)
    assert cell["state"] == "skip" and "views" not in cell


def test_matrix_reads_form_receipts_even_when_legacy_record_tracks_another_form(client):
    store, tid = _matrix_topic(client)
    store.set_publish_post(tid, "x", "video", published=True, url="https://x.com/a/status/123")
    store.set_publish_record(tid, "x", published=True, form="text", url="https://x.com/a/status/456")
    store.add_post_snapshots("x", [{"post_id": "123", "views": 10}, {"post_id": "456", "views": 90}], "2026-10-08T10:00:00+00:00")
    cell = _x_cell(client)
    assert cell["state"] == "views" and cell["views"] == 10
    assert cell["publication_state"] == "published"
    assert cell["forms"][0]["presentation"]["source"] == "post"
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"]}})
    store.set_publish_record(tid, "x", published=False)
    cell = _x_cell(client)
    assert cell["publication_state"] == "partial" and cell["views"] == 10


def test_matrix_does_not_double_count_one_public_post_for_two_forms(client):
    store, tid = _matrix_topic(client)
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"]}})
    for form in ("video", "text"):
        store.set_publish_post(tid, "x", form, published=True, url="https://x.com/a/status/123")
    store.add_post_snapshots("x", [{"post_id": "123", "views": 12}], "2026-10-08T10:00:00+00:00")
    assert _x_cell(client)["views"] == 12


def test_matrix_labels_a_known_sum_partial_until_every_published_post_has_data(client):
    store, tid = _matrix_topic(client)
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"]}})
    for form, pid in (("video", "123"), ("text", "456")):
        store.set_publish_post(tid, "x", form, published=True, url=f"https://x.com/a/status/{pid}")
    store.add_post_snapshots("x", [{"post_id": "123", "views": 23}], "2026-10-08T10:00:00+00:00")
    cell = _x_cell(client)
    assert cell["publication_state"] == "published" and cell["views"] == 23
    assert cell["metrics_complete"] is False
    assert cell["missing_post_ids"] == ["456"] and cell["missing_forms"] == ["text"]
    metrics = {row["form"]: row["metrics"] for row in cell["forms"]}
    assert metrics["video"] == {"views": 23, "post_id": "123", "complete": True, "source": "post_snapshot"}
    assert metrics["text"]["views"] is None and metrics["text"]["complete"] is False
    result = client.get("/api/outbox/matrix").json()
    row = next(row for row in result["rows"] if row["video_id"] == "5")
    assert row["metrics_complete"] is False and "x" in row["missing_platforms"]
    assert result["metrics_complete"] is False
    # A real zero is a completed reading, not a missing snapshot.
    store.add_post_snapshots("x", [{"post_id": "456", "views": 0}], "2026-10-08T10:01:00+00:00")
    cell = _x_cell(client)
    assert cell["views"] == 23 and cell["metrics_complete"] is True
    assert cell["missing_post_ids"] == cell["missing_forms"] == []


def test_matrix_can_cover_historical_rows_after_thirty_with_bounded_pagination(client):
    from datetime import datetime, timedelta, timezone

    store, tid = _matrix_topic(client)
    template = store.video("5")
    store.upsert_videos(template["account_id"], [
        {**template, "video_id": f"80000000000000{i:04}", "title": f"旧作品{i}",
         "published_at": (datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat()}
        for i in range(40)
    ])
    videos = client.get("/api/backfill").json()["videos"]
    target = videos[30]["video_id"]
    store.update_topic(tid, published_video_id=target)
    store.set_publish_post(tid, "x", "video", published=True, url="https://x.com/a/status/789")
    first = client.get("/api/outbox/matrix?limit=30").json()
    assert target not in {row["video_id"] for row in first["rows"]}
    assert first["coverage"]["has_more"] is True
    full = client.get("/api/outbox/matrix?limit=500").json()
    assert len(full["rows"]) == len(videos) and full["coverage"]["complete"] is True
    row = next(row for row in full["rows"] if row["video_id"] == target)
    assert row["cells"]["x"]["publication_state"] == "published"
    assert row["cells"]["x"]["forms"][0]["presentation"]["url"] == "https://x.com/a/status/789"
    tail = client.get("/api/outbox/matrix?offset=30&limit=500").json()
    assert tail["rows"][0]["video_id"] == target
    assert len(first["rows"]) + len(tail["rows"]) == len(videos)
    assert tail["coverage"]["offset"] == 30 and tail["coverage"]["has_more"] is False
    for query in ("limit=501", "limit=0", "offset=-1", "limit=bad"):
        assert client.get(f"/api/outbox/matrix?{query}").status_code == 422
