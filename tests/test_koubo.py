from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import koubo

from test_web import client  # noqa: F401  (fixture)


def _project(tmp_path: Path) -> Path:
    base = tmp_path / "2026-09-22_测试"
    (base / "subtitles").mkdir(parents=True)
    return base


def test_finds_the_biggest_video_and_ignores_intermediates(tmp_path: Path) -> None:
    """成片和只读备份常常并排放着；中间产物目录里也全是 mp4，不能当成片。"""
    base = _project(tmp_path)
    (base / "备份.mov").write_bytes(b"x" * 500)
    (base / "粗剪.mp4").write_bytes(b"x" * 9000)
    for skipped in ("part-a-hook", "final", "renders"):
        (base / skipped).mkdir()
        (base / skipped / "video.mp4").write_bytes(b"x" * 99999)
    assert koubo.find_video(base).name == "粗剪.mp4"
    (base / "说明.txt").write_bytes(b"x" * 99999)  # 不是视频，再大也不算
    assert koubo.find_video(base).name == "粗剪.mp4"
    empty = tmp_path / "空项目"
    empty.mkdir()
    assert koubo.find_video(empty) is None


def test_srt_at_the_fixed_path_wins_over_a_loose_one(tmp_path: Path) -> None:
    """剪映导出的 SRT 通常和视频并排；约定位置有了就用约定位置。"""
    base = _project(tmp_path)
    assert koubo.find_srt(base) is None
    (base / "剪映导出.srt").write_text("1\n", encoding="utf-8")
    loose = koubo.find_srt(base)
    assert loose.name == "剪映导出.srt"
    (base / "subtitles" / "source.srt").write_text("1\n", encoding="utf-8")
    assert koubo.find_srt(base) == base / "subtitles" / "source.srt"


def test_state_tells_the_frontend_which_button_to_show(tmp_path: Path) -> None:
    base = _project(tmp_path)
    assert koubo.state(base) == {"video": None, "srt": None, "sentences": False, "worktable": False, "exported": False}
    (base / "粗剪.mp4").write_bytes(b"x" * 2_097_152)
    s = koubo.state(base)
    assert s["video"] == {"name": "粗剪.mp4", "mb": 2.0} and s["srt"] is None
    (base / "subtitles" / "source.srt").write_text("1\n", encoding="utf-8")
    assert koubo.state(base)["srt"]["at_fixed_path"] is True
    (base / "analysis").mkdir()
    (base / "analysis" / "worktable.html").write_text("<html></html>", encoding="utf-8")
    assert koubo.state(base)["worktable"] is True and koubo.state(base)["exported"] is False


def test_build_worktable_says_which_script_is_missing(tmp_path: Path) -> None:
    base = _project(tmp_path)
    srt = base / "subtitles" / "source.srt"
    srt.write_text("1\n", encoding="utf-8")
    with pytest.raises(koubo.KouboError, match="找不到 park-video-v2"):
        koubo.build_worktable(base, srt=srt, skill=tmp_path / "没装")


def test_build_worktable_runs_the_skills_own_script(tmp_path: Path) -> None:
    """工作台不重写那张表——重写就和后面 14 步的格式对不上了。"""
    base = _project(tmp_path)
    srt = base / "subtitles" / "source.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好世界。\n", encoding="utf-8")
    skill = tmp_path / "skill" / "scripts"
    skill.mkdir(parents=True)
    fake_rows = json.dumps({"transcript": [
        {"id": f"s{i:03d}", "text": "一句话。", "start_hint": i * 4.0, "end_hint": i * 4.0 + 3.5} for i in range(1, 20)
    ]}, ensure_ascii=False)
    (skill / "build_worktable.py").write_text(
        "import sys, pathlib\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)\n"
        f"pathlib.Path(out).write_text({fake_rows!r} if out.endswith('.json') else '<html>x</html>', encoding='utf-8')\n",
        encoding="utf-8",
    )
    # 标点那一步平时走本机 claude；这里给个假的，测试不依赖这台机器装了什么。
    out = koubo.build_worktable(base, srt=srt, skill=tmp_path / "skill", write_fn=lambda prompt: "你好世界。")
    assert out == base / "analysis" / "worktable.html" and out.is_file()
    rows = json.loads((base / "subtitles" / "transcript.sentences.json").read_text(encoding="utf-8"))["transcript"]
    assert len(rows) == 19


