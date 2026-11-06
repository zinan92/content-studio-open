import io
import json
from pathlib import Path
import subprocess

import pytest

from content_studio import platform_stats, x_post
from content_studio.store import StudioStore


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_one_platform_failing_does_not_stop_the_others(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")

    def broken():
        raise platform_stats.StatsError("B站 登录过期了")

    out = platform_stats.sync(store, {"bilibili": broken, "x": lambda: [{"post_id": "1", "title": "t", "published_at": None, "views": 7}]})
    assert out == {"bilibili": {"ok": False, "error": "B站 登录过期了"}, "x": {"ok": True, "posts": 1}}
    assert [r["views"] for r in store.post_snapshots("x", "2000-01-01")] == [7]
    assert "bilibili" not in store.post_synced_at()


def test_bilibili_reads_views_from_the_creator_archive_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies = tmp_path / "bili.json"
    cookies.write_text(json.dumps({"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "s"}]}}))
    seen = []

    def fake_open(request, timeout=30):
        seen.append(request)
        body = {"code": 0, "data": {"arc_audits": [{"Archive": {"bvid": "BV1pU", "title": "新平台", "ptime": 1758700000}, "stat": {"view": 65}}]}}
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(platform_stats.urllib.request, "urlopen", fake_open)
    posts = platform_stats.bilibili_posts(cookies)
    assert posts == [{"post_id": "BV1pU", "title": "新平台", "published_at": "2025-09-24T07:46:40+00:00", "views": 65}]
    assert seen[0].get_header("Cookie") == "SESSDATA=s" and len(seen) == 1  # 不满一页就不翻了


def test_bilibili_logged_out_says_what_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies = tmp_path / "bili.json"
    cookies.write_text(json.dumps({"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "s"}]}}))
    monkeypatch.setattr(platform_stats.urllib.request, "urlopen", lambda r, timeout=30: FakeResponse(b'{"code": -101}'))
    with pytest.raises(platform_stats.StatsError, match="重新登录"):
        platform_stats.bilibili_posts(cookies)


def test_x_reads_impressions_and_signs_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = {"api_key": "key", "api_secret": "ksec", "access_token": "tok", "access_secret": "tsec"}
    urls = []

    def fake_open(request, timeout=30):
        urls.append(request.full_url)
        assert request.get_header("Authorization").startswith("OAuth ")
        if request.full_url.endswith("/users/me"):
            return FakeResponse(b'{"data": {"id": "42"}}')
        return FakeResponse(json.dumps({"data": [{"id": "9", "text": "hello", "created_at": "2026-09-24T12:00:00.000Z",
                                                  "public_metrics": {"impression_count": 986}}]}).encode())

    monkeypatch.setattr(platform_stats.urllib.request, "urlopen", fake_open)
    posts = platform_stats.x_posts(creds)
    assert len(posts) == 1 and posts[0]["views"] == posts[0]["impressions"] == 986
    assert posts[0]["kind"] == "post" and posts[0]["profile_clicks"] is None
    assert len(urls) == 3  # 一次身份查询 + 两次帖子读取
    assert "exclude=retweets" in urls[1]


def test_x_signature_covers_query_parameters() -> None:
    creds = {"api_key": "key", "api_secret": "ksec", "access_token": "tok", "access_secret": "tsec"}
    plain = x_post.authorization_header("GET", "https://api.x.com/2/x", creds, nonce="n", timestamp="1")
    with_query = x_post.authorization_header("GET", "https://api.x.com/2/x", creds, nonce="n", timestamp="1", query={"a": "1"})
    assert plain != with_query and "a=" not in with_query  # 参数进签名，不进头


def test_yanxishi_key_travels_by_env_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("content_studio.publisher._secret", lambda section, key: {"workbench_key": "k" * 40, "env_id": "env-1"}[key])
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw["env"]))
        out = {"ok": True, "items": [{"id": "a1", "title": "新平台", "publishedAt": "2026-09-24T10:00:00Z", "reads": 4}]}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(out) + "\n", stderr="")

    posts = platform_stats.yanxishi_posts(runner=runner)
    assert posts == [{"post_id": "a1", "title": "新平台", "published_at": "2026-09-24T10:00:00Z", "views": 4}]
    argv, env = calls[0]
    assert "k" * 40 not in " ".join(argv) and env["WORKBENCH_KEY"] == "k" * 40 and "/opt/homebrew/bin" in env["PATH"]


def test_yanxishi_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("content_studio.publisher._secret", lambda section, key: "k" * 40)
    runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout='{"ok": false, "error": "研习室拒绝了：admin_not_allowed"}\n', stderr="")
    with pytest.raises(platform_stats.StatsError, match="admin_not_allowed"):
        platform_stats.yanxishi_posts(runner=runner)


def test_a_timeout_gets_one_more_try(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) == 1:
            raise platform_stats.StatsError("network timeout")
        return [{"post_id": "a", "title": "t", "published_at": None, "views": 4}]

    assert platform_stats.sync(store, {"miniprogram": flaky}) == {"miniprogram": {"ok": True, "posts": 1}} and len(tries) == 2


def test_youtube_without_read_permission_is_skipped_quietly(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 2, stdout='{"ok": false, "status": "needs_reauth", "message": "重新授权一次"}', stderr="")
    out = platform_stats.sync(store, {"youtube": lambda: platform_stats.youtube_posts(runner=runner)})
    assert out["youtube"]["not_connected"] is True and "youtube" not in store.post_synced_at()


def test_youtube_views_are_read_once_authorized() -> None:
    body = {"ok": True, "items": [{"id": "abc", "title": "新平台", "publishedAt": "2026-09-24T10:00:00Z", "views": 31}]}
    runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")
    assert platform_stats.youtube_posts(runner=runner) == [{"post_id": "abc", "title": "新平台", "published_at": "2026-09-24T10:00:00Z", "views": 31}]
