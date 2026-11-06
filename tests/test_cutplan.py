"""这次怎么剪（10/19 作者）：视频进来口播稿自动出；Hook / 动效由他自己勾，进度只列勾上的块。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from content_studio import cutplan, koubo
from test_topic_script import BODY, setup
from test_web import client  # noqa: F401  (fixture)
from test_x_line import client_factory  # noqa: F401  (fixture)

SRT = "1\n00:00:00,000 --> 00:00:09,000\n{}\n"
SPOKEN = BODY.replace("\n\n", "")


def project(root: Path, name: str, *, srt: str | None = None) -> Path:
    base = root / name
    base.mkdir(parents=True)
    (base / "粗剪-10月19日.mov").write_bytes(b"x" * 100)
    if srt is not None:
        (base / "subtitles").mkdir()
        (base / "subtitles" / "source.srt").write_text(SRT.format(srt), encoding="utf-8")
    return base


# -- 两个开关落到哪条路 -------------------------------------------------------------------------------

def test_two_switches_map_to_four_routes_and_bad_values_are_refused() -> None:
    assert [cutplan.route(cutplan.clean({"hook": h, "motion": m})) for h, m in
            ((False, False), (False, True), (True, True), (True, False))] == ["plain", "motion", "full", "hook"]
    assert cutplan.clean({"layout": "vertical-full-overlay", "junk": 1})["layout"] == "vertical-full-overlay"
    with pytest.raises(cutplan.CutPlanError):
        cutplan.clean({"hook": "yes"})
    with pytest.raises(cutplan.CutPlanError):
        cutplan.clean({"bgm": "loud"})


def test_projects_started_before_today_read_their_choice_from_the_project_itself() -> None:
    plan, locked = cutplan.from_project({"layout": "v2"}, None)
    assert locked and (plan["hook"], plan["motion"]) == (False, True)
    plan, locked = cutplan.from_project({"layout": "v2.6", "spec": {"hook": "yes", "layout": "split-4x3"}}, None)
    assert locked and (plan["hook"], plan["motion"]) == (True, True)
    plan, _ = cutplan.from_project({"layout": "v2.6", "spec": {}, "hook_skipped": True}, None)
    assert plan["hook"] is False
    assert cutplan.from_project({"layout": "legacy", "delivered": True}, None)[1] is True
    assert cutplan.from_project({"layout": "fresh"}, None) == (None, False)
    saved = {**cutplan.DEFAULT, "hook": True, "started": False}
    assert cutplan.from_project({"layout": "fresh"}, saved) == (cutplan.clean({"hook": True}), False)


def test_progress_lists_only_the_blocks_he_turned_on(tmp_path: Path) -> None:
    base = tmp_path / "p"
    base.mkdir()
    hook = cutplan.clean({"hook": True, "motion": False})
    rows = cutplan.blocks({"layout": "fresh"}, hook, base, has_srt=True)
    assert [(b["label"], b["state"]) for b in rows] == [("逐字稿", "done"), ("选 Hook", "current"), ("剪 Hook 片段", "todo"), ("成片", "todo")]
    plain = cutplan.blocks({"layout": "fresh"}, cutplan.clean({}), base, has_srt=False)
    assert [b["label"] for b in plain] == ["逐字稿", "成片"]
    steps = [{"step": n, "done": n <= 9} for n in range(1, 15)]
    full = cutplan.blocks({"layout": "v2.6", "steps": steps}, cutplan.clean({"hook": True, "motion": True}), base, has_srt=True)
    assert [(b["label"], b["state"]) for b in full] == [("逐字稿", "done"), ("Hook", "done"), ("动效", "current"), ("成片", "todo")]
    assert cutplan.blocks({"layout": "fresh"}, None, base, has_srt=True) == []
    # 10/20：成片在外面剪完放进来了，机器的 Hook 没走完——不再把 Hook 标成「现在这步」
    early = [{"step": n, "done": n <= 4} for n in range(1, 15)]
    outside = cutplan.blocks({"layout": "v2.6", "steps": early, "final_video": "final/video.mp4"}, cutplan.clean({"hook": True, "motion": True}), base, has_srt=True)
    assert [(b["label"], b["state"]) for b in outside] == [("逐字稿", "done"), ("Hook", "todo"), ("动效", "todo"), ("成片", "done")]


# -- 卡片接口 ----------------------------------------------------------------------------------------

def test_the_card_remembers_his_last_choice_starts_the_right_thing_and_then_locks(client, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    root = tmp_path / "projects"
    root.mkdir()
    client.put("/api/settings", json={"video_projects_root": str(root)})
    tid = client.post("/api/topics", json={"title": "不剪不加", "formats": "video"}).json()["id"]
    empty = client.get(f"/api/topics/{tid}/video-project/plan").json()
    assert empty["has_video"] is False and empty["locked"] is False and empty["plan"] == cutplan.DEFAULT

    base = project(root, "2026-10-19_不剪不加")
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    view = client.get(f"/api/topics/{tid}/video-project/plan").json()
    assert view["has_video"] and not view["chosen"] and not view["locked"]

    # 不剪不加：粗剪拷进 final/，卡锁住
    r = client.post(f"/api/topics/{tid}/video-project/plan/start", json={"hook": False, "motion": False})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] and r.json()["route"] == "plain" and (base / "final" / "粗剪-10月19日.mov").is_file()
    assert client.put(f"/api/topics/{tid}/video-project/plan", json={"hook": True}).status_code == 400

    # 只剪 Hook：下一条默认照上一次，开始后进度里有「选 Hook」「剪 Hook 片段」（切片在 test_hookcut）
    tid2 = client.post("/api/topics", json={"title": "只剪钩子", "formats": "video"}).json()["id"]
    base2 = project(root, "2026-10-19_只剪钩子")
    client.put(f"/api/topics/{tid2}/video-project", json={"name": base2.name})
    assert client.get(f"/api/topics/{tid2}/video-project/plan").json()["plan"]["hook"] is False
    assert client.put(f"/api/topics/{tid2}/video-project/plan", json={"hook": True}).json()["plan"]["hook"] is True
    assert client.app.state.store.settings()["cut_plan_default"]["hook"] is True
    hook = client.post(f"/api/topics/{tid2}/video-project/plan/start", json={}).json()
    assert hook["route"] == "hook" and hook["locked"] and "hook_command" not in hook
    assert [b["label"] for b in hook["blocks"]] == ["逐字稿", "选 Hook", "剪 Hook 片段", "成片"]

    # 只加动效：转成 park-video-v2 项目
    from content_studio.extras.motion import video_v2

    called: list[Path] = []
    monkeypatch.setattr(video_v2, "init", lambda b: called.append(b) or {"already": False})
    tid3 = client.post("/api/topics", json={"title": "只加动效", "formats": "video"}).json()["id"]
    base3 = project(root, "2026-10-19_只加动效")
    client.put(f"/api/topics/{tid3}/video-project", json={"name": base3.name})
    motion = client.post(f"/api/topics/{tid3}/video-project/plan/start", json={"hook": False, "motion": True}).json()
    assert called == [base3] and motion["route"] == "motion" and motion["locked"]


def test_backing_out_of_a_choice_unlocks_the_card(client, tmp_path: Path) -> None:  # noqa: F811
    root = tmp_path / "projects"
    root.mkdir()
    client.put("/api/settings", json={"video_projects_root": str(root)})
    tid = client.post("/api/topics", json={"title": "反悔", "formats": "video"}).json()["id"]
    base = project(root, "2026-10-19_反悔")
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    client.post(f"/api/topics/{tid}/video-project/plan/start", json={"hook": False, "motion": False})
    assert client.post(f"/api/topics/{tid}/video-project/back").status_code == 200
    view = client.get(f"/api/topics/{tid}/video-project/plan").json()
    assert view["locked"] is False and view["chosen"] is True


# -- 视频进来，口播稿自动出 -------------------------------------------------------------------------------

def wait_script(client, tid: int) -> dict:
    for _ in range(300):
        d = client.get(f"/api/topics/{tid}/script").json()
        if not d["running"] and d["script"]:
            return d
        time.sleep(0.03)
    raise AssertionError("口播稿没自动出")


def test_linking_a_video_with_subtitles_makes_the_script_from_his_spoken_words(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, topic, calls = setup(client_factory, tmp_path, monkeypatch)
    tid = topic["id"]
    root = tmp_path / "projects"
    root.mkdir()
    client.put("/api/settings", json={"video_projects_root": str(root)})
    base = project(root, "2026-10-19_闭环", srt=SPOKEN)
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    d = wait_script(client, tid)
    assert d["script"]["trk"]["source"] == "transcript" and d["script"]["trk"]["transcript_hash"]
    assert BODY.split("\n\n")[0] in d["script"]["text"]  # 原话，不重写
    before = len(calls)
    client.get(f"/api/topics/{tid}/script")
    time.sleep(0.1)
    assert len(calls) == before  # 同一版逐字稿不重做

    # 重录了一遍：换成这一次说的，上一版留备份
    (base / "subtitles" / "source.srt").write_text(SRT.format(SPOKEN + "这是重录时多说的一句话，用来区分两次。"), encoding="utf-8")
    client.get(f"/api/topics/{tid}/script")
    for _ in range(300):
        d = client.get(f"/api/topics/{tid}/script").json()
        if not d["running"] and "重录时多说" in (d["script"] or {}).get("text", ""):
            break
        time.sleep(0.03)
    assert "重录时多说" in d["script"]["text"]
    assert (tmp_path / "drafts" / f"topic-{tid}" / "script.md.bak").is_file()


def test_a_video_without_subtitles_is_transcribed_right_away_then_the_script_follows(client, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    monkeypatch.delenv("CONTENT_STUDIO_NO_AUTO_TRANSCRIBE", raising=False)
    root = tmp_path / "projects"
    root.mkdir()
    client.put("/api/settings", json={"video_projects_root": str(root)})
    tid = client.post("/api/topics", json={"title": "没带字幕", "formats": "video"}).json()["id"]
    base = project(root, "2026-10-19_没带字幕")

    def fake_transcribe(video: Path, b: Path, **_kw) -> Path:
        (b / "subtitles").mkdir(exist_ok=True)
        out = b / "subtitles" / "source.srt"
        out.write_text(SRT.format("你好"), encoding="utf-8")
        return out

    monkeypatch.setattr(koubo, "transcribe", fake_transcribe)
    monkeypatch.setattr(koubo, "build_worktable", lambda b, srt: b / "analysis" / "worktable.html")
    seen: list[int] = []
    client.app.state.topic_script_auto = lambda topic_id: seen.append(topic_id)
    client.app.state.topic_review_start = lambda topic_id: None
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    for thread in threading.enumerate():
        if thread.name == f"koubo-{tid}":
            thread.join(timeout=5)
    assert (base / "subtitles" / "source.srt").is_file() and seen == [tid]
