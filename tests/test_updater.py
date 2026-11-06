"""检查更新：只快进、只在更新分支且干净时动；开发机、有改动一律不动。git 全是假的，测试不碰真仓库。"""
from pathlib import Path

import pytest

from content_studio import updater


class FakeGit:
    def __init__(self, *, branch="main", dirty="", behind="2", fetch_ok=True):
        self.branch, self.dirty, self.behind, self.fetch_ok = branch, dirty, behind, fetch_ok
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        sub = args[1] if args[0] == "git" else args[0]
        if sub == "rev-parse":
            return 0, self.branch
        if sub == "log" and "-1" in args:
            return 0, "abc1234\x1f2026-09-28T20:00:00+08:00\x1ffeat: 当前版本"
        if sub == "status":
            return 0, self.dirty
        if sub == "fetch":
            return (0, "") if self.fetch_ok else (1, "Could not resolve host")
        if sub == "rev-list":
            return 0, self.behind
        if sub == "log":
            return 0, "def5678\x1f2026-09-29T09:00:00+08:00\x1ffeat: 新功能\nfed8765\x1f2026-09-29T10:00:00+08:00\x1ffix: 修一个 bug"
        if sub == "merge":
            return 0, "Fast-forward"
        return 0, ""


def test_status_lists_new_versions_on_the_update_branch() -> None:
    st = updater.status(run=FakeGit())
    assert st["can_update"] and st["behind"] == 2 and st["reason"] is None
    assert [c["subject"] for c in st["commits"]] == ["feat: 新功能", "fix: 修一个 bug"]
    assert st["head"]["hash"] == "abc1234"


@pytest.mark.parametrize("git,why", [
    (FakeGit(branch="feat/x"), "开发机"),
    (FakeGit(dirty=" M src/x.py"), "没提交的改动"),
    (FakeGit(fetch_ok=False), "连不上 GitHub"),
])
def test_dev_machines_and_offline_are_never_updated(git: FakeGit, why: str) -> None:
    st = updater.status(run=git)
    assert not st["can_update"] and why in st["reason"]
    with pytest.raises(updater.UpdateError, match=why):
        updater.apply(run=git, restart=lambda: pytest.fail("不该重启"))
    assert not any(a[:2] == ["git", "merge"] for a in git.calls)


def test_apply_fast_forwards_then_restarts() -> None:
    git, restarted = FakeGit(), []
    out = updater.apply(run=git, restart=lambda: restarted.append(True))
    assert out["updated"] and out["count"] == 2 and restarted == [True]
    assert ["git", "merge", "--ff-only", "origin/main"] in git.calls
    assert not any(a[0] != "git" for a in git.calls)  # 依赖没变，不跑 pip


def test_nothing_new_means_no_restart() -> None:
    out = updater.apply(run=FakeGit(behind="0"), restart=lambda: pytest.fail("不该重启"))
    assert out == {"updated": False, "message": "已经是最新版"}


def test_manifest_lists_every_dependency_with_its_access() -> None:
    names = {d["name"]: d for d in updater.deps()}
    assert {"content-downloader", "content-ops", "park-video-v2"} <= set(names)
    assert names["content-ops"]["access"] == "public" and names["park-video-v2"]["access"] == "public"


def test_every_dependency_comes_from_parks_own_github() -> None:
    """别人的开源项目用 作者 名下的副本：原作者删库或闭源，装机和更新都不受影响。"""
    import json

    for d in json.loads(updater.MANIFEST.read_text(encoding="utf-8"))["deps"]:
        assert d["repo"].startswith("https://github.com/zinan92/"), d["name"]
        if d["access"] == "fork":
            assert d.get("upstream"), d["name"]