def test_the_save_button_is_appended_not_woven_in(tmp_path: Path) -> None:
    """只依赖模板里的全局 payload()。它没了就退回原来的导出按钮，不把表搞坏。"""
    base = _project(tmp_path)
    (base / "analysis").mkdir()
    (base / "analysis" / "worktable.html").write_text("<html><body>原表</body></html>", encoding="utf-8")
    html = koubo.worktable_html(base, save_url="/api/topics/7/video-project/worktable")
    assert html.startswith("<html><body>原表</body></html>")
    assert "typeof payload !== 'function'" in html
    assert '"/api/topics/7/video-project/worktable"' in html
    assert "X-Content-Studio" in html
    with pytest.raises(koubo.KouboError, match="还没有生成工作台"):
        koubo.worktable_html(tmp_path / "别的", save_url="/x")


def test_latest_export_is_the_newest_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """剪映不往项目目录里导，文件名还全是日期。作者：「就拿最新的就好了，命名用来校对。」"""
    import os

    root = tmp_path / "剪映导出"
    root.mkdir()
    for name, age in (("9月7日.mp4", 300), ("9月22日.mp4", 10), ("9月17日(2).mp4", 100)):
        f = root / name
        f.write_bytes(b"x" * 1_048_576)
        os.utime(f, (0, 1_700_000_000 - age))
    # 带字幕导出时剪映建一个同名文件夹，mp4 和 srt 放在里面。
    folder = root / "8月19日"
    folder.mkdir()
    (folder / "8月19日.mp4").write_bytes(b"x" * 2_097_152)
    (folder / "8月19日.srt").write_text("1\n", encoding="utf-8")
    os.utime(folder / "8月19日.mp4", (0, 1_700_000_000 - 500))

    latest = koubo.latest_export(root)
    assert latest["name"] == "9月22日.mp4" and latest["mb"] == 1.0 and latest["srt"] is None
    assert koubo.latest_export(tmp_path / "没有这个目录") is None

    rows = koubo.recent_exports(root, durations=False)
    assert [r["name"] for r in rows] == ["9月22日.mp4", "9月17日(2).mp4", "9月7日.mp4", "8月19日.mp4"]
    assert rows[-1]["srt"] == "8月19日.srt" and rows[-1]["folder"] == "8月19日"


def test_an_export_saved_inside_the_last_export_folder_is_still_the_latest(tmp_path: Path) -> None:
    """10/7：剪映记着上次导到哪，新的一条落进了「10月5日/10月7日 (1)/」，只看一层就一直显示 10/5 那条。"""
    import os

    root = tmp_path / "剪映导出"
    old = root / "10月5日"
    old.mkdir(parents=True)
    (old / "10月5日.mov").write_bytes(b"x" * 3000)
    (old / "10月5日.srt").write_text("1\n", encoding="utf-8")
    (old / "10月5日 (1).mov").write_bytes(b"x" * 2000)  # 同一文件夹里后导的、没带字幕、还更小
    nested = old / "10月7日 (1)"
    nested.mkdir()
    (nested / "10月7日 (1).mov").write_bytes(b"x" * 1000)
    (nested / "10月7日 (1).srt").write_text("1\n", encoding="utf-8")
    for f, t in ((old / "10月5日.mov", 100), (old / "10月5日 (1).mov", 200), (nested / "10月7日 (1).mov", 300)):
        os.utime(f, (0, 1_700_000_000 + t))

    rows = koubo.recent_exports(root, durations=False)
    assert [(r["name"], r["srt"]) for r in rows] == [
        ("10月7日 (1).mov", "10月7日 (1).srt"), ("10月5日 (1).mov", None), ("10月5日.mov", "10月5日.srt")]
    assert rows[0]["folder"] == "10月7日 (1)"
    assert koubo.locate([(root, koubo.EXPORT_DEPTH)], "10月7日 (1).mov", 1000) == nested / "10月7日 (1).mov"
    assert koubo.locate([(root, koubo.EXPORT_DEPTH)], "10月7日 (1).mov", 999) is None


