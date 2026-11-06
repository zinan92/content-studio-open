from __future__ import annotations

import os

import pytest

from datetime import datetime, timedelta, timezone

from content_studio import publish

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def test_similarity_prefers_same_story() -> None:
    assert publish.title_similarity("为什么这么多人看不到 AI 的影响力", "为什么这么多人，到今天还感觉不到AI？#AI #认知") > 0.4
    assert publish.title_similarity("为什么这么多人看不到 AI 的影响力", "黄金今天怎么走") < 0.25


def test_suggestions_respect_time_taken_and_image_posts() -> None:
    topic = {"title": "为什么这么多人看不到 AI 的影响力", "created_at": iso(NOW - timedelta(days=3))}
    videos = [
        {"video_id": "1", "title": "为什么这么多人看不到AI的影响力？", "published_at": iso(NOW - timedelta(days=1)), "is_image_post": 0},
        {"video_id": "2", "title": "为什么这么多人看不到AI的影响力", "published_at": iso(NOW - timedelta(days=30)), "is_image_post": 0},
        {"video_id": "3", "title": "为什么这么多人看不到AI的影响力", "published_at": iso(NOW - timedelta(days=1)), "is_image_post": 1},
        {"video_id": "4", "title": "为什么很多人看不到 AI 影响力", "published_at": iso(NOW), "is_image_post": 0},
    ]
    assert [v["video_id"] for v in publish.suggest_matches(topic, videos, taken={"4"})] == ["1"]


def test_performance_milestones_and_teardown_hint() -> None:
    published = NOW - timedelta(hours=80)
    video = {"video_id": "9", "title": "t", "published_at": iso(published), "likes": 3000, "collects": 600, "views": None}
    snaps = [
        {"fetched_at": iso(published + timedelta(hours=5)), "likes": 500, "views": None},
        {"fetched_at": iso(published + timedelta(hours=26)), "likes": 1800, "views": None},
        {"fetched_at": iso(published + timedelta(hours=79)), "likes": 3000, "views": None},
    ]
    perf = publish.performance(video, median_likes=600, snapshots=snaps, creator={"fan_increment": 40, "avg_view_second": 21}, has_report=False, now=NOW)
    assert perf["multiple"] == 5.0 and perf["collect_per_like"] == 0.2
    m = {x["hours"]: x for x in perf["milestones"]}
    assert m[24]["likes"] == 1800 and m[72]["likes"] == 3000 and m[168]["reached"] is False
    assert perf["suggest_teardown"] is True and perf["creator"]["fan_increment"] == 40
    assert publish.performance(video, median_likes=None, snapshots=[], creator=None, has_report=True, now=NOW)["suggest_teardown"] is False


def test_sync_staleness() -> None:
    assert publish.sync_is_stale(None)
    assert publish.sync_is_stale(iso(NOW - timedelta(hours=7)), now=NOW)
    assert not publish.sync_is_stale(iso(NOW - timedelta(hours=1)), now=NOW)


def test_a_platform_block_is_not_reported_as_an_expired_login(tmp_path) -> None:
    """作者: 视频号腾讯最近两个月开始封。Re-scanning a QR code fixes nothing, so the tile
    must not send him off to log in again."""
    from content_studio import publisher

    cred = tmp_path / "account.json"
    cred.write_text("{}", encoding="utf-8")
    spec = {"label": "视频号", "credential": cred, "blocked": "平台限制了自动发布", "login_hint": "x", "modes": {"draft": {"label": "草稿"}}}
    got = publisher.readiness({"channels": spec})["channels"]
    assert got["blocked"] is True and got["note"] == "平台限制了自动发布" and got["login_hint"] == ""

    # a channel without the flag still reports on credential age as before
    ok = publisher.readiness({"bilibili": {"label": "B 站", "credential": cred, "login_hint": "y", "modes": {"upload": {"label": "投稿"}}}})["bilibili"]
    assert ok.get("blocked") is not True and ok["credential"] is True


def test_a_text_only_channel_does_not_demand_a_video_or_a_title(tmp_path) -> None:
    """X 发的是正文本身。Requiring a 成片 or a 标题 would block 作者 on fields that do not exist there."""
    from content_studio import publisher

    spec = {"label": "X", "copy_key": "x", "credential": tmp_path / "s.yaml", "login_hint": "",
            "no_video": True, "modes": {"post": {"label": "发一条推文（纯文字）", "argv": ["python3", "-m", "content_studio.x_post", "--text", "{body}"]}}}
    copy = {"x": {"title": "", "body": "大多数人以为合规只是流程", "tags": ["AI"]}}
    payload = publisher.build_payload("x", "post", video=None, copy=copy, publishers={"x": spec})
    assert payload["video"] == "" and payload["body"] == "大多数人以为合规只是流程"
    assert publisher.command_for(payload, {"x": spec})[-1] == "大多数人以为合规只是流程"

    with pytest.raises(publisher.PublishError, match="正文"):
        publisher.build_payload("x", "post", video=None, copy={"x": {"body": ""}}, publishers={"x": spec})


