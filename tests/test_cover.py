from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import cover


def test_split_title_keeps_latin_words_whole() -> None:
    lines = cover.split_title("我终于理解了dontbesilent为什么开源dbskill！")
    assert "dontbesilent" in lines and "".join(lines) == "我终于理解了dontbesilent为什么开源dbskill！"
    assert all(cover.units(l) <= 8 for l in lines)


def test_generate_hands_codex_the_frame_refs_and_title_and_files_the_two_covers(tmp_path: Path, monkeypatch) -> None:
    """9/29：封面改由 Codex image_gen 出。这里给它一帧、两张风格参考、逐字标题；它交回两张，放进 final/covers/。"""
    skill = tmp_path / "skill"
    for rel in cover.STYLE_REFS.values():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_bytes(b"png")
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(skill))
    monkeypatch.setenv("CONTENT_STUDIO_PORTRAITS", str(tmp_path / "没有形象照"))
    base = tmp_path / "proj"
    (base / "final" / "covers").mkdir(parents=True)
    (base / "final" / "covers" / "旧-竖封面.jpg").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(cover, "_run", lambda args, what, timeout=120: calls.append(what) or (Path(args[-1]).write_bytes(b"jpg") if what in ("取帧", "垫 16:9") else ""))
    monkeypatch.setattr(cover, "_ratio_ok", lambda path, want: True)
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    seen = {}

    def runner(text: str, cwd: Path) -> None:
        # 10/2 起 image_gen 只画竖、横两张，16:9 由 ffmpeg 从横版垫出来
        seen["text"] = text
        seen["files"] = sorted(p.name for p in cwd.iterdir())
        (cwd / "out" / "cover-3x4.png").write_bytes(b"p")
        (cwd / "out" / "cover-4x3.png").write_bytes(b"l")

    made = cover.generate(base, tmp_path / "raw.mov", at=292.0, title="做自媒体没有大流量如何月入10个", runner=runner)
    assert "垫 16:9" in calls and "16:9" not in seen["text"]
    assert made == {"竖": "final/covers/做自媒体没有大流量如何月入10个-竖封面.png", "横": "final/covers/做自媒体没有大流量如何月入10个-横封面.png",
                    "YouTube": "final/covers/做自媒体没有大流量如何月入10个-YouTube封面.png"}
    assert seen["files"] == ["out", "person.jpg", "prompt.md", "style-3x4.png", "style-4x3.png"]
    assert "做自媒体没有大流量如何月入10个" in seen["text"] and "SOLE PERSON SOURCE" in seen["text"] and "STYLE REFERENCE ONLY" in seen["text"]
    assert (base / "final" / "covers" / "_old" / "旧-竖封面.jpg").is_file()


def test_cover_person_comes_only_from_the_video_frame_even_with_portraits_around(tmp_path: Path, monkeypatch) -> None:
    """10/2 作者：不要把视频那一帧和形象照拼在一起，拼出来像另一个人、竖横两张还不一样；只用视频本身那一帧。"""
    skill = tmp_path / "skill"
    for rel in cover.STYLE_REFS.values():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_bytes(b"png")
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(skill))
    looks = tmp_path / "形象照"
    looks.mkdir()
    for name in ("01 电梯间 正脸.jpg", "03 浴室 笑.jpg", "05 旧照 光膀子.jpg", "README.md"):
        (looks / name).write_bytes(b"x")
    monkeypatch.setenv("CONTENT_STUDIO_PORTRAITS", str(looks))
    monkeypatch.setattr(cover, "_run", lambda args, what, timeout=120: Path(args[-1]).write_bytes(b"jpg") if what in ("取帧", "垫 16:9") else "")
    monkeypatch.setattr(cover, "_ratio_ok", lambda path, want: True)
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    seen = {}

    def runner(text: str, cwd: Path) -> None:
        seen["text"], seen["files"] = text, sorted(p.name for p in cwd.iterdir())
        for name in ("cover-3x4.png", "cover-4x3.png"):
            (cwd / "out" / name).write_bytes(b"p")

    cover.generate(tmp_path / "proj", tmp_path / "raw.mov", at=1.0, title="明牌机会，AI时代普通人仅有的三条路", runner=runner)
    assert seen["files"] == ["out", "person.jpg", "prompt.md", "style-3x4.png", "style-4x3.png"]
    assert "SOLE PERSON SOURCE" in seen["text"] and "好看版" not in seen["text"] and "look-" not in seen["text"]
    assert "两张封面里是同一个人" in seen["text"]


def test_generate_says_so_when_a_cover_is_missing(tmp_path: Path, monkeypatch) -> None:
    skill = tmp_path / "skill"
    for rel in cover.STYLE_REFS.values():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_bytes(b"png")
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(skill))
    monkeypatch.setattr(cover, "_run", lambda args, what, timeout=120: "")
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    with pytest.raises(cover.CoverError, match="没出来"):
        cover.generate(tmp_path / "p", tmp_path / "v.mp4", at=1, title="标题", runner=lambda text, cwd: None)
    with pytest.raises(cover.CoverError, match="先写标题"):
        cover.generate(tmp_path / "p", tmp_path / "v.mp4", at=1, title=" ", runner=lambda text, cwd: None)


