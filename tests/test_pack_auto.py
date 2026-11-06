"""打包自动档：只定标题，剩下一步接一步做完、自动定稿；失败停下等重试；重启打断的再起一次。"""
from pathlib import Path

from content_studio import pack_auto


def ap(**made_or_locked: str) -> dict:
    """made_or_locked：key -> "made" / "locked" / "stale"（定过稿但改过了）。没写的 = 还没做。"""
    out = {}
    for key in ("copy", "cover", "article", "figs", "wx", "xhs"):
        s = made_or_locked.get(key)
        out[key] = {"made": s in ("made", "locked", "stale"), "approved": s in ("locked", "stale"), "valid": s == "locked"}
    return out


ARMED = {"armed": True, "title": "只有6000粉丝"}


def test_nothing_happens_until_park_sets_the_title() -> None:
    assert pack_auto.plan({}, ap(copy="locked"), set(), title="x", xhs=False) == []
    assert pack_auto.plan({"armed": False}, ap(copy="locked"), set(), title="x", xhs=False) == []


def test_armed_starts_cover_and_article_but_figs_wait_for_the_article() -> None:
    assert pack_auto.plan(ARMED, ap(copy="locked"), set(), title="只有6000粉丝", xhs=False) == [("start", "cover"), ("start", "article")]


def test_made_steps_are_auto_approved_and_the_next_one_starts_in_the_same_pass() -> None:
    actions = pack_auto.plan(ARMED, ap(copy="locked", cover="locked", article="made"), set(), title="只有6000粉丝", xhs=False)
    assert actions == [("approve", "article"), ("start", "figs")]


def test_an_approved_article_whose_subtitles_changed_is_rewritten_and_the_steps_after_it_wait() -> None:
    # 10/13：视频重录了，文章还是旧字幕写的。定过稿也不算数：重写，插图、排版等它。
    done = ap(copy="locked", cover="locked", article="locked", figs="locked", wx="locked")
    assert pack_auto.plan(ARMED, done, set(), title="只有6000粉丝", xhs=False) == []
    assert pack_auto.plan(ARMED, done, set(), title="只有6000粉丝", xhs=False, stale={"article"}) == [("start", "article")]
    rows = pack_auto.view(ARMED, done, set(), xhs=False, stale={"article": "视频重录过了，文章要重写"})
    assert {r["key"]: (r["state"], r["note"]) for r in rows}["article"] == ("waiting", "视频重录过了，文章要重写")


def test_running_steps_are_left_alone() -> None:
    assert pack_auto.plan(ARMED, ap(copy="locked"), {"cover", "article"}, title="只有6000粉丝", xhs=False) == []


def test_a_failed_step_waits_for_retry_instead_of_looping() -> None:
    state = {**ARMED, "steps": {"cover": {"state": "error", "error": "超时"}}}
    assert ("start", "cover") not in pack_auto.plan(state, ap(copy="locked"), set(), title="只有6000粉丝", xhs=False)


def test_a_step_cut_off_by_a_restart_is_restarted_once_then_given_up() -> None:
    once = {**ARMED, "steps": {"cover": {"state": "running", "tries": 1}}}
    assert ("interrupted", "cover") in pack_auto.plan(once, ap(copy="locked"), set(), title="只有6000粉丝", xhs=False)
    twice = {**ARMED, "steps": {"cover": {"state": "running", "tries": 2}}}
    assert ("give_up", "cover") in pack_auto.plan(twice, ap(copy="locked"), set(), title="只有6000粉丝", xhs=False)


def test_a_cover_made_for_an_old_title_is_redrawn_not_approved() -> None:
    state = {**ARMED, "steps": {"cover": {"state": "made", "title": "旧标题"}}}
    assert pack_auto.plan(state, ap(copy="locked", cover="stale"), set(), title="只有6000粉丝", xhs=False)[0] == ("start", "cover")
    same = {**ARMED, "steps": {"cover": {"state": "made", "title": "只有6000粉丝"}}}
    assert pack_auto.plan(same, ap(copy="locked", cover="made"), set(), title="只有6000粉丝", xhs=False)[0] == ("approve", "cover")


def test_xhs_only_when_xiaohongshu_is_set_to_cards() -> None:
    full = ap(copy="locked", cover="locked", article="locked", figs="locked", wx="locked")
    assert pack_auto.plan(ARMED, full, set(), title="只有6000粉丝", xhs=False) == []
    assert pack_auto.plan(ARMED, full, set(), title="只有6000粉丝", xhs=True) == [("start", "xhs")]


def test_state_survives_on_disk_and_retry_clears_the_error(tmp_path: Path) -> None:
    pack_auto.arm(tmp_path, "只有6000粉丝")
    pack_auto.mark(tmp_path, "cover", state="error", error="超时")
    assert pack_auto.load(tmp_path)["steps"]["cover"]["state"] == "error"
    pack_auto.retry(tmp_path, "cover")
    assert "cover" not in pack_auto.load(tmp_path)["steps"]
    pack_auto.mark(tmp_path, "figs", state="error", error="x")
    pack_auto.arm(tmp_path, "新标题")  # 换标题：之前失败的清掉重来
    assert "figs" not in pack_auto.load(tmp_path)["steps"]


def test_view_says_what_is_happening_for_each_step() -> None:
    state = {**ARMED, "steps": {"figs": {"state": "error", "error": "Codex 超时"}}}
    rows = {r["key"]: r for r in pack_auto.view(state, ap(copy="locked", cover="locked"), {"article"}, xhs=False)}
    assert rows["cover"]["state"] == "done" and rows["article"]["state"] == "running"
    assert rows["figs"]["state"] == "error" and rows["figs"]["note"] == "Codex 超时"
    assert rows["wx"]["state"] == "waiting"


def test_a_locked_step_being_redone_shows_as_running_and_a_failed_redo_is_said() -> None:
    """文章定稿了又在润色：显示在做（页面才会接着刷新）；润色没成：仍然算好了，但说一句。"""
    locked = ap(copy="locked", cover="locked", article="locked")
    rows = {r["key"]: r for r in pack_auto.view(ARMED, locked, {"article"}, xhs=False)}
    assert rows["article"]["state"] == "running"
    failed = {**ARMED, "steps": {"article": {"state": "error", "error": "图片行要原样保留"}}}
    rows = {r["key"]: r for r in pack_auto.view(failed, locked, set(), xhs=False)}
    assert rows["article"]["state"] == "done" and "图片行要原样保留" in rows["article"]["note"]
