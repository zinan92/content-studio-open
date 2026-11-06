"""写作流程：每一步在每篇文章上跑没跑，状态从文章上存的字段推出来（10/12 作者：「我问了你才知道没跑过」）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.extras.xline import write_flow, x_daily

NOW = write_flow.current("newhash", 4)


def by_id(rows):
    return {r["id"]: r for r in rows}


def article(**more):
    return {"id": "d-A1", "long": True, "state": "pending", "prep": "ready", "prep_at": "2026-10-12T11:24:59+08:00",
            "flow_prep": {"skill": "skillv1"}, "qa": "ready", "qa_v": 4, "qa_rules": "newhash", "qa_at": "2026-10-12T12:01:00+08:00",
            "qa_complete": True, "qa_issues": [], "qa_changes": [{"kind": "错字"}], "qa_value_ok": True,
            "qa_value": {"痛点": {"ok": True}, "解法": {"ok": True}, "收藏": {"ok": True}}, **more}


def test_steps_list_every_step_in_fixed_order_and_say_which_ones_never_ran_alone() -> None:
    rows = write_flow.steps(article(), {**NOW, "skill": "skillv1"})
    assert [r["id"] for r in rows] == ["opening", "density", "scarcity", "ending", "style", "check-pain", "check-benefit", "check-resonance", "check-complete", "check-typo"]
    r = by_id(rows)
    assert r["style"]["status"] == "ran" and r["style"]["rules"] == "skillv1" and not r["style"]["stale"]
    # 开头、骨架、结尾的规则写在 skill 里，但整理时塞在同一个提示词里：照实说「没单独跑」
    assert {r[i]["status"] for i in ("opening", "density", "ending")} == {"bundled"}
    assert {r[i]["status"] for i in ("scarcity", "check-resonance")} == {"none"}
    assert r["check-typo"]["note"] == "改了 1 处" and r["check-complete"]["note"] == "完整" and r["check-pain"]["note"] == "过"


def test_incomplete_article_is_reported_with_the_first_issue() -> None:
    r = by_id(write_flow.steps(article(qa_complete=False, qa_issues=["末句有实质内容但未展开"]), NOW))
    assert r["check-complete"]["status"] == "ran" and r["check-complete"]["note"] == "不完整：末句有实质内容但未展开"


def test_value_gate_failure_names_the_failed_check() -> None:
    value = {"痛点": {"ok": False, "why": "没说清谁的问题"}, "解法": {"ok": True}, "收藏": {"ok": True}}
    r = by_id(write_flow.steps(article(qa_value=value, qa_value_ok=False), NOW))
    assert r["check-pain"]["note"].startswith("不过：痛点：没说清谁的问题") and r["check-benefit"]["note"] == "过"


def test_article_made_before_qa_existed_shows_never_ran_not_blank() -> None:
    old = {"id": "d-L5", "long": True, "state": "failed", "prep": "ready", "compiled": True}
    r = by_id(write_flow.steps(old, NOW))
    assert r["check-complete"]["status"] == "never" and "10/11" in r["check-complete"]["note"]
    assert r["style"]["status"] == "none" and "没有改写" in r["style"]["note"]  # 合集：没改写


def test_changed_rules_mark_the_step_stale_and_only_those() -> None:
    old_qa = article(qa_rules="oldhash")
    r = by_id(write_flow.steps(old_qa, {**NOW, "skill": "skillv2"}))
    assert [i for i, row in r.items() if row["stale"]] == ["style", "check-pain", "check-benefit", "check-complete", "check-typo"]
    older_version = by_id(write_flow.steps(article(qa_v=3), NOW))
    assert older_version["check-complete"]["stale"] is True and older_version["style"]["stale"] is False


def test_qa_that_failed_or_is_running_is_said_plainly() -> None:
    failed = by_id(write_flow.steps(article(qa="failed", qa_error="codex 超时"), NOW))["check-complete"]
    assert failed["status"] == "failed" and failed["note"] == "codex 超时"
    assert by_id(write_flow.steps(article(qa="running"), NOW))["check-typo"]["status"] == "running"


def test_short_posts_have_no_flow_and_attach_adds_stale_ids() -> None:
    assert write_flow.steps({"id": "s", "long": False, "state": "pending"}, NOW) == []
    post = article(qa_rules="oldhash")
    write_flow.attach(post, NOW)
    assert post["flow_stale"] == ["check-pain", "check-benefit", "check-complete", "check-typo"] and len(post["flow"]) == 10


def test_rerun_qa_requeues_the_check_without_touching_the_text(tmp_path: Path) -> None:
    p = tmp_path / "x_daily.json"
    key = "2026-10-12"
    with x_daily._LOCK:
        data = x_daily.load(p)
        data["days"][key] = {"posts": [{**article(), "text": "正文", "qa_changes": []},
                                       {**article(), "id": "sent", "state": "sent", "text": "已发"}]}
        x_daily.save(p, data)
    post = x_daily.rerun_qa(p, key, "d-A1")
    assert post["qa"] is None and post["text"] == "正文"
    with pytest.raises(x_daily.DailyError):
        x_daily.rerun_qa(p, key, "sent")


def day_with_value_article(p: Path, key: str = "2026-10-12", **more) -> None:
    with x_daily._LOCK:
        data = x_daily.load(p)
        data["days"][key] = {"posts": [{"id": f"{key}-A1", "long": True, "manual_publish": True, "from_pick": f"{key}-K1", "state": "pending",
                                        "prep": "ready", "text": "# 标题\n\n正文一段。\n\n最后就是复杂的工作流。", **more}],
                             "picks": [{"id": f"{key}-K1", "source_id": "s", "title": "t", "text": "x", "chars": 1, "choice": "article"}]}
        x_daily.save(p, data)


def qa_result(complete: bool, issues: list[str]) -> dict:
    return {"text": "# 标题\n\n正文一段。\n\n最后就是复杂的工作流。", "changes": [], "dropped": [], "complete": complete, "issues": issues,
            "value_ok": True, "value": {}, "value_issues": []}


def test_value_article_whose_ending_is_unfinished_is_swapped_out_when_the_manifest_says_so(tmp_path: Path) -> None:
    p, key = tmp_path / "x_daily.json", "2026-10-12"
    day_with_value_article(p)
    post = x_daily.apply_qa(p, key, f"{key}-A1", seen="# 标题\n\n正文一段。\n\n最后就是复杂的工作流。",
                            result=qa_result(False, ["末句有实质内容但未展开"]), complete_on_fail="swap-if-ending-unfinished")
    assert post["state"] == "rejected" and post["swapped"] and "结尾没写完" in post["swap_reason"]
    pick = x_daily.load(p)["days"][key]["picks"][0]
    assert pick["choice"] == "skip" and pick["auto"] is True  # 候选标成不发，下一篇会顶上


def test_incomplete_in_the_middle_or_warn_mode_only_marks_red(tmp_path: Path) -> None:
    p, key = tmp_path / "x_daily.json", "2026-10-12"
    day_with_value_article(p, text="# 标题\n\n正文一段，讲完了。")
    seen = "# 标题\n\n正文一段，讲完了。"
    res = {**qa_result(False, ["中间一段缺少衔接"]), "text": seen}
    assert x_daily.apply_qa(p, key, f"{key}-A1", seen=seen, result=res, complete_on_fail="swap-if-ending-unfinished")["state"] == "pending"
    day_with_value_article(p)
    seen = "# 标题\n\n正文一段。\n\n最后就是复杂的工作流。"
    assert x_daily.apply_qa(p, key, f"{key}-A1", seen=seen, result=qa_result(False, ["末句未展开"]), complete_on_fail="warn")["state"] == "pending"
    day_with_value_article(p)
    assert x_daily.apply_qa(p, key, f"{key}-A1", seen=seen, result=qa_result(False, ["中间缺衔接"]), complete_on_fail="swap")["state"] == "rejected"


def test_articles_made_one_call_per_step_keep_their_recorded_steps() -> None:
    post = article(flow_run={"flow": "流程1", "ids": ["opening", "style"], "steps": {
        "opening": {"status": "ran", "note": "去掉或换掉 3 字，新写 0 字", "version": "v1", "at": "2026-10-12T12:00:00+08:00"}}})
    r = by_id(write_flow.steps(post, {**NOW, "step_versions": {"opening": "v2"}}))
    assert r["opening"]["status"] == "ran" and r["opening"]["note"].startswith("去掉或换掉") and r["opening"]["stale"] is True
    assert r["density"]["status"] == "off"  # 这篇走的流程里没有这一步
