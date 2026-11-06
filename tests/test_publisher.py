from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest

from content_studio import publisher as pub


def _specs(tmp_path: Path, script: str) -> dict:
    cred = tmp_path / "cookie.json"
    cred.write_text("{}")
    old = (datetime.now() - timedelta(days=90)).timestamp()
    os.utime(cred, (old, old))
    return {"channels": {"label": "视频号", "copy_key": "channels", "credential": cred, "login_hint": "扫码",
                         "modes": {"draft": {"label": "草稿", "argv": [sys.executable, "-c", script, "{video}", "{title}", "{body}", "{tags}"]}}},
            "youtube": {"label": "YouTube", "copy_key": "youtube", "credential": tmp_path / "missing.json", "login_hint": "auth", "modes": {"private": {"label": "私享", "argv": ["true"]}}}}


def test_readiness_flags_old_and_missing_credentials(tmp_path: Path) -> None:
    ready = pub.readiness(_specs(tmp_path, ""))
    assert ready["channels"]["credential"] and ready["channels"]["likely_expired"] and "重新登录" in ready["channels"]["note"]
    assert ready["youtube"]["credential"] is False


def test_payload_requires_video_copy_and_known_mode(tmp_path: Path) -> None:
    specs = _specs(tmp_path, "")
    video = tmp_path / "final.mp4"
    with pytest.raises(pub.PublishError, match="成片"):
        pub.build_payload("channels", "draft", video=video, copy={}, publishers=specs)
    video.write_bytes(b"0" * 2048)
    with pytest.raises(pub.PublishError, match="标题"):
        pub.build_payload("channels", "draft", video=video, copy={}, publishers=specs)
    with pytest.raises(pub.PublishError, match="方式"):
        pub.build_payload("channels", "publish", video=video, copy={}, publishers=specs)
    payload = pub.build_payload("channels", "draft", video=video, copy={"channels": {"title": "标题", "body": "正文", "tags": ["AI"]}}, publishers=specs)
    assert payload["title"] == "标题" and payload["tags"] == ["AI"] and pub.command_for(payload, specs)[-4:] == [str(video), "标题", "正文", "AI"]


def test_platform_without_its_own_copy_uses_the_shared_one(tmp_path: Path) -> None:
    """补发的旧视频只种了抖音的标题：B 站、YouTube 点发布不该卡在「先写好标题」。"""
    specs = _specs(tmp_path, "")
    video = tmp_path / "final.mp4"
    video.write_bytes(b"0" * 2048)
    payload = pub.build_payload("channels", "draft", video=video, copy={"douyin": {"title": "看懂加息", "body": "", "tags": ["金融"]}}, publishers=specs)
    assert payload["title"] == "看懂加息" and payload["tags"] == ["金融"]


def test_confirm_window_and_state() -> None:
    now = datetime.now(timezone.utc)
    pub.confirmable({"state": "awaiting_confirm", "created_at": now.isoformat()}, now=now)
    with pytest.raises(pub.PublishError, match="30 分钟"):
        pub.confirmable({"state": "awaiting_confirm", "created_at": (now - timedelta(minutes=31)).isoformat()}, now=now)
    with pytest.raises(pub.PublishError, match="不在等待确认"):
        pub.confirmable({"state": "done", "created_at": now.isoformat()}, now=now)


