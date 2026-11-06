from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

import pytest

from content_studio import videolib

MB = 1 << 20
OLD = datetime(2026, 10, 5, 16, 0).timestamp()
NOW = datetime(2026, 10, 7, 12, 0).timestamp()


def _file(path: Path, tag: str, *, size: int = MB + 10, mtime: float = OLD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = tag.encode() * (size // len(tag) + 1)
    path.write_bytes(body[:size])
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "ssd" / "视频"
    root.mkdir(parents=True)
    (root / videolib.MARKER).write_text("规范", encoding="utf-8")
    return root


def _plan(lib: Path, home: Path, **kw):
    return videolib.plan(lib, home=home, now=NOW, open_files=kw.pop("open_files", lambda paths: set()), **kw)


def test_library_must_carry_the_naming_rules(tmp_path: Path, lib: Path) -> None:
    assert videolib.check_library(lib) == lib
    with pytest.raises(videolib.VideoLibError, match="没插"):
        videolib.check_library(tmp_path / "空的")
    assert videolib.library_from("/Volumes/Phone SSD/视频/exports") == Path("/Volumes/Phone SSD/视频")
    assert videolib.library_from("") is None


def test_names_put_the_date_first() -> None:
    assert videolib.dated_name("2026-10-05 13.54.48 Zinan的快速会议 155925747", OLD) == "2026-10-05 Zinan的快速会议 155925747"
    assert videolib.dated_name("content-studio-promo-20261004-codex", OLD) == "2026-10-04 content-studio-promo-20261004-codex"
    assert videolib.dated_name("张三 1005 咨询录音", OLD) == "2026-10-05 张三 1005 咨询录音"
    assert videolib.category_of("作者内容流水线 横屏", ".mp4") == videolib.PROMO
    assert videolib.category_of("张三 咨询录音", ".m4a") == videolib.TALK
    assert videolib.category_of("No.1200 Road 4", ".m4a") == videolib.TALK  # 音频默认当录音
    assert videolib.category_of("recall test", ".mp4") == videolib.INBOX


def test_plan_sorts_by_content_and_leaves_what_others_read(tmp_path: Path, lib: Path) -> None:
    home = tmp_path / "home"
    _file(home / "Movies/作者内容流水线/横屏-科技.mp4", "a")
    _file(home / "Movies/作者内容流水线/竖屏.mp4", "b")
    _file(home / "Movies/JianyingPro/草稿/素材.mp4", "c")  # 剪映草稿按绝对路径引用素材
    _file(home / "Downloads/张三 1005 咨询录音.m4a", "d")
    _file(home / "Downloads/随手录的.mov", "e")
    _file(home / "Downloads/小样.mp4", "f", size=1000)  # 太小
    _file(home / "Downloads/正在导出.mp4", "g", mtime=NOW - 60)
    _file(home / "Downloads/某工程/out.mp4", "h")
    (home / "Downloads/某工程/package.json").write_text("{}")
    (home / "Downloads/链接.mp4").symlink_to(home / "Downloads/随手录的.mov")
    _file(home / "Documents/TencentMeeting/2026-10-05 13.54.48 Zinan的快速会议 155925747/meeting_01.mp4", "i")
    _file(home / "work/cs-promo/out/Content-Studio-4K.mp4", "j")
    _file(home / "work/cs-promo/out/qa/层.mov", "k")
    _file(home / "work/cs-promo/public/audio/mix.wav", "l")  # Remotion 素材
    _file(home / ".config/content-studio/consults/原件.m4a", "m")  # 工作台自己读

    moves, skipped = _plan(lib, home)
    got = {str(m.dest): m.source.relative_to(home).as_posix() for m in moves}
    assert got == {
        "宣传片/2026-10-05 作者内容流水线/横屏-科技.mp4": "Movies/作者内容流水线/横屏-科技.mp4",
        "宣传片/2026-10-05 作者内容流水线/竖屏.mp4": "Movies/作者内容流水线/竖屏.mp4",
        "录音与会议/2026-10-05 张三 1005 咨询录音.m4a": "Downloads/张三 1005 咨询录音.m4a",
        "_收件箱/2026-10-05 随手录的.mov": "Downloads/随手录的.mov",
        "录音与会议/2026-10-05 Zinan的快速会议 155925747/meeting_01.mp4":
            "Documents/TencentMeeting/2026-10-05 13.54.48 Zinan的快速会议 155925747/meeting_01.mp4",
        "宣传片/2026-10-05 cs-promo/Content-Studio-4K.mp4": "work/cs-promo/out/Content-Studio-4K.mp4",
        "宣传片/2026-10-05 cs-promo/qa/层.mov": "work/cs-promo/out/qa/层.mov",
    }
    reasons = {p.name: why for p, why in skipped}
    assert "可能还在录" in reasons["正在导出.mp4"]
    assert "工程文件夹" in reasons["某工程"]
    assert len(skipped) == 2


def test_open_files_and_duplicates(tmp_path: Path, lib: Path) -> None:
    home = tmp_path / "home"
    busy = _file(home / "Downloads/录着呢.mov", "a")
    same = _file(home / "Downloads/宣传片 v6 手机版.mp4", "b")
    _file(lib / "宣传片/早就搬过的.mp4", "b")
    _file(lib / "_收件箱/2026-10-05 撞名.mp4", "old")
    _file(home / "Downloads/撞名.mp4", "new")

    moves, skipped = _plan(lib, home, open_files=lambda paths: {busy})
    assert [(p.name, why) for p, why in skipped] == [("录着呢.mov", "有程序正开着")]
    by_name = {m.source.name: m for m in moves}
    assert by_name["宣传片 v6 手机版.mp4"].duplicate_of == Path("宣传片/早就搬过的.mp4")
    assert by_name["撞名.mp4"].dest == Path("_收件箱/2026-10-05 撞名 2.mp4")
    assert same.exists()  # 只是列出来


def test_apply_copies_verifies_then_removes(tmp_path: Path, lib: Path) -> None:
    home = tmp_path / "home"
    a = _file(home / "Movies/作者内容流水线/横屏.mp4", "a")
    (home / "Movies/作者内容流水线/.DS_Store").write_bytes(b"x")
    b = _file(home / "work/cs-promo/out/qa/层.mov", "b")
    dup = _file(home / "Downloads/重复.mp4", "c")
    _file(lib / "宣传片/原来那份.mp4", "c")

    moves, _ = _plan(lib, home)
    done = videolib.apply(lib, moves, log=lambda line: None)
    assert done == {"moved": 2, "duplicate": 1, "failed": 0, "bytes": 2 * (MB + 10)}
    assert not a.exists() and not b.exists() and not dup.exists()
    assert (lib / "宣传片/2026-10-05 作者内容流水线/横屏.mp4").read_bytes()[:1] == b"a"
    assert (lib / "宣传片/2026-10-05 cs-promo/qa/层.mov").exists()
    assert not (home / "Movies/作者内容流水线").exists()  # 搬空的组目录删掉
    assert (home / "Movies").is_dir() and (home / "work/cs-promo/out").is_dir()  # 根留着
    assert not list(lib.rglob("*.copying"))
    records = [json.loads(line) for line in (lib / videolib.MANIFEST).read_text(encoding="utf-8").splitlines()]
    assert sorted(r["action"] for r in records) == ["duplicate", "moved", "moved"]
    assert all(len(r["sha256"]) == 64 and r["source"].startswith(str(home)) for r in records)


def test_apply_keeps_the_source_when_the_copy_does_not_match(tmp_path: Path, lib: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    src = _file(home / "Downloads/会议.mp4", "a")
    moves, _ = _plan(lib, home)
    real = videolib.sha256
    monkeypatch.setattr(videolib, "sha256", lambda p: "坏" if p.name.endswith(".copying") else real(p))
    done = videolib.apply(lib, moves, log=lambda line: None)
    assert done["failed"] == 1 and src.exists()
    assert not list(lib.rglob("*.mp4*"))


def test_describe_groups_by_folder(tmp_path: Path, lib: Path) -> None:
    home = tmp_path / "home"
    _file(home / "Movies/作者内容流水线/横屏.mp4", "a")
    _file(home / "Movies/作者内容流水线/竖屏.mp4", "b")
    moves, skipped = _plan(lib, home)
    text = "\n".join(videolib.describe(lib, moves, skipped, home=home))
    assert "要搬 2 个文件" in text
    assert "宣传片/2026-10-05 作者内容流水线/  ← ~/Movies/作者内容流水线（2 个，2 MB）" in text