def test_pick_frames_keeps_the_best_faces_in_time_order(tmp_path: Path, monkeypatch) -> None:
    """9/29：画面机器挑。多取几帧，留人脸质量最好的几张（按时间排），分最高的标 pick；没脸/多张脸不算。"""
    frames = [{"at": float(i * 10), "path": tmp_path / f"f{i}.jpg"} for i in range(12)]
    monkeypatch.setattr(cover, "candidate_frames", lambda video, out_dir, count: frames[:count])
    scores = {f["path"]: s for f, s in zip(frames, [0.1, 0.9, -1, 0.5, 0.2, 0.8, 0.3, -1, 0.7, 0.4, 0.6, 0.05])}
    monkeypatch.setattr(cover, "score_frames", lambda paths: scores)
    kept = cover.pick_frames(tmp_path / "v.mp4", tmp_path, keep=6, sample=12)
    assert [f["at"] for f in kept] == [10.0, 30.0, 50.0, 80.0, 90.0, 100.0]
    assert [f["at"] for f in kept if f["pick"]] == [10.0]


def test_pick_frames_falls_back_to_the_middle_when_nothing_scores(tmp_path: Path, monkeypatch) -> None:
    frames = [{"at": float(i), "path": tmp_path / f"f{i}.jpg"} for i in range(12)]
    monkeypatch.setattr(cover, "candidate_frames", lambda video, out_dir, count: frames[:count])
    monkeypatch.setattr(cover, "score_frames", lambda paths: {p: -1.0 for p in paths})
    kept = cover.pick_frames(tmp_path / "v.mp4", tmp_path, keep=6, sample=12)
    assert len(kept) == 6 and sum(f["pick"] for f in kept) == 1


def test_long_phrase_breaks_between_words_and_keeps_punctuation_on_the_line() -> None:
    """9/29 以前「99%的自媒体人都在追求流量，」被硬切成「99%的自媒体 / 人都在追求流 / 量，」。"""
    title = "99%的自媒体人都在追求流量，但是变现和流量关系并不大"
    words = ["99", "%", "的", "自媒体", "人", "都", "在", "追求", "流量", "，", "但是", "变现", "和", "流量", "关系", "并", "不", "大"]
    breaks, i = set(), 0
    for w in words:
        i += len(w)
        breaks.add(i)
    assert cover.split_title(title, breaks=breaks) == ["99%的自媒体人", "都在追求流量，", "但是变现和", "流量关系并不大"]


def test_release_tells_16x9_from_4x3(tmp_path: Path) -> None:
    from content_studio import release

    covers = tmp_path / "final" / "covers"
    covers.mkdir(parents=True)
    (covers / "t-横封面.png").write_bytes(b"")
    (covers / "t-YouTube封面.png").write_bytes(b"")
    found = release.find_covers(tmp_path)
    assert found["wide"] == "final/covers/t-YouTube封面.png" and found["landscape"] == "final/covers/t-横封面.png"


def test_title_lines_keep_numbers_with_their_units_and_particles_off_the_line_start(monkeypatch) -> None:
    """10/2：「我是怎么聊一 / 个年入 200 / 万的老板的」——数字和量词、单位不拆；「了」「的」不打头。"""
    monkeypatch.setattr(cover, "word_breaks", lambda text: set(range(1, len(text))))
    for title in ("6000 粉丝，三天三单 2000 块的咨询：我是怎么聊一个年入 200 万的老板的", "只有6000粉丝，3个小时赚了大部分人一个月工资"):
        lines = cover.split_title(title)
        assert "".join(lines).replace(" ", "") == title.replace(" ", "")
        for a, b in zip(lines, lines[1:]):
            assert not (a[-1] in cover.NUMERAL and b[0] in cover.MEASURE), (a, b)
            assert b[0] not in cover.NO_LINE_START, (a, b)


def test_progress_counts_the_drawn_covers_that_landed(tmp_path: Path) -> None:
    assert cover.progress(tmp_path) == {"done": 0, "total": 2}
    out = tmp_path / cover.WORK / "out"
    out.mkdir(parents=True)
    (out / "cover-3x4.png").write_bytes(b"p")
    assert cover.progress(tmp_path) == {"done": 1, "total": 2}


def test_progress_note_says_it_is_finishing_once_both_are_drawn() -> None:
    """10/3 作者：「封面明明已经出好了，但是进度条一直在转」——两张画完到换上新封面还有约 1 分钟收尾。"""
    assert cover.progress_note({"done": 0, "total": 2}) == "出图中 · 竖版、横版好了 0/2"
    assert cover.progress_note({"done": 1, "total": 2}) == "出图中 · 竖版、横版好了 1/2"
    note = cover.progress_note({"done": 2, "total": 2})
    assert "收尾" in note and "2/2" not in note
