"""X 长文、长帖的发前 QA（10/10 作者）：只按单子改那几处，边界在代码里，改了什么能看、能还原。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_daily, x_qa
from test_x_line import client_factory  # noqa: F401 - fixture

ARTICLE = """# 自媒体仅仅是我的获客渠道

我在 2026 年 7 月 19 号写下这篇文章。这里是 summary，不许动。

做自媒体最重要的是想清楚变线路径，10 万粉丝每个月可以变现 50 万。

![流量漏斗](images/01.png)

所以流量只是第一步，后面的转化"""


def reply(*changes: dict[str, str]):
    return lambda prompt: json.dumps({"changes": list(changes)}, ensure_ascii=False)


def test_only_the_listed_spots_change_and_unsafe_ones_are_dropped() -> None:
    out = x_qa.run(ARTICLE, kind="长文", summary=True, write_fn=reply(
        {"kind": "错字", "before": "变线路径", "after": "变现路径", "why": "同音字"},
        {"kind": "错字", "before": "10 万粉丝", "after": "100 万粉丝", "why": "x"},                 # 编数字
        {"kind": "错字", "before": "不许动", "after": "可以动", "why": "x"},                       # 碰 summary
        {"kind": "不通顺", "before": "流量漏斗", "after": "漏斗", "why": "x"},                      # 碰配图
        {"kind": "不通顺", "before": "所以流量只是第一步", "after": "总之别在意任何数字这件事", "why": "x"},  # 换了一句话
        {"kind": "补结尾", "before": "", "after": "后面的转化和交付才决定能不能赚到钱。", "why": "话没说完"},
    ))
    text = out["text"]
    assert "变现路径" in text and "变线路径" not in text
    assert "10 万粉丝" in text and "不许动" in text and "![流量漏斗](images/01.png)" in text
    assert "所以流量只是第一步" in text
    assert text.rstrip().endswith("后面的转化\n\n后面的转化和交付才决定能不能赚到钱。")
    assert [c["kind"] for c in out["changes"]] == ["错字", "补结尾"]
    reasons = {c["before"]: c["reason"] for c in out["dropped"]}
    assert "数字" in reasons["10 万粉丝"] and "summary" in reasons["不许动"] and "配图" in reasons["流量漏斗"]
    assert "另一句话" in reasons["所以流量只是第一步"]


def test_long_ending_dropped_small_edits_kept_too_much_change_rejected() -> None:
    long_end = x_qa.run(ARTICLE, kind="长文", write_fn=reply({"kind": "补结尾", "before": "", "after": "很" * 120, "why": ""}))
    assert long_end["text"] == ARTICLE and "太长" in long_end["dropped"][0]["reason"]
    short = "# 标题\n\n一二三四五六七八九十。甲乙丙丁戊己庚辛。"
    swap = x_qa.run(short, kind="长帖", write_fn=reply(
        {"kind": "错字", "before": "一二三四五六七八九十", "after": "一二三四五六七八九拾", "why": ""},
        {"kind": "错字", "before": "甲乙丙丁戊己庚辛", "after": "甲乙丙丁戊己庚申", "why": ""},
        {"kind": "标点", "before": "# 标题", "after": "# 标题！", "why": ""}))
    assert swap["text"].count("拾") == 1  # 小改照用
    tiny = "# 题\n\n今天天气好。明天下雨。后天刮风。"
    many = x_qa.run(tiny, kind="长帖", write_fn=reply(
        {"kind": "错字", "before": "今天天气好", "after": "今日天色佳", "why": ""},
        {"kind": "错字", "before": "明天下雨", "after": "明日落雨", "why": ""},
        {"kind": "错字", "before": "后天刮风", "after": "后日起风", "why": ""}))
    assert many["text"] == tiny and not many["changes"] and all("整份不用" in c["reason"] for c in many["dropped"])
    with pytest.raises(x_qa.QAError):
        x_qa.run(short, kind="长帖", write_fn=lambda p: "没问题")


def test_ending_goes_before_trailing_images() -> None:
    text = "# 题\n\n第一段\n\n话说到一半\n\n![图](images/02.png)\n"
    out = x_qa.run(text, kind="长文", write_fn=reply({"kind": "补结尾", "before": "", "after": "收尾一句。", "why": ""}))
    assert out["text"] == "# 题\n\n第一段\n\n话说到一半\n\n收尾一句。\n\n![图](images/02.png)\n"


def test_qa_runs_on_pending_items_shows_changes_skips_edited_and_reverts(client_factory, tmp_path: Path,  # noqa: F811
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    model = reply({"kind": "错字", "before": "变线路径", "after": "变现路径", "why": "同音字"})
    client: TestClient = client_factory(write_fn=model, x_fetch_fn=lambda url: [] if "manifest" in url else {})
    key = x_daily.day_key(x_daily.now_bj())
    post = "# 长帖\n\n想清楚变线路径再做。"
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [
        {"id": f"{key}-A", "long": True, "format": "post", "prep": "ready", "state": "approved", "text": post},
        {"id": f"{key}-P", "long": True, "format": "post", "prep": "ready", "state": "pending", "text": post},
        {"id": f"{key}-L", "long": True, "prep": "running", "state": "pending", "text": ARTICLE}],
        "planned_at": "x", "long_planned_at": "x", "long_target": [5, 5], "halted": None}}})

    job = x_daily.qa_next(x_daily.path())
    assert job[1]["id"] == f"{key}-A"  # 勾过没发的也过 QA；没做好的继续等
    client.app.state.x_long_qa(*job)
    job = x_daily.qa_next(x_daily.path())
    assert job[1]["id"] == f"{key}-P"
    client.app.state.x_long_qa(*job)
    got = {x["id"]: x for x in client.get("/api/xline/daily").json()["today"]["posts"]}
    assert got[f"{key}-P"]["text"] == "# 长帖\n\n想清楚变现路径再做。"
    assert got[f"{key}-P"]["qa"] == "ready" and got[f"{key}-P"]["qa_before"] == post
    assert got[f"{key}-P"]["qa_changes"][0]["after"] == "变现路径"
    assert got[f"{key}-A"]["state"] == "pending"
    assert got[f"{key}-A"]["qa_note"] == "QA 改过，你再看一眼再勾"
    assert x_daily.qa_next(x_daily.path()) is None

    r = client.post(f"/api/xline/daily/{key}/{key}-P/qa/revert")
    assert r.status_code == 200 and r.json()["post"]["text"] == post and r.json()["post"]["qa"] == "reverted"
    assert client.post(f"/api/xline/daily/{key}/{key}-P/qa/revert").status_code == 400
    assert x_daily.qa_next(x_daily.path()) is None  # 还原了不再自动 QA

    # 他在 QA 做的时候改了字：QA 不写回去
    x_daily.set_post(x_daily.path(), key, f"{key}-L", prep="ready")
    seen = x_daily.qa_next(x_daily.path())[1]["text"]
    client.patch(f"/api/xline/daily/{key}/{key}-L", json={"text": ARTICLE + "\n\n我自己补的。"})
    done = x_daily.apply_qa(x_daily.path(), key, f"{key}-L", seen=seen, result={"text": "别的", "changes": [], "dropped": []})
    assert done["qa"] == "skipped" and done["text"].rstrip().endswith("我自己补的。")

    # QA 出错不挡发：原文照旧
    x_daily.set_post(x_daily.path(), key, f"{key}-L", qa=None)
    failing = client_factory(write_fn=lambda p: "乱写", x_fetch_fn=lambda url: [] if "manifest" in url else {})
    failing.app.state.x_long_qa(*x_daily.qa_next(x_daily.path()))
    after = next(x for x in x_daily.load(x_daily.path())["days"][key]["posts"] if x["id"] == f"{key}-L")
    assert after["qa"] == "failed" and "格式" in after["qa_error"] and after["text"].rstrip().endswith("我自己补的。")


def reply_with_intro(intro: dict | None, *changes: dict[str, str]):
    return lambda prompt: json.dumps({"intro": intro, "changes": list(changes)}, ensure_ascii=False)


PROMPT_POST = "# 小闭环先闭，大闭环后闭\n\n我们用这个 thread 来记录整个框架的搭建，我需要你把我设想中的框架帮我画出来。\n\n第一，人生是不断建造闭环的过程。"


def test_intro_tells_readers_what_this_is_and_goes_under_the_title_or_after_the_summary() -> None:
    """10/10 晚 作者：给 agent 的 prompt 直接发，读者不知所云——开头要直说这是什么。"""
    intro = {"kind": "prompt", "text": "下面是我给 agent 写的一段 prompt，让它帮我搭个人第二脑的框架，大家可以参考。"}
    out = x_qa.run(PROMPT_POST, kind="长帖", write_fn=reply_with_intro(intro))
    blocks = out["text"].split("\n\n")
    assert blocks[0] == "# 小闭环先闭，大闭环后闭" and blocks[1] == intro["text"] and out["intro"] == intro["text"]
    assert out["changes"][0]["kind"] == "导语"
    plain = x_qa.run(PROMPT_POST.removeprefix("# "), kind="长帖", write_fn=reply_with_intro(intro))  # 长帖的标题没有 #
    assert plain["text"].split("\n\n")[:2] == ["小闭环先闭，大闭环后闭", intro["text"]]
    with_summary = x_qa.run(ARTICLE, kind="长文", summary=True, write_fn=reply_with_intro({"kind": "思考", "text": "这是我对自媒体变现的一段思考。"}))
    assert with_summary["text"].split("\n\n")[2] == "这是我对自媒体变现的一段思考。"  # summary 还在第二段

    for bad, why in ((" 你们怎么看？这是我的 prompt", "提问"), ("这是 作者 的 prompt，大家参考", "第一人称"),
                     ("这是我 30 天总结的 prompt", "数字"), ("我" * 120, "长度")):
        r = x_qa.run(PROMPT_POST, kind="长帖", write_fn=reply_with_intro({"kind": "prompt", "text": bad}))
        assert r["text"] == PROMPT_POST and r["intro"] is None and why in r["dropped"][-1]["reason"]
    assert x_qa.run(PROMPT_POST, kind="长帖", write_fn=reply_with_intro(intro), has_intro=True)["text"] == PROMPT_POST


def test_posts_qad_by_the_old_rules_get_a_second_pass_that_keeps_his_original(client_factory, tmp_path: Path,  # noqa: F811
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    intro = {"kind": "prompt", "text": "下面是我给 agent 写的一段 prompt，大家可以参考。"}
    client: TestClient = client_factory(write_fn=reply_with_intro(intro), x_fetch_fn=lambda url: [] if "manifest" in url else {})
    key = x_daily.day_key(x_daily.now_bj())
    original = PROMPT_POST.replace("搭建", "搭见")
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [
        {"id": f"{key}-P", "long": True, "format": "post", "prep": "ready", "state": "pending", "text": PROMPT_POST,
         "qa": "ready", "qa_before": original, "qa_changes": [{"kind": "错字", "before": "搭见", "after": "搭建", "why": ""}]},
        {"id": f"{key}-A", "long": True, "format": "post", "prep": "ready", "state": "approved", "text": PROMPT_POST, "qa": "ready"}],
        "planned_at": "x", "long_planned_at": "x", "long_target": [5, 5], "halted": None}}})
    job = x_daily.qa_next(x_daily.path(), qa_version=x_qa.VERSION)
    assert job[1]["id"] == f"{key}-P"  # 保持队列顺序
    client.app.state.x_long_qa(*job)
    post = next(x for x in client.get("/api/xline/daily").json()["today"]["posts"] if x["id"] == f"{key}-P")
    assert post["qa_v"] == x_qa.VERSION and post["intro"] == intro["text"] and post["qa_before"] == original
    assert [c["kind"] for c in post["qa_changes"]] == ["错字", "导语"]
    approved_job = x_daily.qa_next(x_daily.path(), qa_version=x_qa.VERSION)
    assert approved_job[1]["id"] == f"{key}-A"
    client.app.state.x_long_qa(*approved_job)
    assert x_daily.qa_next(x_daily.path(), qa_version=x_qa.VERSION) is None
    reverted = client.post(f"/api/xline/daily/{key}/{key}-P/qa/revert").json()["post"]
    assert reverted["text"] == original and not reverted.get("intro")


def model_result(**data):
    return lambda prompt: json.dumps({"changes": [], **data}, ensure_ascii=False)


def test_numbered_article_paragraphs_preserve_literal_prefix_and_inline_styles() -> None:
    from content_studio.extras.xline import x_article

    title, items = x_article.parse_markdown("# T\n\n1. a\n\n![x](i.png)\n\n2. **b**\n\n- bullet")
    assert title == "T"
    assert [item["type"] for item in items] == ["unstyled", "image", "unstyled", "unordered-list-item"]
    assert [item["text"] for item in items if item["type"] == "unstyled"] == ["1. a", "2. b"]
    assert items[2]["styles"] == [{"offset": 3, "length": 1, "style": "bold"}]


def test_compilation_keeps_consecutive_segments_without_numbering() -> None:
    post = x_daily.as_compilation({"text": "标题\n\n第一段原话。\n\n第二段原话。"})
    assert post["text"] == "# 标题\n\n第一段原话。\n\n第二段原话。"


@pytest.mark.parametrize("title", ["# 1. T", "1. T"])
@pytest.mark.parametrize("mode, expected", [("remove", ["a", "b", "c"]), ("renumber", ["1. a", "2. b", "3. c"])])
def test_numbering_is_applied_by_code_without_touching_title_summary_or_images(title, mode, expected) -> None:
    text = f"{title}\n\n8. summary\n\n1. a\n\n![1. x](1.png)\n\n1) b\n\n2、 c\n"
    out = x_qa.run(text, kind="长文", summary=True, write_fn=model_result(numbering=mode))
    assert out["text"] == f"{title}\n\n8. summary\n\n{expected[0]}\n\n![1. x](1.png)\n\n{expected[1]}\n\n{expected[2]}\n"
    assert out["changes"] == [{"kind": "编号", "before": "", "after": "去掉编号" if mode == "remove" else "重新编号",
                                "why": "让编号符合整篇结构并保持连续"}]
    assert x_qa.run(text, kind="长文", write_fn=model_result())["text"] == text


def deletion(before, after=""):
    return {"kind": "删", "before": before, "after": after, "why": "读者看不到视频"}


def test_delete_filler_cleans_whitespace_preserves_protected_text_and_other_edits() -> None:
    filler = "接下来给大家放一下我这个产品，放这个视频。"
    body = "这是我自己需要的功能，我做出来以后每天都在用。" * 10
    text = f"# 标题\n\nsummary  保留双空格\n\n{filler}\n\n正文  口水  继续。变线路径。{body}\n\n![图](i.png)\n"
    out = x_qa.run(text, kind="长文", summary=True, write_fn=reply(
        deletion(filler), deletion("口水"), {"kind": "错字", "before": "变线路径", "after": "变现路径", "why": "同音字"}))
    assert out["text"] == f"# 标题\n\nsummary  保留双空格\n\n正文 继续。变现路径。{body}\n\n![图](i.png)\n"
    assert len(out["changes"]) == 3 and not out["dropped"]


@pytest.mark.parametrize("before, after, reason", [
    ("重复", "别的话", "必须是空"), ("重复", " ", "必须是空"), ("重复", None, "必须是空"), ("长" * 121, "", "字太多"),
    ("重复", "", "不止一处"), ("保护摘要", "", "summary"), ("图片", "", "配图"),
    ("不存在", "", "找不到"), ("跨\n行", "", "跨段"),
])
def test_deletion_rejects_invalid_spans(before, after, reason) -> None:
    text = "# 标题\n\n保护摘要\n\n重复和重复。跨\n行。" + "长" * 121 + "\n\n![图片](i.png)"
    out = x_qa.run(text, kind="长文", summary=True, write_fn=reply(deletion(before, after)))
    assert out["text"] == text and not out["changes"]
    assert reason in out["dropped"][0]["reason"]


def test_deletions_over_fifteen_percent_are_all_dropped_but_typo_is_kept() -> None:
    text = "# 标题\n\n屏幕这边和视频那边。变线路径。这里还有一点内容。"
    out = x_qa.run(text, kind="长文", write_fn=reply(deletion("屏幕这边"), deletion("视频那边"),
        {"kind": "错字", "before": "变线路径", "after": "变现路径", "why": "同音字"}))
    assert out["text"] == text.replace("变线路径", "变现路径")
    assert [c["kind"] for c in out["changes"]] == ["错字"]
    assert len(out["dropped"]) == 2 and all(c["reason"] == "删得太多" for c in out["dropped"])


def test_deletion_budget_and_body_similarity_are_independent() -> None:
    text = "# 题\n\n" + "甲" * 12 + "。一二三四五六" + "乙" * 77
    out = x_qa.run(text, kind="长文", write_fn=reply(deletion("甲" * 12)))
    assert out["text"] == text.replace("甲" * 12, "") and not out["dropped"]
    combined = x_qa.run(text, kind="长文", write_fn=reply(deletion("甲" * 12),
        {"kind": "错字", "before": "一二三四五六", "after": "壹贰叁肆伍陆", "why": ""}))
    assert combined["text"] == text.replace("甲" * 12, "").replace("一二三四五六", "壹贰叁肆伍陆")
    assert not combined["dropped"]  # 删除不计入相似度，其余小改仍在阈值内
    text = "# 题\n\n删掉。" + "甲" * 40 + "。" + "乙" * 40
    bad = x_qa.run(text, kind="长文", write_fn=reply(deletion("删掉。"),
        {"kind": "错字", "before": "甲" * 40, "after": "丙" * 40, "why": ""}))
    assert bad["text"] == text and all("整份不用" in c["reason"] for c in bad["dropped"])


def test_completeness_defaults_and_bounded_issues() -> None:
    default = x_qa.run(ARTICLE, kind="长文", write_fn=model_result())
    assert default["complete"] is True and default["issues"] == []
    out = x_qa.run(ARTICLE, kind="长文", write_fn=model_result(complete=False, issues=["没有开头", "长" * 100, None, *["缺递进"] * 8]))
    assert out["complete"] is False and out["issues"] == ["没有开头", "长" * 80, "缺递进", "缺递进", "缺递进"]
    assert "## 完整度：站在陌生读者的角度" in x_qa.prompt(ARTICLE, kind="长文")


@pytest.mark.parametrize("changed, complete, state, note", [
    (True, True, "pending", "QA 改过，你再看一眼再勾"),
    (False, True, "approved", None),
    (False, False, "pending", "QA 觉得还不完整，你看一眼再决定"),
    (True, False, "pending", "QA 觉得还不完整，你看一眼再决定"),
])
def test_approved_old_qa_is_picked_and_needs_review_only_when_necessary(tmp_path, changed, complete, state, note) -> None:
    from datetime import datetime
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    p, key = tmp_path / "daily.json", "2026-10-11"
    post = {"id": "p", "long": True, "prep": "ready", "state": "approved", "text": ARTICLE, "qa": "ready", "qa_v": 2, "decided_at": "old"}
    x_daily.save(p, {"days": {key: {"posts": [post]}}})
    assert x_daily.qa_next(p, now, qa_version=3) == (key, post)
    result = {"text": ARTICLE + "。" if changed else ARTICLE, "changes": [], "dropped": [], "complete": complete,
              "issues": [] if complete else ["没有结尾"]}
    got = x_daily.apply_qa(p, key, "p", seen=ARTICLE, result=result)
    assert got["state"] == state and got.get("qa_note") == note
    assert got["qa_complete"] is complete and got["qa_issues"] == result["issues"] and got["qa_v"] == x_qa.VERSION
    assert got["decided_at"] == ("old" if state == "approved" else None)
    assert x_daily.qa_next(p, now, qa_version=3) is None
    if changed:
        restored = x_daily.revert_qa(p, key, "p")
        assert restored["text"] == ARTICLE and not any(k in restored for k in ("qa_complete", "qa_issues", "qa_note"))


def test_queue_day_order_and_versioned_skip_after_concurrent_edit(tmp_path) -> None:
    from datetime import datetime
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    p, key = tmp_path / "daily.json", "2026-10-11"
    base = {"long": True, "prep": "ready", "state": "approved", "text": ARTICLE, "qa": "skipped", "qa_v": 2}
    posts = [{**base, "id": state, "state": state} for state in ("sent", "sending", "rejected")]
    posts += [{**base, "id": "swapped", "swapped": True}, {**base, "id": "preparing", "prep": "running"}, {**base, "id": "today"}]
    x_daily.save(p, {"days": {"2026-10-12": {"posts": [{**base, "id": "tomorrow"}]}, key: {"posts": posts}}})
    assert x_daily.qa_next(p, now)[1]["id"] == "today"
    x_daily.set_post(p, key, "today", text="他改了")
    got = x_daily.apply_qa(p, key, "today", seen=ARTICLE, result={"text": "不能覆盖"})
    assert got["text"] == "他改了" and got["qa"] == "skipped" and got["qa_v"] == x_qa.VERSION
    assert x_daily.qa_next(p, now)[1]["id"] == "tomorrow"


def test_bulk_approval_skips_incomplete_running_and_unchecked_but_single_tick_allowed(client_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    client = client_factory(write_fn=model_result(), x_fetch_fn=lambda url: [] if "manifest" in url else {})
    key = x_daily.day_key(x_daily.now_bj())
    base = {"long": True, "prep": "ready", "state": "pending", "text": ARTICLE, "format": "article"}
    posts = [{**base, "id": "incomplete", "qa": "ready", "qa_complete": False},
             {**base, "id": "running", "qa": "running"}, {**base, "id": "unchecked"},
             {**base, "id": "complete", "qa": "ready", "qa_complete": True}]
    x_daily.save(x_daily.path(), {"days": {key: {"posts": posts}}})
    assert client.post(f"/api/xline/daily/{key}/approve-all").json() == {"approved": 1, "left": 3}
    response = client.patch(f"/api/xline/daily/{key}/incomplete", json={"state": "approved"})
    assert response.status_code == 200 and response.json()["post"]["state"] == "approved"


def test_completeness_is_decided_by_code_from_five_checks_and_catches_numbers_without_space() -> None:
    """10/11 作者：完整度检查要 thorough——开头、递进、结尾、编号、指代，一项不过就不完整。"""
    ok = {k: {"ok": True, "why": ""} for k in x_qa.CHECKS}
    assert x_qa.verdict({"checks": ok, "complete": False}) == (True, [], ok)
    bad = {**ok, "递进": {"ok": False, "why": "几段讲话片段堆在一起，没有主线"}}
    complete, issues, _ = x_qa.verdict({"checks": bad, "complete": True})
    assert complete is False and issues == ["递进：几段讲话片段堆在一起，没有主线"]
    assert x_qa.verdict({"complete": False, "issues": ["没有结尾"]})[:2] == (False, ["没有结尾"])  # 老格式
    assert x_qa.verdict({})[:2] == (True, [])
    text = "# 题\n\n1. 第一段\n\n![图](i.png)\n\n2.做自己，第二段\n\n这是 2.5 倍的差距。"
    assert x_qa.renumber(text, "remove") == "# 题\n\n第一段\n\n![图](i.png)\n\n做自己，第二段\n\n这是 2.5 倍的差距。"


@pytest.fixture(autouse=True)
def isolated_qa_rules(tmp_path, monkeypatch):
    """所有 QA 测试只读仓库通用版或临时副本，不碰本机个人规则。"""
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "qa-home"))
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(x_qa.outline.DEFAULT_WORKFLOWS))


def test_rules_priority_frontmatter_and_save_destination(tmp_path, monkeypatch):
    from content_studio.paths import config_dir

    bundled = x_qa.outline.DEFAULT_WORKFLOWS / x_qa.RULES_FILE
    customer = config_dir() / x_qa.RULES_FILE
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(workflows))
    assert x_qa.rules_path() == bundled
    assert x_qa.load_rules()["bundled"] is True
    assert x_qa.save_path() == workflows / x_qa.RULES_FILE
    customer.parent.mkdir()
    customer.write_text("客户规则", encoding="utf-8")
    assert x_qa.rules_path() == customer
    assert x_qa.load_rules()["text"] == "客户规则"
    custom = workflows / x_qa.RULES_FILE
    custom.write_text("---\nowner: test\n---\n\n自定义规则\n", encoding="utf-8")
    assert x_qa.rules_path() == custom
    assert x_qa.load_rules() == {"path": str(custom), "text": "自定义规则", "bundled": False, "save_path": str(custom)}
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(x_qa.outline.DEFAULT_WORKFLOWS))
    assert x_qa.rules_path() == customer  # 客户副本不能被默认 workflows 遮住
    assert x_qa.save_path() == customer
    alias = tmp_path / "bundled-alias"
    alias.symlink_to(x_qa.outline.DEFAULT_WORKFLOWS, target_is_directory=True)
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(alias))
    assert x_qa.save_path() == customer
    assert x_qa.rules_path() == customer


@pytest.mark.parametrize("bad", ["", " \n", "---\nowner: test\n---", b"\xff"])
def test_invalid_rules_fall_back_to_bundled(tmp_path, monkeypatch, bad):
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(workflows))
    (workflows / x_qa.RULES_FILE).write_bytes(bad if isinstance(bad, bytes) else bad.encode())
    result = x_qa.load_rules()
    assert result["bundled"] and result["text"] == x_qa.bundled_rules()
    assert result["save_path"] == str(workflows / x_qa.RULES_FILE)


def test_unreadable_rules_fall_back_and_missing_bundle_has_clear_error(tmp_path, monkeypatch):
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    custom = workflows / x_qa.RULES_FILE
    custom.write_text("自定义规则", encoding="utf-8")
    monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(workflows))
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        if path == custom:
            raise PermissionError("unreadable")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert x_qa.load_rules()["bundled"]
    monkeypatch.setattr(x_qa.outline, "DEFAULT_WORKFLOWS", tmp_path / "missing")
    with pytest.raises(x_qa.QAError, match="找不到 X 发前 QA 规则："):
        x_qa.load_rules()


def test_prompt_uses_only_file_judgement_and_keeps_limits_contract_and_position():
    custom = "自定义规则：只查错字"
    prompt = x_qa.prompt(ARTICLE, kind="长文", source="测试来源", summary=True, rules=custom)
    assert custom in prompt and "来源：测试来源" in prompt
    assert "站在一个在 X 上刷到这条的陌生读者的角度" not in prompt
    assert "## 完整度" not in prompt
    assert "导语如果要写，放在标题下面那段 summary 后面。" in prompt
    hard = prompt.split("## 硬上限（代码会卡）\n")[1].split("## 原文")[0]
    for limit in (x_qa.BEFORE_MAX, x_qa.DELETE_MAX, x_qa.ENDING_MAX, x_qa.INTRO_MAX, x_qa.MAX_CHANGES):
        assert str(limit) in hard
    assert "15%" in hard
    contract = prompt.split("## 输出\n")[1]
    for key in ('"intro"', '"numbering"', '"checks"', '"issues"', '"changes"', '"before"', '"after"', '"why"'):
        assert key in contract
    assert f"通常不超过 {x_qa.BEFORE_MAX} 个字，删不超过 {x_qa.DELETE_MAX} 字" in contract
    plain = x_qa.prompt(ARTICLE, kind="长帖", rules=custom)
    assert "来源：" not in plain and "放在标题下面第一段。" in plain
    assert x_qa.VERSION == 4
    assert x_qa.rules_hash("abc") == "a9993e3647"


@pytest.mark.parametrize("custom_workflows", [False, True])
def test_qa_rules_api_get_save_reset(client_factory, tmp_path, monkeypatch, custom_workflows):
    from content_studio.paths import config_dir

    from content_studio.store import StudioStore

    events = []
    monkeypatch.setattr(StudioStore, "log_event", lambda self, kind, text, topic_id=None: events.append((kind, text)))
    if custom_workflows:
        monkeypatch.setenv(x_qa.outline.WORKFLOWS_ENV, str(tmp_path / "custom"))
    client = client_factory(write_fn=model_result(), x_fetch_fn=lambda url: [])
    bundled_path = x_qa.outline.DEFAULT_WORKFLOWS / x_qa.RULES_FILE
    bundled_bytes = bundled_path.read_bytes()
    got = client.get("/api/xline/qa-rules")
    assert got.status_code == 200
    assert got.json()["bundled"] and not got.json()["resettable"]
    assert got.json()["text"] == got.json()["bundled_text"]
    for text, message in (("短", "规则太短"), ("长" * 20001, "规则太长")):
        response = client.put("/api/xline/qa-rules", json={"text": text})
        assert response.status_code == 400 and response.json()["detail"] == message
    custom = "只查作者原文的错字，不能润色，不能改写原来的观点。"
    saved = client.put("/api/xline/qa-rules", json={"text": " \n" + custom + "\n "})
    assert saved.status_code == 200
    assert ("x", "改了 X 发前 QA 规则") in events
    root = tmp_path / "custom" if custom_workflows else config_dir()
    path = root / x_qa.RULES_FILE
    assert path.read_text(encoding="utf-8") == custom + "\n"
    assert saved.json()["text"] == custom and saved.json()["path"] == saved.json()["save_path"] == str(path)
    assert saved.json()["resettable"] is not custom_workflows
    assert client.get("/api/xline/qa-rules").json()["text"] == custom
    reset = client.delete("/api/xline/qa-rules")
    if custom_workflows:
        assert reset.status_code == 400 and reset.json()["detail"] == "这份在你的规则文件夹里，去那里删"
        assert path.exists()
    else:
        assert reset.status_code == 200 and reset.json()["bundled"] and not reset.json()["resettable"]
        assert not path.exists()
    assert bundled_path.read_bytes() == bundled_bytes


@pytest.mark.parametrize("state", ["pending", "approved"])
def test_changed_hash_requeues_only_eligible_posts_and_keeps_legacy_posts(tmp_path, state):
    from datetime import datetime

    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    p, key = tmp_path / "daily.json", "2026-10-11"
    base = {"long": True, "prep": "ready", "state": state, "text": ARTICLE, "qa": "ready", "qa_v": x_qa.VERSION, "qa_rules": "old"}
    excluded = [{"state": s} for s in ("sent", "sending", "rejected")]
    excluded += [{"qa": s} for s in ("failed", "reverted", "skipped")]
    excluded += [{"long": False, "state": "approved"}, {"prep": "running"}, {"swapped": True}, {"qa_rules": None}, {"qa_rules": "new"}]
    posts = [{**base, **extra, "id": str(i)} for i, extra in enumerate(excluded)]
    legacy = {k: v for k, v in base.items() if k != "qa_rules"}
    posts += [{**legacy, "id": "legacy"}, {**base, "id": "eligible"}]
    x_daily.save(p, {"days": {key: {"posts": posts}, "2026-10-12": {"posts": [{**base, "id": "tomorrow"}]},
                              "2026-10-13": {"posts": [{**base, "id": "future"}]}}})
    assert x_daily.qa_next(p, now) is None
    assert x_daily.qa_next(p, now, rules_hash="new")[1]["id"] == "eligible"
    result = {"text": ARTICLE, "changes": [], "dropped": []}
    done = x_daily.apply_qa(p, key, "eligible", seen=ARTICLE, result=result, rules_hash="new")
    assert done["qa_rules"] == "new" and done["qa_v"] == x_qa.VERSION
    assert x_daily.qa_next(p, now, rules_hash="new")[1]["id"] == "tomorrow"
    x_daily.apply_qa(p, "2026-10-12", "tomorrow", seen=ARTICLE, result=result, rules_hash="new")
    assert x_daily.qa_next(p, now, rules_hash="new") is None


def test_qa_job_uses_one_rules_snapshot_and_records_its_hash(client_factory, monkeypatch):
    old, new = "自定义规则：只查错字，这是本次任务正在使用的那份。", "新规则：按新的标准检查下一篇，不能污染正在做的任务。"
    path = x_qa.save_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(old, encoding="utf-8")
    calls = []
    original_load = x_qa.load_rules

    def load():
        calls.append(True)
        return original_load()

    def write(prompt):
        assert old in prompt and new not in prompt
        path.write_text(new, encoding="utf-8")
        return '{"changes": []}'

    monkeypatch.setattr(x_qa, "load_rules", load)
    client = client_factory(write_fn=write, x_fetch_fn=lambda url: [])
    key = x_daily.day_key(x_daily.now_bj())
    post = {"id": "p", "long": True, "prep": "ready", "state": "pending", "text": ARTICLE}
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [post]}}})
    client.app.state.x_long_qa(key, post)
    got = x_daily.load(x_daily.path())["days"][key]["posts"][0]
    assert len(calls) == 1
    assert got["qa"] == "ready" and got["qa_rules"] == x_qa.rules_hash(old)
    assert x_daily.qa_next(x_daily.path(), rules_hash=x_qa.rules_hash(new))[1]["id"] == "p"


def value_checks(failed=None):
    return {k: {"ok": k != failed, "why": "没有可复用的方法" if k == failed else ""} for k in x_qa.VALUE_CHECKS}


def test_value_verdict_pass_fail_and_missing():
    ok = value_checks()
    assert x_qa.value_verdict({"value": ok}) == (True, [], ok)
    bad = value_checks("解法")
    assert x_qa.value_verdict({"value": bad}) == (False, ["解法：没有可复用的方法"], bad)
    assert x_qa.value_verdict({}) == (True, [], {})
    out = x_qa.run(ARTICLE, kind="长文", write_fn=model_result())
    assert out["value_ok"] is None


@pytest.mark.parametrize("kind", ["长文", "长帖", "合集", "热点长帖"])
def test_long_forms_request_value_without_rewriting(kind):
    out = x_qa.run(ARTICLE, kind=kind, write_fn=model_result(value=value_checks("收藏")))
    assert out["text"] == ARTICLE and out["value_ok"] is False
    prompt = x_qa.prompt(ARTICLE, kind=kind)
    assert '"value":' in prompt and "价值不够不许加内容" in prompt


def test_short_form_does_not_check_or_store_value(tmp_path):
    prompt = x_qa.prompt("短帖", kind="短帖")
    assert '"value"' not in prompt and "## 价值：" not in prompt
    out = x_qa.run("短帖", kind="短帖", write_fn=model_result(value=value_checks("痛点")))
    assert "value_ok" not in out
    p = tmp_path / "daily.json"
    x_daily.save(p, {"days": {"d": {"posts": [{"id": "s", "text": "短帖", "state": "pending"}]}}})
    post = x_daily.apply_qa(p, "d", "s", seen="短帖", result=out)
    assert "qa_value_ok" not in post


def test_value_failure_bulk_hold_and_single_override(client_factory, monkeypatch):
    client = client_factory(write_fn=model_result(value=value_checks("收藏")), x_fetch_fn=lambda url: {})
    key = x_daily.day_key(x_daily.now_bj())
    base = {"long": True, "format": "post", "prep": "ready", "text": ARTICLE, "qa": "ready", "qa_v": 3}
    posts = [{**base, "id": "p", "state": "pending"}, {**base, "id": "a", "state": "approved"}]
    x_daily.save(x_daily.path(), {"days": {key: {"posts": posts}}})
    assert x_daily.qa_next(x_daily.path())[1]["id"] == "p"
    client.app.state.x_long_qa(key, posts[0])
    assert client.post(f"/api/xline/daily/{key}/approve-all").json() == {"approved": 0, "left": 1}
    client.app.state.x_long_qa(key, posts[1])
    held = x_daily.load(x_daily.path())["days"][key]["posts"][1]
    assert held["state"] == "pending" and held["qa_value_held"] is True
    # 旧勾选状态也要在 sendable 里兜底。
    x_daily.set_post(x_daily.path(), key, "a", state="approved")
    d = x_daily.load(x_daily.path())["days"][key]
    assert x_daily.sendable(d) == [] and d["posts"][1]["qa_value_held"]
    x_daily.save(x_daily.path(), {"days": {key: d}})
    post = client.patch(f"/api/xline/daily/{key}/a", json={"state": "approved"}).json()["post"]
    assert post["qa_value_override"] and not post.get("qa_value_held")
    assert [p["id"] for p in x_daily.sendable(x_daily.load(x_daily.path())["days"][key])] == ["a"]


@pytest.mark.parametrize("gate, flag", [("qa_value_ok", "qa_value"), ("qa_complete", "qa_complete")])
def test_tick_persists_hold_without_calling_sender_and_manual_override(tmp_path, gate, flag):
    from datetime import datetime
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    p = tmp_path / "daily.json"
    post = {"id": "p", "long": True, "prep": "ready", "state": "approved", "text": ARTICLE, gate: False}
    x_daily.save(p, {"days": {"2026-10-11": {"posts": [post]}}})
    def forbidden(*args, **kwargs):
        pytest.fail("held post must not reach sender")
    assert x_daily.tick(p, now=now, post_fn=forbidden, record_fn=forbidden) is None
    held = x_daily.load(p)["days"]["2026-10-11"]["posts"][0]
    assert held["state"] == "pending" and held[f"{flag}_held"]
    x_daily.mark(p, "2026-10-11", "p", state="approved")
    assert x_daily.due(x_daily.load(p)["days"]["2026-10-11"], now)["id"] == "p"


@pytest.mark.parametrize("state", ["pending", "approved"])
def test_version_four_requeues_version_three(tmp_path, state):
    from datetime import datetime
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    p = tmp_path / "daily.json"
    post = {"id": "p", "long": True, "prep": "ready", "state": state, "text": ARTICLE, "qa": "ready", "qa_v": 3}
    x_daily.save(p, {"days": {"2026-10-11": {"posts": [post]}}})
    assert x_daily.qa_next(p, now) == ("2026-10-11", post)
