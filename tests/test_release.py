from __future__ import annotations

import json
import os
from pathlib import Path
import struct

from content_studio import release, video_project


def _png(path: Path, w: int, h: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00")


def _jpg(path: Path, w: int, h: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    path.write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")


def _mp4(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def test_the_real_shape_codex_delivered(tmp_path: Path) -> None:
    """9/22 那条视频：成片叫「9月22日-抖音上传版.mp4」，工作台只认 final/video.mp4，发布台一直说没有成片。"""
    _mp4(tmp_path / "final" / "9月22日-抖音上传版.mp4", 900)
    _mp4(tmp_path / "final" / "h3-proxy.mp4", 2000)  # 代理片更大也不该被选：名字里有「上传版」的优先
    _jpg(tmp_path / "final" / "9月22日-封面.jpg", 1440, 1080)
    _png(tmp_path / "final" / "covers" / "9月22日-竖封面.png", 1080, 1440)
    _png(tmp_path / "final" / "covers" / "subject-cutout.png", 900, 1600)  # 抠像是中间产物，不是封面
    (tmp_path / "final" / "发布文案.md").write_text(
        "# 抖音发布文案\n\n## 推荐标题\n\n产品越来越便宜，真正越来越贵的是信任\n\n"
        "## 备选标题\n\nAI 时代，自媒体博主为什么必须从卖课转向卖产品？\n\n"
        "## 简介\n\n当人人都能手搓产品，稀缺的就不再是做出来。\n\n#自媒体 #AI #产品\n\n## 上传文件\n\n- 视频：x.mp4\n",
        encoding="utf-8",
    )
    r = release.find_release(tmp_path)
    assert r["video"] == "final/9月22日-抖音上传版.mp4"
    assert r["covers"] == {"landscape": "final/9月22日-封面.jpg", "portrait": "final/covers/9月22日-竖封面.png", "wechat": None, "wide": None}
    assert r["copy"]["title"] == "产品越来越便宜，真正越来越贵的是信任"
    assert r["copy"]["alternatives"] == ["AI 时代，自媒体博主为什么必须从卖课转向卖产品？"]
    assert r["copy"]["body"] == "当人人都能手搓产品，稀缺的就不再是做出来。"
    assert r["copy"]["tags"] == ["自媒体", "AI", "产品"]


def test_without_hints_the_biggest_video_wins(tmp_path: Path) -> None:
    """没有提示词时取最大的：代理片、预览片都比母版小。"""
    _mp4(tmp_path / "final" / "a.mp4", 100)
    _mp4(tmp_path / "final" / "b.mp4", 500)
    assert release.find_video(tmp_path) == "final/b.mp4"
    assert release.find_video(tmp_path / "空的") is None


def test_old_fixed_paths_still_win(tmp_path: Path) -> None:
    _mp4(tmp_path / "final" / "video.mp4", 10)
    _mp4(tmp_path / "final" / "上传版.mp4", 999)
    assert release.find_video(tmp_path) == "final/video.mp4"
    legacy = tmp_path / "旧项目"
    _mp4(legacy / "final-video.mp4", 10)
    assert release.find_video(legacy) == "final-video.mp4"


def test_a_newer_cover_replaces_the_older_one(tmp_path: Path) -> None:
    """改过一版封面，旧的那张不该再被选中。"""
    old = tmp_path / "final" / "封面-旧.png"
    new = tmp_path / "final" / "covers" / "封面-新.png"
    _png(old, 1440, 1080)
    _png(new, 1440, 1080)
    os.utime(old, (1, 1_700_000_000))
    os.utime(new, (1, 1_700_000_500))
    assert release.find_covers(tmp_path)["landscape"] == "final/covers/封面-新.png"


def test_image_size_reads_png_and_jpeg_headers(tmp_path: Path) -> None:
    _png(tmp_path / "a.png", 1440, 1080)
    _jpg(tmp_path / "b.jpg", 1080, 1440)
    (tmp_path / "c.png").write_bytes(b"not an image")
    assert release.image_size(tmp_path / "a.png") == (1440, 1080)
    assert release.image_size(tmp_path / "b.jpg") == (1080, 1440)
    assert release.image_size(tmp_path / "c.png") is None


def test_inspect_shows_the_delivery_without_changing_step_14(tmp_path: Path) -> None:
    """只用于显示和发布：认 final/ 下真实交付的那个。Step 14 仍看 final/video.mp4 + QA + 终审。"""
    base = tmp_path / "2026-09-22_测试"
    base.mkdir()
    (base / "project.json").write_text(json.dumps({
        "presets": {"media": "m", "audio": "a", "caption_style": "c", "caption_layout": "l"},
        "step_status": {str(n): "pass" for n in range(2, 14)}, "approvals": {"hook": "ok", "visual_spec": "ok"},
    }), encoding="utf-8")
    _mp4(base / "final" / "9月22日-抖音上传版.mp4", 10)
    info = video_project.inspect(tmp_path, base.name)
    assert info["final_video"] == "final/9月22日-抖音上传版.mp4"
    assert info["release"]["video"] == "final/9月22日-抖音上传版.mp4"
    assert info["delivered"] is False  # 判据没放宽