def test_wechat_errors_are_told_apart_instead_of_all_reading_as_blocked(tmp_path) -> None:
    """40164 是 IP 白名单、40125 是密钥不对——2026-09-21 就是靠分清这两个才没去修错地方。"""
    import json as _json

    from content_studio.extras.autopost import wechat

    class Reply:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps(self.payload).encode()

    creds = {"appid": "wx", "secret": "s"}
    assert wechat.fetch_token(creds, opener=lambda *a, **k: Reply({"access_token": "x", "expires_in": 7200}))["ok"] is True
    assert wechat.fetch_token(creds, opener=lambda *a, **k: Reply({"errcode": 40164}))["reason"] == "ip"
    assert wechat.fetch_token(creds, opener=lambda *a, **k: Reply({"errcode": 40125}))["reason"] == "secret"
    assert wechat.fetch_token({}, opener=None)["reason"] == "unconfigured"


def test_wechat_state_is_cached_so_the_daily_token_quota_is_not_burned(tmp_path, monkeypatch) -> None:
    """微信取令牌每天有次数上限；每次渲染页面都问一次，几天就用光了。"""
    import json as _json
    from datetime import datetime, timedelta, timezone

    from content_studio.extras.autopost import wechat

    # 凭据平时读 ~/.config/content-studio/secrets.yaml；测试不碰这台机器上的真文件。
    monkeypatch.setattr(wechat, "load_credentials", lambda: {"appid": "wx-test", "secret": "s"})
    calls = []

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            calls.append(1)
            return _json.dumps({"access_token": "x"}).encode()

    cache = tmp_path / "state.json"
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    first = wechat.state(now=now, opener=lambda *a, **k: Reply(), cache_path=cache)
    assert first["ok"] and first["cached"] is False and len(calls) == 1

    again = wechat.state(now=now + timedelta(hours=1), opener=lambda *a, **k: Reply(), cache_path=cache)
    assert again["cached"] is True and len(calls) == 1  # 没有再问微信

    later = wechat.state(now=now + timedelta(hours=7), opener=lambda *a, **k: Reply(), cache_path=cache)
    assert later["cached"] is False and len(calls) == 2  # 过了 6 小时才重新问


def test_a_live_probe_beats_the_cookie_file_date(tmp_path) -> None:
    """2026-09-21：B 站 cookie 四个月没动，按 mtime 早该「过期」，一问平台却是 valid。
    把能用的通道报成坏的，会让 作者 白做一次扫码登录。"""
    from datetime import datetime, timedelta, timezone

    from content_studio import channel_probe, publisher

    cred = tmp_path / "cookie.json"
    cred.write_text("{}", encoding="utf-8")
    old = datetime.now().timestamp() - 120 * 86400
    os.utime(cred, (old, old))

    spec = {"label": "B 站", "credential": cred, "login_hint": "x", "modes": {"upload": {"label": "投稿"}},
            "probe": ["echo", "valid"], "probe_ok": "valid"}

    channel_probe.CACHE_PATH = tmp_path / "probes.json"
    got = publisher.readiness({"bilibili": spec})["bilibili"]
    assert got["age_days"] >= 119  # 文件确实很旧
    assert got["likely_expired"] is False and "能用" in got["note"]  # 但探测说能用


def test_probe_result_is_cached_and_a_failed_probe_does_not_flip_the_state(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from content_studio import channel_probe

    calls = []

    class Done:
        def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "", 0

    def runner(argv):
        calls.append(argv)
        return Done("valid")

    cache = tmp_path / "p.json"
    spec = {"probe": ["x"], "probe_ok": "valid"}
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    first = channel_probe.probe("b", spec, now=now, cache_path=cache, runner=runner)
    assert first["ok"] is True and len(calls) == 1
    again = channel_probe.probe("b", spec, now=now + timedelta(hours=2), cache_path=cache, runner=runner)
    assert again["cached"] is True and len(calls) == 1

    def boom(argv):
        raise OSError("探测命令跑不起来")

    later = channel_probe.probe("b", spec, now=now + timedelta(hours=9), cache_path=cache, runner=boom)
    assert later["ok"] is True and later.get("stale_probe") is True  # 保留上次结论，不误报成失效
    assert channel_probe.probe("none", {}, cache_path=cache) is None
