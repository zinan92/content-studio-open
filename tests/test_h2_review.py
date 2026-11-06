from __future__ import annotations

import os
from pathlib import Path

import pytest

from content_studio import video_project


def test_the_standard_page_wins_then_the_newest(tmp_path: Path) -> None:
    a = tmp_path / "analysis"
    (a / "visual-preview" / "h2-final").mkdir(parents=True)
    loose = a / "h2-visual-review-final.html"
    loose.write_text("x", encoding="utf-8")
    assert video_project.find_h2_review(tmp_path) == "analysis/h2-visual-review-final.html"
    v1 = a / "visual-preview" / "review-v1.html"
    v2 = a / "visual-preview" / "h2-final" / "review-v2.html"
    v1.write_text("x", encoding="utf-8")
    v2.write_text("x", encoding="utf-8")
    os.utime(v1, (1, 1_700_000_000))
    os.utime(v2, (1, 1_700_000_500))
    assert video_project.find_h2_review(tmp_path) == "analysis/visual-preview/h2-final/review-v2.html"
    assert video_project.find_h2_review(tmp_path / "空") is None


def test_file_urls_are_rewritten_both_encoded_and_plain(tmp_path: Path) -> None:
    """Codex 那版审批页用的是绝对 file:// 地址，网页里会被浏览器拦掉，服务时要改写。"""
    base = tmp_path / "2026-09-22_9月22日"
    from urllib.parse import quote

    html = (f'<img src="file://{quote(str(base))}/analysis/a.png">'
            f'<video src="file://{base}/analysis/b.mp4"></video>'
            '<img src="file:///别的项目/c.png">')
    out = video_project.rewrite_local_urls(html, base, "/api/video-projects/p/raw/")
    assert '<img src="/api/video-projects/p/raw/analysis/a.png">' in out
    assert '<video src="/api/video-projects/p/raw/analysis/b.mp4">' in out
    assert "file:///别的项目/c.png" in out  # 项目外的地址不动


def test_raw_file_refuses_anything_outside_the_project(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    base = root / "2026-09-22_测试"
    (base / "analysis").mkdir(parents=True)
    (base / "analysis" / "ok.png").write_bytes(b"\x89PNG")
    (base / ".git").mkdir()
    (base / ".git" / "config").write_text("x", encoding="utf-8")
    (base / "analysis" / "secret.key").write_text("x", encoding="utf-8")
    (tmp_path / "outside.png").write_bytes(b"x")
    os.symlink(tmp_path / "outside.png", base / "analysis" / "link.png")

    assert video_project.raw_file(root, base.name, "analysis/ok.png") == (base / "analysis" / "ok.png").resolve()
    for bad in ("../outside.png", "analysis/../../outside.png", ".git/config", "analysis/secret.key",
                "analysis/link.png", "analysis/missing.png", ""):
        with pytest.raises(video_project.VideoProjectError):
            video_project.raw_file(root, base.name, bad)