def test_dropping_the_export_folder_makes_links_and_fills_the_project(
        client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """拖进来只拿得到名字和大小：按这两样在剪映导出目录里找回原文件；还没项目就顺手建一个、关联上。"""
    root = tmp_path / "视频" / "exports"
    root.mkdir(parents=True)
    exports = tmp_path / "视频" / "剪映导出" / "10月5日" / "10月7日 (1)"
    exports.mkdir(parents=True)
    (exports / "10月7日 (1).mov").write_bytes(b"x" * 1000)
    (exports / "10月7日 (1).srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好。\n", encoding="utf-8")
    monkeypatch.delenv(koubo.EXPORTS_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "家"))
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "爆款拆解", "formats": "video"}).json()

    r = client.post(f"/api/topics/{topic['id']}/video-project/drop",
                    json={"files": [{"name": "10月7日 (1).mov", "size": 1000}, {"name": "10月7日 (1).srt", "size": 39}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] and body["video"] == "粗剪-10月7日 (1).mov" and body["srt"] == "subtitles/source.srt"
    linked = client.get(f"/api/topics/{topic['id']}/video-project").json()["name"]
    assert linked == body["created"]
    assert (root / linked / "粗剪-10月7日 (1).mov").stat().st_size == 1000

    miss = client.post(f"/api/topics/{topic['id']}/video-project/drop", json={"files": [{"name": "别的.mov", "size": 5}]})
    assert miss.status_code == 400 and "没找到 别的.mov" in miss.json()["error"]
    none = client.post(f"/api/topics/{topic['id']}/video-project/drop", json={"files": [{"name": "a.srt", "size": 5}]})
    assert none.status_code == 400 and "没有视频" in none.json()["error"]


def test_the_subtitle_landing_in_the_project_starts_the_post_shoot_review_but_never_breaks_the_drop(
        client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """10/13 作者：字幕一放进项目，拍后批注自动出；批注起不来也不能让「放进项目」失败。"""
    root = tmp_path / "视频" / "exports"
    root.mkdir(parents=True)
    exports = tmp_path / "视频" / "剪映导出" / "10月5日" / "10月7日 (1)"
    exports.mkdir(parents=True)
    (exports / "10月7日 (1).mov").write_bytes(b"x" * 1000)
    (exports / "10月7日 (1).srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好。\n", encoding="utf-8")
    monkeypatch.delenv(koubo.EXPORTS_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "家"))
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "爆款拆解", "formats": "video"}).json()
    started: list[int] = []

    def boom(topic_id: int) -> None:
        started.append(topic_id)
        raise RuntimeError("批注起不来")

    client.app.state.topic_review_start = boom
    with_srt = client.post(f"/api/topics/{topic['id']}/video-project/drop", json={"files": [{"name": "10月7日 (1).mov", "size": 1000}, {"name": "10月7日 (1).srt", "size": 39}]})
    assert with_srt.status_code == 200 and started == [topic["id"]]


def test_adopting_keeps_the_date_so_it_stays_traceable(tmp_path: Path) -> None:
    """项目里躺一个叫「粗剪.mp4」的东西，回头对不上是哪一次导的。"""
    root = tmp_path / "剪映导出"
    folder = root / "9月22日"
    folder.mkdir(parents=True)
    video = folder / "9月22日.mp4"
    video.write_bytes(b"x" * 1024)
    srt = folder / "9月22日.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好。\n", encoding="utf-8")

    base = tmp_path / "项目"
    out = koubo.adopt(video, base, srt=srt)
    assert out == {"video": "粗剪-9月22日.mp4", "srt": "subtitles/source.srt"}
    assert (base / "粗剪-9月22日.mp4").read_bytes() == b"x" * 1024
    assert (base / "subtitles" / "source.srt").is_file()
    assert koubo.find_video(base).name == "粗剪-9月22日.mp4"
    assert koubo.find_srt(base) == base / "subtitles" / "source.srt"

    with pytest.raises(koubo.KouboError, match="找不到这个文件"):
        koubo.adopt(root / "不存在.mp4", base)


