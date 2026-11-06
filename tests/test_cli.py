from __future__ import annotations

import json
from pathlib import Path

from content_studio.cli import main


def test_creator_sync_rejects_cookie_file_inside_repository(tmp_path: Path, monkeypatch) -> None:
    cookies = tmp_path / "cookies.json"
    cookies.write_text(json.dumps({"sessionid": "redacted"}), encoding="utf-8")
    cookies.chmod(0o600)
    monkeypatch.chdir(tmp_path)

    assert main(["creator-sync", "--cookies", "cookies.json", "--db", "db.sqlite3"]) == 1


def test_help_exposes_manual_creator_sync_command() -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0


def _sync_store(tmp_path: Path):
    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "studio.sqlite3")
    me = store.add_account(platform="抖音", profile_url="https://www.douyin.com/user/me", external_id="me", status="active", is_self=True)
    others = [store.add_account(platform="抖音", profile_url=f"https://www.douyin.com/user/b{i}", external_id=f"b{i}", status="active")
              for i in range(3)]
    return store, me, others


def _patch_sync(monkeypatch, calls: list, stop_at: int | None = None) -> None:
    from content_studio import cli, platform_stats
    from content_studio.accounts import RiskControlStop

    def fake_sync(store, account_id, *, client_factory, pages=None):
        calls.append((account_id, pages))
        if account_id == stop_at:
            raise RiskControlStop("抖音要求验证")
        return {"video_count": 0}

    monkeypatch.setattr(cli, "sync_account", fake_sync)
    monkeypatch.setattr(cli, "_cookie_client_factory", lambda _path: object)
    monkeypatch.setattr(cli, "sync_creator_metrics", lambda **_kw: {"status": "ok"})
    monkeypatch.setattr(platform_stats, "sync", lambda *_a, **_kw: {})
    from content_studio import followers

    monkeypatch.setattr(followers, "FETCHERS", {})  # 不真去问 X、B站


def test_sync_everything_without_benchmarks_only_touches_my_douyin(tmp_path: Path, monkeypatch) -> None:
    """9/29：「同步全部账号」只同步自己的号，对标一个都不碰。"""
    from content_studio.cli import sync_everything

    store, me, _others = _sync_store(tmp_path)
    calls: list = []
    _patch_sync(monkeypatch, calls)
    summary = sync_everything(store, cookie_path=tmp_path / "c", creator_db=tmp_path / "d", benchmarks=False)
    assert calls == [(me["id"], None)]
    assert summary["creator_metrics"] == {"status": "ok"}


def test_benchmarks_read_one_page_each_and_stop_on_risk_control(tmp_path: Path, monkeypatch) -> None:
    from content_studio.cli import BENCHMARK_PAGES, sync_benchmarks, sync_everything

    store, me, others = _sync_store(tmp_path)
    calls: list = []
    _patch_sync(monkeypatch, calls)
    sync_everything(store, cookie_path=tmp_path / "c", creator_db=tmp_path / "d")
    assert BENCHMARK_PAGES == 1
    assert calls == [(me["id"], None)] + [(o["id"], 1) for o in others]

    calls.clear()
    _patch_sync(monkeypatch, calls, stop_at=others[1]["id"])
    summary = sync_benchmarks(store, cookie_path=tmp_path / "c")
    assert [c[0] for c in calls] == [others[0]["id"], others[1]["id"]]  # 撞上风控，第三个不再碰
    assert summary["stopped"]


def test_risk_control_on_my_account_skips_benchmarks(tmp_path: Path, monkeypatch) -> None:
    from content_studio.cli import sync_everything

    store, me, _others = _sync_store(tmp_path)
    calls: list = []
    _patch_sync(monkeypatch, calls, stop_at=me["id"])
    summary = sync_everything(store, cookie_path=tmp_path / "c", creator_db=tmp_path / "d")
    assert calls == [(me["id"], None)]
    assert summary["stopped"]
