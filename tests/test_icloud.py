from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from content_studio import icloud, koubo, video_project


def test_mobile_documents_counts_as_synced(tmp_path: Path) -> None:
    mobile = tmp_path / "Mobile Documents"
    inside = mobile / "com~apple~CloudDocs" / "项目"
    inside.mkdir(parents=True)
    assert icloud.icloud_owner(inside, mobile=mobile) == mobile.resolve()
    assert icloud.icloud_owner(tmp_path / "别处", mobile=mobile) is None


def test_a_folder_with_the_provider_xattr_counts_as_synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """「桌面与文稿」同步开着时 ~/Documents 带 file-provider 的 xattr；它下面所有子目录都算。"""
    docs = tmp_path / "Documents"
    project = docs / "Codex" / "Workspaces" / "2026-09-22_9月22日"
    project.mkdir(parents=True)
    monkeypatch.setattr(icloud, "_has_xattr", lambda p, name: Path(p) == docs.resolve() and name == icloud.PROVIDER_XATTR)
    assert icloud.icloud_owner(project, mobile=tmp_path / "无") == docs.resolve()
    with pytest.raises(ValueError, match="iCloud 同步范围"):
        icloud.refuse_synced_root(project)


def test_the_video_root_is_refused_when_it_is_synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    monkeypatch.setattr(icloud, "icloud_owner", lambda p, **_: tmp_path)
    with pytest.raises(video_project.VideoProjectError, match="换到外置盘"):
        video_project.resolve_root(str(root))
    monkeypatch.setattr(icloud, "icloud_owner", lambda p, **_: None)
    assert video_project.resolve_root(str(root)) == root.resolve()


@pytest.mark.skipif(not hasattr(stat, "SF_DATALESS"), reason="iCloud 占位文件只有 macOS 有（SF_DATALESS）")
def test_a_placeholder_says_not_downloaded_instead_of_corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """9/22 真发生过：占位文件被 ffprobe 读成 moov atom not found，看起来像坏了，其实只是没下载。"""
    video = tmp_path / "粗剪.mp4"
    video.write_bytes(b"x")
    real_stat = os.stat

    class Flags:
        def __init__(self, st):
            self._st = st
            self.st_flags = stat.SF_DATALESS

        def __getattr__(self, name):
            return getattr(self._st, name)

    monkeypatch.setattr(icloud.os, "stat", lambda p, *a, **k: Flags(real_stat(p)) if Path(p) == video else real_stat(p))
    assert icloud.is_dataless(video) is True
    with pytest.raises(icloud.NotLocalError, match="没下载到本地"):
        icloud.ensure_local(video)
    with pytest.raises(koubo.KouboError, match="没下载到本地"):
        koubo.transcribe(video, tmp_path)


def test_a_normal_file_passes(tmp_path: Path) -> None:
    f = tmp_path / "a.srt"
    f.write_text("1\n", encoding="utf-8")
    assert icloud.is_dataless(f) is False
    assert icloud.ensure_local(f) == f
    assert icloud.is_dataless(tmp_path / "不存在") is False
