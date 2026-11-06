from __future__ import annotations

from pathlib import Path

from content_studio import profile, vault


def _good(tmp_path: Path) -> dict:
    root = tmp_path / "vault"
    (root / "mine").mkdir(parents=True)
    (root / "clips").mkdir()
    return {
        "me": {"name": "某人", "douyin": "https://www.douyin.com/user/MS4wLjABAAAAxyz", "platforms": {"x": "someone"}},
        "ai": {"backend": "claude-cli"},
        "benchmarks": ["https://www.douyin.com/user/MS4wLjABAAAAabc"],
        "vault": {"path": str(root), "folders": {"my_writing": "mine", "clippings": "clips"}},
    }


def test_an_empty_profile_fails_exactly_the_required_items() -> None:
    """模板上标了 [必填] 的，就是这五个；少一个工作台起来也用不了。"""
    checks = profile.check({})
    required = {c.key for c in checks if c.required}
    assert required == {"me.name", "me.douyin", "ai.backend", "vault.path", "vault.folders.my_writing"}
    assert all(not c.ok for c in checks)
    s = profile.summary(checks)
    assert s["ok"] is False and len(s["missing_required"]) == 5


def test_a_filled_profile_passes_and_reports_only_the_optionals_left(tmp_path: Path) -> None:
    checks = profile.check(_good(tmp_path))
    s = profile.summary(checks)
    assert s["ok"] is True and s["missing_required"] == []
    left = {m["key"] for m in s["missing_optional"]}
    # 填了 x 和 clippings，这两项就不该再被报缺
    assert "me.platforms" not in left and "vault.folders.clippings" not in left
    assert "vault.folders.saved" in left and "secrets_file" in left


def test_required_items_are_validated_not_just_present(tmp_path: Path) -> None:
    """填了但填错，必须报错——一个「已填」的空壳会让人以为配好了。"""
    data = _good(tmp_path)
    data["me"]["douyin"] = "https://www.douyin.com/video/123"          # 视频链接不是主页
    data["ai"]["backend"] = "anthropic-api"                              # 还没接入的方式
    data["vault"]["folders"]["my_writing"] = "does-not-exist"            # 库里没这个文件夹
    bad = {c.key for c in profile.check(data) if c.required and not c.ok}
    assert bad == {"me.douyin", "ai.backend", "vault.folders.my_writing"}


def test_the_checklist_reads_like_instructions_not_a_stack_trace() -> None:
    text = profile.render_checklist(profile.check({}), None)
    assert "还没有 profile.yaml" in text and "cp profile.example.yaml profile.yaml" in text
    assert "必填" in text and "可选" in text and "❌" in text and "○" in text
    assert "起来了也用不了" in text


def test_vault_folder_names_come_from_the_profile() -> None:
    """这是 profile 第一次真正改变行为的地方：别人的库不叫 003_原始输出。"""
    try:
        vault.configure({"folders": {"my_writing": "notes/mine", "clippings": "inbox"},
                         "dailies": [{"key": "ai", "label": "AI", "folder": "daily/ai"}]})
        by_key = {s.key: s for s in vault.INBOX_SOURCES}
        assert by_key["raw"].folder == "notes/mine" and by_key["raw"].timeless is True
        assert by_key["clipping"].folder == "inbox"
        assert "saved" not in by_key                        # 可选没配 → 不列，别留一个永远空的 tab
        assert by_key["benchmark"].folder == "002_对标内容"   # 没给的保留默认
        assert [(d.key, d.folder) for d in vault.DAILY_SOURCES] == [("ai", "daily/ai")]
        # 再配一次只给 my_writing：clippings 必须能回来（从默认重建，不是从上一次的结果）
        vault.configure({"folders": {"my_writing": "x"}})
        assert {s.key for s in vault.INBOX_SOURCES} == {"benchmark", "raw"}
    finally:
        vault.configure(None)
    # 复位后和从没配过一样，后面的测试不受影响
    assert {s.key for s in vault.INBOX_SOURCES} == {"benchmark", "clipping", "saved", "raw"}
    assert len(vault.DAILY_SOURCES) == 3


def test_find_profile_prefers_the_explicit_path_then_env_then_search(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "a.yaml"; explicit.write_text("me: {}", encoding="utf-8")
    from_env = tmp_path / "b.yaml"; from_env.write_text("me: {}", encoding="utf-8")
    monkeypatch.setenv(profile.PROFILE_ENV, str(from_env))
    assert profile.find_profile(explicit) == explicit
    assert profile.find_profile(None) == from_env
    monkeypatch.delenv(profile.PROFILE_ENV)
    monkeypatch.setattr(profile, "SEARCH_PATHS", (tmp_path / "nope.yaml",))
    assert profile.find_profile(None) is None
    assert profile.load(None) == {}                     # 没文件不是错误，是「还没配」


def test_backend_check_matches_supported_runtime_and_keeps_legacy_profiles(tmp_path) -> None:
    data = _good(tmp_path)
    for backend in ("codex", "claude", "claude-cli"):
        data["ai"]["backend"] = backend
        check = next(x for x in profile.check(data) if x.key == "ai.backend")
        assert check.ok
        assert "不代表已经登录" in check.hint
    data["ai"]["backend"] = "unknown-provider"
    assert not next(x for x in profile.check(data) if x.key == "ai.backend").ok
