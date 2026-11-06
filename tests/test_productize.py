"""A stranger's clone must work without 作者's machine: bundled Anna, neutral defaults,
one env var for the data directory, and prompts that use the profile's own name."""
from __future__ import annotations

import importlib
from pathlib import Path

from content_studio import identity, outline, paths, profile, store, video_project
from content_studio.extras.team import anna


def test_config_dir_follows_env(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "studio-home"))
    assert paths.config_dir() == tmp_path / "studio-home"
    monkeypatch.delenv(paths.HOME_ENV)
    assert paths.config_dir() == Path("~/.config/content-studio").expanduser()


def test_bundled_anna_role_and_framework_load(monkeypatch):
    monkeypatch.delenv(anna.ANNA_ROLE_ENV, raising=False)
    monkeypatch.delenv(outline.WORKFLOWS_ENV, raising=False)
    soul = anna.load_soul(skill_path=Path("/nonexistent/SKILL.md"))
    assert "Anna｜流量 CEO" in soul["text"]
    assert str(anna.DEFAULT_ROLE) in soul["sources"]
    assert "开头候选" in outline.load_framework()


def test_defaults_do_not_name_a_person():
    assert store.DEFAULT_SETTINGS["obsidian_vault"] == ""
    assert all("/Volumes/" not in str(p) for p in video_project.DEFAULT_ROOTS)
    for module in (anna, outline):
        assert "notes" not in str(module.__dict__["DEFAULT_ROLE" if module is anna else "DEFAULT_WORKFLOWS"])


def test_author_comes_from_profile(monkeypatch, tmp_path):
    cfg = tmp_path / "profile.yaml"
    cfg.write_text("me:\n  name: 小王\n  platforms:\n    channels: 小王聊AI\n", encoding="utf-8")
    monkeypatch.setenv(profile.PROFILE_ENV, str(cfg))
    identity.reset()
    me = identity.author()
    assert (me.name, me.channel) == ("小王", "小王聊AI")
    assert me.channel_phrase == "他的号是「小王聊AI」，"
    identity.reset()


def test_author_without_profile_is_neutral(monkeypatch, tmp_path):
    monkeypatch.setenv(profile.PROFILE_ENV, str(tmp_path / "missing.yaml"))
    monkeypatch.setattr(profile, "SEARCH_PATHS", ())
    identity.reset()
    me = identity.author()
    assert me.name == "作者" and me.channel == "" and me.channel_phrase == ""
    identity.reset()


def test_profile_check_knows_anna_keys(tmp_path):
    role = tmp_path / "Anna.md"
    role.write_text("# Anna", encoding="utf-8")
    checks = {c.key: c for c in profile.check({"anna": {"role": str(role), "workflows": str(tmp_path)}})}
    assert checks["anna.role"].ok and not checks["anna.role"].required
    assert not checks["anna.workflows"].ok  # folder has no 一勾式骨架.md
    assert "一勾式骨架.md" in checks["anna.workflows"].hint


def test_example_profile_lists_anna_section():
    text = profile.EXAMPLE_PATH.read_text(encoding="utf-8")
    assert "anna:" in text and "  role:" in text and "  workflows:" in text


def test_profile_anna_paths_reach_the_env(monkeypatch, tmp_path):
    """2026-09-22：上线后 serve 直接崩——web.py 用了 os 没 import，而测试里从没给过带 anna 的 profile。"""
    from content_studio.web import _apply_profile
    from content_studio.store import StudioStore

    monkeypatch.delenv(anna.ANNA_ROLE_ENV, raising=False)
    monkeypatch.delenv(outline.WORKFLOWS_ENV, raising=False)
    role = tmp_path / "Anna.md"
    role.write_text("# Anna", encoding="utf-8")
    _apply_profile(StudioStore(tmp_path / "s.sqlite3"), {"anna": {"role": str(role), "workflows": str(tmp_path)}})
    assert __import__("os").environ[anna.ANNA_ROLE_ENV] == str(role)
    assert __import__("os").environ[outline.WORKFLOWS_ENV] == str(tmp_path)