def test_run_parses_json_and_explains_login(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0")
    ok_script = "import json,sys; print('log line'); print(json.dumps({'ok': True, 'status': 'draft_saved_in_platform', 'url': 'https://channels.weixin.qq.com/x', 'title': sys.argv[2]}))"
    specs = _specs(tmp_path, ok_script)
    payload = pub.build_payload("channels", "draft", video=video, copy={"channels": {"title": "T", "body": "", "tags": []}}, publishers=specs)
    result = pub.run(payload, publishers=specs)
    assert result["ok"] and result["title"] == "T" and pub.result_url(result).startswith("https://")
    bad = _specs(tmp_path, "import json; print(json.dumps({'ok': False, 'status': 'cookie_invalid'})); raise SystemExit(2)")
    failed = pub.run(payload, publishers=bad)
    assert failed["ok"] is False and "重新扫码" in pub.explain(failed)


def test_after_publishing_open_the_page_to_confirm() -> None:
    """作者 9/27：存了 X 草稿不知道发过去没有，还得自己去找。发完直接打开那一页。"""
    assert pub.confirm_url("x", {"id": "2104231031381635072"}) == "https://x.com/compose/articles/edit/2104231031381635072"
    assert pub.confirm_url("wechat_mp", {"media_id": "m"}) == "https://mp.weixin.qq.com/"
    assert pub.confirm_url("bilibili", {"platform_url": "https://member.bilibili.com/platform/upload-manager/article", "url": "https://www.bilibili.com/video/BV1"}).startswith("https://member.bilibili.com")
    assert pub.confirm_url("youtube", {"video_id": "abc"}) == "https://studio.youtube.com/video/abc/edit"


def test_youtube_sets_the_cover_after_upload_and_a_failure_is_only_a_note(tmp_path: Path) -> None:
    """9/29：YouTube 传完把定稿的封面设上去；设不上不算发布失败。"""
    import subprocess as sp

    cover = tmp_path / "c.png"
    cover.write_bytes(b"1")
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = argv
        return sp.CompletedProcess(argv, 0, stdout='{"ok": true, "message": "封面设好了"}\n', stderr="")

    assert pub.youtube_cover("vid123", cover, runner=runner) == {"thumbnail": "set", "thumbnail_message": "封面设好了"}
    assert seen["argv"][1].endswith("youtube_thumb.py") and seen["argv"][3] == "vid123" and seen["argv"][5] == str(cover)

    def refused(argv, **kw):
        return sp.CompletedProcess(argv, 1, stdout='{"ok": false, "message": "YouTube 不让这个频道用自定义封面"}\n', stderr="")

    assert pub.youtube_cover("vid123", cover, runner=refused)["thumbnail"] == "failed"


def test_youtube_private_upload_is_a_draft_with_its_public_link_ready(monkeypatch, tmp_path: Path) -> None:
    """9/29：私享 = 草稿（作者自己去后台公开）；公开以后的链接现在就知道，先带着。"""
    import subprocess as sp

    monkeypatch.setattr(pub.subprocess, "run", lambda argv, **kw: sp.CompletedProcess(argv, 0, stdout='{"ok": true, "video_id": "vid9", "privacy_status": "private"}\n', stderr=""))
    payload = {"platform": "youtube", "mode": "private", "video": str(tmp_path / "v.mp4"), "title": "t", "body": "b", "tags": [], "cover": ""}
    result = pub.run(payload)
    assert result["published"] is False and result["public_url"] == "https://www.youtube.com/watch?v=vid9"


def test_diagnose_says_why_what_to_do_and_which_button() -> None:
    """10/3 作者：「只给我展示 error 是没有用的」。用那天真实的两条报错。"""
    yt = ('andle_error_response(response_data, retryable_error)\n  File "/Users/me/work/content-ops/.venv/lib/python3.12/site-packages/google/oauth2/_client.py", '
          'line 73, in _handle_error_response\n    raise exceptions.RefreshError(\ngoogle.auth.exceptions.RefreshError: '
          "('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})")
    d = pub.diagnose("youtube", yt)
    assert d["fix"] == "login" and d["label"] == "登录 YouTube" and "过期" in d["why"] and "允许" in d["todo"]
    x = "连不上 X：<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)>"
    d = pub.diagnose("x", x)
    assert d["fix"] == "retry" and "网络" in d["why"] and "SSL" not in d["why"]
    assert pub.diagnose("x", "X 拒绝了这次调用（401）：密钥不对")["fix"] == "setup"
    assert pub.diagnose("x", "X 说超额了（429），等额度恢复再发")["fix"] == "wait"
    wx = pub.diagnose("wechat_mp", "errcode=40164 invalid ip 1.2.3.4 ipv6 ::ffff, not in whitelist")
    assert wx["fix"] == "setup" and "1.2.3.4" in wx["todo"]
    other = pub.diagnose("bilibili", 'Traceback (most recent call last):\n  File "a.py", line 1\nValueError: 视频太大')
    assert other["fix"] == "retry" and other["why"] == "ValueError: 视频太大"
    assert pub.diagnose("bilibili", "账号未登录")["fix"] == "login"
