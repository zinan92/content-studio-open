from __future__ import annotations

import json
import os
from pathlib import Path

from content_studio import archive


def _fake_download(fail_on: set[str] | None = None, seconds: float = 100.0):
    calls: list[str] = []

    def fn(url: str, cookies: Path, out: Path) -> None:
        vid = url.rsplit("/", 1)[-1]
        calls.append(vid)
        if fail_on and vid in fail_on:
            raise RuntimeError("风控")
        media = out / "douyin" / "me" / vid / "media"
        media.mkdir(parents=True)
        (media / "video.mp4").write_bytes(b"x" * 10)

    return fn, calls


def probe_const(value: float):
    return lambda _p: value


def test_usable_root_needs_the_disk_to_be_there(tmp_path: Path) -> None:
    assert archive.usable_root("") is None
    assert archive.usable_root(str(tmp_path / "a" / "b")) is None
    assert archive.usable_root(str(tmp_path / "lib")).is_dir()
    assert archive.usable_root("/Volumes/没有这块盘-xyz/视频/作品库") is None


def test_local_original_is_linked_into_its_folder_and_nothing_is_downloaded(tmp_path: Path) -> None:
    lib, src = tmp_path / "lib", tmp_path / "videos"
    lib.mkdir()
    (src / "剪映导出").mkdir(parents=True)
    original = src / "剪映导出" / "9月17日.mp4"
    original.write_bytes(b"v" * (4 * 1024 * 1024))
    os.utime(original, (1789000000, 1789000000))  # 2026-09-10-ish
    video = {"video_id": "v1", "title": "看懂一件事 #标签", "published_at": "2026-09-12T10:00:00", "duration_seconds": 1278.7}
    fn, calls = _fake_download()
    r = archive.archive_pending([video], root=lib, cookie_path=tmp_path / "c", search=[src], download_fn=fn, probe=probe_const(1278.72))
    assert r["local"] == ["v1"] and calls == []
    final = archive.video_file(lib, "v1")
    assert final is not None and final.parent.name == archive.FINAL_DIR and os.path.samefile(final, original)
    assert final.name == final.parent.parent.name + ".mp4"  # 「日期 标题.mp4」，不带原来的「9月17日」
    assert archive.source_of(lib, "v1") == "local"
    assert "本机原片" in (final.parent.parent / "info.md").read_text(encoding="utf-8")


