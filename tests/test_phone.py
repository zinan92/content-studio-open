from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from content_studio import phone


def test_one_file_when_it_fits() -> None:
    assert phone.plan_segments(726.4, 23.1) == [(0.0, 726.4)]


def test_split_evenly_with_headroom() -> None:
    segs = phone.plan_segments(600, 60)  # 60 MB / (28 × 0.9) → 3 段
    assert len(segs) == 3 and segs[0] == (0.0, 200.0) and segs[-1][1] == 600
    assert all(b > a for a, b in segs) and all(segs[i][1] == segs[i + 1][0] for i in range(len(segs) - 1))
    assert len(phone.plan_segments(600, 29)) == 2  # 超过 28 MB 就切，按 28×0.9 算段数
    with pytest.raises(phone.PhonePreviewError):
        phone.plan_segments(0, 10)


def test_part_names_carry_index_and_range() -> None:
    assert phone.part_name(2, 182.4, 363.0) == "02_03-02至06-03.mp4"
    assert phone.PART.match(phone.part_name(1, 0, 726.4))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def test_make_preview_splits_and_replaces_old_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "final.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1440x1080:rate=25", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", "12", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    out = tmp_path / "final" / phone.FOLDER
    out.mkdir(parents=True)
    (out / "01_00-00至09-99.mp4").write_bytes(b"old")
    (out / "别的文件.txt").write_text("留着", encoding="utf-8")

    one = phone.make_preview(tmp_path, video)
    assert [p["name"] for p in one] == ["01_00-00至00-12.mp4"] and one[0]["path"].startswith("final/")
    assert (out / "别的文件.txt").is_file() and not (out / ".压缩中.mp4").exists()

    size = one[0]["mb"]
    monkeypatch.setattr(phone, "CAP_MB", size / 2.2)
    parts = phone.make_preview(tmp_path, video)
    assert len(parts) >= 3 and parts[0]["name"].startswith("01_00-00至")
    assert all(p["mb"] <= size / 2.2 for p in parts)
    assert [p["name"] for p in phone.existing(tmp_path)] == [p["name"] for p in parts]