def _sentences(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transcript": rows}, ensure_ascii=False), encoding="utf-8")


def test_a_transcript_with_no_punctuation_is_caught_not_shipped(tmp_path: Path) -> None:
    """真发生过：whisper 转中文不给标点，12 分钟被切成 1 句。

    build_worktable 靠标点断句，所以那张表看起来生成成功了，打开才发现是一整坨，
    没法标 Hook 也没法挂视觉标注。宁可当场报错。
    """
    bad = tmp_path / "bad.json"
    _sentences(bad, [{"id": "s001", "text": "有幸有一些博主朋友" * 60, "start_hint": 0.7, "end_hint": 713.0}])
    with pytest.raises(koubo.KouboError, match="断句失败"):
        koubo._guard_sentences(bad)

    good = tmp_path / "good.json"
    _sentences(good, [{"id": f"s{i:03d}", "text": "一句话。", "start_hint": i * 4.0, "end_hint": i * 4.0 + 3.5} for i in range(1, 180)])
    koubo._guard_sentences(good)  # 不该抛

    empty = tmp_path / "empty.json"
    _sentences(empty, [])
    with pytest.raises(koubo.KouboError, match="断句结果是空的"):
        koubo._guard_sentences(empty)

    missing = tmp_path / "没有这个.json"
    koubo._guard_sentences(missing)  # 读不到就别拦，真正的错误在别处报


def test_srt_text_drops_the_numbers_and_timecodes(tmp_path: Path) -> None:
    srt = tmp_path / "source.srt"
    srt.write_text(
        "1\n00:00:00,720 --> 00:00:03,200\n有幸有一些博主朋友\n\n"
        "2\n00:00:03,200 --> 00:00:06,120\n不管是卖课还是做咨询\n",
        encoding="utf-8",
    )
    assert koubo.srt_text(srt) == "有幸有一些博主朋友\n不管是卖课还是做咨询"


def test_punctuating_may_not_rewrite_a_single_character() -> None:
    """map 会核对补标点后的文字和 SRT 原文有没有漂移，改了字就出不了活。"""
    seen = {}

    def fake(prompt):
        seen["prompt"] = prompt
        return "有幸有一些博主朋友，不管是卖课还是做咨询。"

    out = koubo.punctuate("有幸有一些博主朋友\n不管是卖课还是做咨询", write_fn=fake)
    assert out == "有幸有一些博主朋友，不管是卖课还是做咨询。"
    assert "一个字都不许改" in seen["prompt"] and "不要删语气词和口误" in seen["prompt"]
    assert "有幸有一些博主朋友" in seen["prompt"]
    with pytest.raises(koubo.KouboError, match="没有返回内容"):
        koubo.punctuate("随便", write_fn=lambda p: "  ")


def test_a_useless_worktable_is_never_left_on_disk(tmp_path: Path) -> None:
    """守卫要在出 HTML 之前拦下来——反过来的话，一张没法用的表还是留在盘上。"""
    base = tmp_path / "项目"
    (base / "subtitles").mkdir(parents=True)
    srt = base / "subtitles" / "source.srt"
    srt.write_text("1\n00:00:00,000 --> 00:11:53,000\n一整坨没有标点的话\n", encoding="utf-8")
    (base / "subtitles" / "transcript.corrected.txt").write_text("一整坨没有标点的话\n", encoding="utf-8")
    skill = tmp_path / "skill" / "scripts"
    skill.mkdir(parents=True)
    blob = json.dumps({"transcript": [{"id": "s001", "text": "一整坨", "start_hint": 0.0, "end_hint": 713.0}]}, ensure_ascii=False)
    (skill / "build_worktable.py").write_text(
        "import sys, pathlib\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)\n"
        f"pathlib.Path(out).write_text({blob!r} if out.endswith('.json') else '<html>x</html>', encoding='utf-8')\n",
        encoding="utf-8",
    )
    with pytest.raises(koubo.KouboError, match="断句失败"):
        koubo.build_worktable(base, srt=srt, skill=tmp_path / "skill")
    assert not (base / "analysis" / "worktable.html").exists()


def test_project_json_unblocks_the_fourteen_steps(tmp_path: Path) -> None:
    """没有 project.json，工作台按「旧版目录」识别：进度算不出来，「开始跑」被拒，
    于是标完 Hook 之后没有任何一条路通向动效。"""
    skill = tmp_path / "skill"
    for folder, names in (("media", ["park-talking-head-4x3-v1"]), ("audio", ["park-voice-v1"]),
                          ("captions", ["park-caption-4x3-v1", "park-caption-layout-v1"])):
        (skill / "presets" / folder).mkdir(parents=True)
        for n in names:
            (skill / "presets" / folder / f"{n}.json").write_text("{}", encoding="utf-8")

    # caption_style 和 caption_layout 同在 captions/ 下，靠名字里的 layout 区分。
    assert koubo.default_presets(skill) == {
        "media": "park-talking-head-4x3-v1", "audio": "park-voice-v1",
        "caption_style": "park-caption-4x3-v1", "caption_layout": "park-caption-layout-v1",
    }

    base = tmp_path / "项目"
    base.mkdir()
    data = koubo.init_project(base, skill=skill)
    written = json.loads((base / "project.json").read_text(encoding="utf-8"))
    assert written == data and written["current_step"] == 1
    assert written["approvals"] == {"hook": None, "visual_spec": None, "final": None}
    assert written["presets"]["caption_layout"] == "park-caption-layout-v1"

    # 已经有了就不动——里面可能已经记了审批和证据。
    with pytest.raises(koubo.KouboError, match="不覆盖"):
        koubo.init_project(base, skill=skill)

    (skill / "presets" / "audio" / "park-voice-v1.json").unlink()
    with pytest.raises(koubo.KouboError, match="没有可用的 audio preset"):
        koubo.default_presets(skill)


def test_skipping_hook_is_written_into_the_contract(tmp_path: Path) -> None:
    """Hook 那四步的判据全是文件存在性，不写进 step_status 的话进度永远停在 Step 5。"""
    base = tmp_path / "项目"
    base.mkdir()
    with pytest.raises(koubo.KouboError, match="还没初始化"):
        koubo.skip_hook(base)

    (base / "project.json").write_text(json.dumps({
        "presets": {"media": "m"}, "step_status": {"2": "pass"}, "approvals": {"hook": None, "final": None},
    }, ensure_ascii=False), encoding="utf-8")
    assert koubo.skip_hook(base) == [5, 7, 8, 9]
    data = json.loads((base / "project.json").read_text(encoding="utf-8"))
    assert data["step_status"] == {"2": "pass", "5": "skipped", "7": "skipped", "8": "skipped", "9": "skipped"}
    assert data["approvals"]["hook"] == "skipped" and data["approvals"]["final"] is None
    assert data["presets"] == {"media": "m"}  # 别的字段一个不动


def _contract_project(tmp_path: Path) -> Path:
    base = tmp_path / "项目"
    base.mkdir()
    (base / "project.json").write_text(json.dumps({
        "presets": {"media": "m", "audio": "a", "caption_style": "c", "caption_layout": "l"},
        "step_status": {"2": "pass"}, "approvals": {"hook": None, "visual_spec": None, "final": None}}), encoding="utf-8")
    return base


def test_hook_made_elsewhere_counts_as_done(tmp_path: Path) -> None:
    """9/22 的 Hook 是 Codex 剪的：给出视频，5/7/8/9 记成 external，进度往后走。"""
    from content_studio import video_project

    base = _contract_project(tmp_path)
    with pytest.raises(koubo.KouboError, match="Hook 在哪"):
        koubo.mark_external(base, "hook")
    with pytest.raises(koubo.KouboError, match="不是视频"):
        koubo.mark_external(base, "hook", source=tmp_path / "nope.txt")
    clip = tmp_path / "hook.mp4"
    clip.write_bytes(b"0" * 32)
    koubo.mark_external(base, "hook", source=clip)
    data = json.loads((base / "project.json").read_text(encoding="utf-8"))
    assert (base / "part-a-hook" / "video.mp4").is_file()
    assert [data["step_status"][str(n)] for n in (5, 7, 8, 9)] == ["external"] * 4
    assert data["step_status"]["2"] == "pass" and data["approvals"]["hook"] == "external"
    (base / "subtitles").mkdir()
    for rel in ("subtitles/source.srt", "subtitles/transcript.sentences.json", "analysis/worktable.html"):
        (base / rel).parent.mkdir(exist_ok=True)
        (base / rel).write_text("x", encoding="utf-8")
    data["step_status"]["3"] = "pass"
    (base / "project.json").write_text(json.dumps(data), encoding="utf-8")
    info = video_project.inspect(tmp_path, "项目")
    assert info["current_step"] == 6  # Hook 这一段过了，停在内容地图
    assert "在外面做完了" in info["steps"][4]["evidence"]


def test_whole_video_made_elsewhere_goes_to_publish(tmp_path: Path) -> None:
    from content_studio import video_project

    base = _contract_project(tmp_path)
    with pytest.raises(koubo.KouboError, match="final/"):
        koubo.mark_external(base, "all")
    (base / "final").mkdir()
    (base / "final" / "9月22日-抖音上传版.mp4").write_bytes(b"0" * 32)
    koubo.mark_external(base, "all")
    info = video_project.inspect(tmp_path, "项目")
    assert info["delivered"] is True and info["current_step"] is None
    assert json.loads((base / "project.json").read_text(encoding="utf-8"))["step_status"]["2"] == "pass"  # 机器做过的不改写


def test_whole_video_made_elsewhere_without_project_json_uses_the_rough_cut(tmp_path: Path) -> None:
    # 10/5：新建的目录没有 project.json，点「整条在外面做完了」报「还没初始化」。粗剪就是成片。
    from content_studio import video_project

    base = tmp_path / "2026-10-05_新项目"
    base.mkdir()
    (base / "README.md").write_text("x", encoding="utf-8")
    with pytest.raises(koubo.KouboError, match="粗剪"):
        koubo.mark_external(base, "all")
    (base / "粗剪-10月5日.mov").write_bytes(b"0" * 32)
    koubo.mark_external(base, "all")
    assert (base / "final" / "粗剪-10月5日.mov").is_file() and not (base / "project.json").exists()
    info = video_project.inspect(tmp_path, base.name)
    assert info["delivered"] is True and info["final_video"] == "final/粗剪-10月5日.mov"
    assert video_project.safe_file(tmp_path.resolve(), base.name, info["final_video"]).name == "粗剪-10月5日.mov"


def test_visual_target_reaches_the_runner_prompt(tmp_path: Path) -> None:
    from content_studio.extras.motion import workflow_runner

    base = _contract_project(tmp_path)
    assert "动效占正文" not in workflow_runner.build_prompt(base)
    assert koubo.set_visual_target(base, 30) == 0.3
    prompt = workflow_runner.build_prompt(base)
    assert "作者 定为 30%" in prompt and "coverage_exception" not in prompt
    koubo.set_visual_target(base, 50)
    assert "coverage_exception：「作者 指定 50%」" in workflow_runner.build_prompt(base)
    with pytest.raises(koubo.KouboError):
        koubo.set_visual_target(base, 120)