def test_downloads_are_checked_serial_and_two_failures_stop(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    vids = [{"video_id": f"v{i}", "title": f"第{i}条标题足够长的 描述", "published_at": f"2026-09-0{i}", "duration_seconds": 100.0} for i in range(1, 5)]
    fn, calls = _fake_download(fail_on={"v3", "v2"})
    r = archive.archive_pending(vids, root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(100.0), sleep=lambda _s: None, download=True)
    assert calls == ["v4", "v3", "v2"] and r["done"] == ["v4"] and r["stopped"]
    assert archive.is_download(archive.video_file(lib, "v4"))
    assert json.loads((lib / archive.INDEX_FILE).read_text(encoding="utf-8"))["v4"]["source"] == "douyin"
    assert not (lib / ".downloading" / "v3").exists()


def test_a_short_download_is_thrown_away(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    fn, _ = _fake_download()
    v = {"video_id": "long", "title": "很长的一条视频标题 x", "published_at": "2026-09-12", "duration_seconds": 758.7}
    r = archive.archive_pending([v], root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(30.0), download=True)
    assert r["done"] == [] and "只有 30 秒" in r["failed"][0]["error"]
    assert archive.video_file(lib, "long") is None


def test_no_root_means_nothing_happens(tmp_path: Path) -> None:
    fn, calls = _fake_download()
    r = archive.archive_pending([{"video_id": "a"}], root=None, cookie_path=tmp_path, download_fn=fn)
    assert calls == [] and r["skipped"]


def test_by_default_nothing_is_downloaded_missing_ones_are_listed(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    fn, calls = _fake_download()
    v = {"video_id": "gone", "title": "在另一台电脑上的一条 x", "published_at": "2026-03-01", "duration_seconds": 900.0}
    r = archive.archive_pending([v], root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(900.0))
    assert calls == [] and r["missing"] == ["gone"] and r["done"] == []


def _video_file(path: Path, size: int, when: int = 1772700000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"v" * size)
    os.utime(path, (when, when))  # 2026-03-05-ish
    return path


def test_one_file_goes_to_one_video_and_downloads_are_not_originals(tmp_path: Path) -> None:
    """9/27: two videos 1.2 s apart, and 3/3's Douyin download copied to two places on the NAS.
    It went into both folders as 「本机原片」. It is neither an original nor 3/1's."""
    lib, nas = tmp_path / "lib", tmp_path / "nas"
    lib.mkdir()
    size = 4 * 1024 * 1024
    _video_file(nas / "抖音下载版" / "7612963821522554158" / "media" / "video.mp4", size)
    _video_file(nas / "已匹配抖音作品" / "2026-03-03_明牌机会" / "1 成片" / "video.mp4", size)
    first = {"video_id": "7612227309759646986", "title": "测试哪个coding agent最听话 x", "published_at": "2026-03-01", "duration_seconds": 2298.6}
    third = {"video_id": "7612963821522554158", "title": "AI时代的明牌机会 但是大部分人", "published_at": "2026-03-03", "duration_seconds": 2299.8}
    r = archive.archive_pending([first, third], root=lib, cookie_path=tmp_path / "c", search=[nas], probe=probe_const(2299.83))
    assert archive.video_file(lib, first["video_id"]) is None and r["missing"] == [first["video_id"]]
    assert archive.video_file(lib, third["video_id"]).name == "2026-03-03 AI时代的明牌机会 抖音下载版.mp4"
    assert archive.source_of(lib, third["video_id"]) == "douyin"


def test_a_file_belongs_to_the_video_it_is_closest_to(tmp_path: Path) -> None:
    lib, src = tmp_path / "lib", tmp_path / "videos"
    lib.mkdir()
    _video_file(src / "导出" / "a.mp4", 4 * 1024 * 1024)
    near = {"video_id": "near", "title": "离得近的那条标题 x", "published_at": "2026-03-03", "duration_seconds": 2299.8}
    far = {"video_id": "far", "title": "离得远的那条标题 x", "published_at": "2026-03-01", "duration_seconds": 2298.6}
    archive.archive_pending([far, near], root=lib, cookie_path=tmp_path / "c", search=[src], probe=probe_const(2299.83))
    assert archive.video_file(lib, "near") is not None and archive.video_file(lib, "far") is None
    # a second run does not hand the same file to the other one
    archive.archive_pending([far, near], root=lib, cookie_path=tmp_path / "c", search=[src], probe=probe_const(2299.83))
    assert archive.video_file(lib, "far") is None


def test_an_original_replaces_a_douyin_download(tmp_path: Path) -> None:
    lib, src = tmp_path / "lib", tmp_path / "videos"
    lib.mkdir()
    v = {"video_id": "v9", "title": "AI越强，你越是在瞎努力 x", "published_at": "2026-03-08", "duration_seconds": 1047.1}
    fn, _ = _fake_download()
    archive.archive_pending([v], root=lib, cookie_path=tmp_path / "c", download_fn=fn, probe=probe_const(1047.13), download=True)
    assert archive.source_of(lib, "v9") == "douyin"
    _video_file(src / "final" / "AI时代如何避免无效努力.mp4", 5 * 1024 * 1024)
    r = archive.archive_pending([v], root=lib, cookie_path=tmp_path / "c", search=[src], probe=probe_const(1047.13))
    assert r["upgraded"] == ["v9"] and archive.source_of(lib, "v9") == "local"
    final = archive.video_file(lib, "v9")
    assert final.name == final.parent.parent.name + ".mp4"
    assert (final.parent / archive.download_name(final.parent.parent)).exists()


def test_node_modules_is_not_scanned(tmp_path: Path) -> None:
    lib, src = tmp_path / "lib", tmp_path / "videos"
    lib.mkdir()
    _video_file(src / "project" / "node_modules" / "pkg" / "clip.mp4", 4 * 1024 * 1024)
    assert archive.scan_local([src], root=lib, probe=probe_const(10.0)) == []


def test_folder_date_is_beijing_time() -> None:
    """库里存 UTC。9/12 00:01（北京）发的 FDE 存成 2026-09-11T16:01:11+00:00。"""
    v = {"video_id": "x", "title": "给每一个业务匹配一个 FDE 业务、流量", "published_at": "2026-09-11T16:01:11+00:00"}
    assert archive.folder_name(v).startswith("2026-09-12 ")
    assert archive.publish_day({"published_at": "2026-09-11T15:59:00+00:00"}) == "2026-09-11"
