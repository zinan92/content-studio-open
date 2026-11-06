"""第一轮：打分 + 修改清单。没有评论；每个原因只能做它被允许的事；超预算的放进「没放进来」（10/12 作者）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio.extras.xline import write_gates as gates
from content_studio.extras.xline import write_module, write_patch as wp
from test_write_module import make_skill

PARAS = [f"第{n}段：我觉得闭环比终局更重要，因为终局大家都看得到，但是短期做不到，所以小闭环先闭，大闭环后闭，编号{n}不用管。" for n in "一二三四五六七八九十"]
LAST = "所以先完成小闭环，再往上叠业务，这就是我的判断。"
BASE = "# 闭环\n\n" + "\n\n".join([*PARAS, LAST]) + "\n"


@pytest.fixture()
def mod(tmp_path: Path):
    m = write_module.load(make_skill(tmp_path))
    return m, wp.round_steps(m, m.flows["流程1"])


def ch(reason, op, anchor, text="", note="为什么", **more):
    return {"reason": reason, "op": op, "anchor": anchor, "text": text, "note": note, **more}


def run(mod, *changes, base=BASE, pct=None):
    m, steps = mod
    if pct is not None:
        m = write_module.with_pct(m, pct)
    return wp.validate(m, steps, base, {"scores": {"高密度": {"score": 62, "why": "x"}, "稀缺": {"score": 50, "why": "y"}}, "changes": list(changes)})


def whys(r):
    return [d["why"] for d in r["dropped"]]


# -- 谁能做什么 ------------------------------------------------------------------------------------

def test_valid_changes_are_kept_in_order_with_positions_and_scores(mod) -> None:
    r = run(mod, ch("开头", "move", LAST), ch("风格", "replace", "编号一不用管", "编号一"), ch("风格", "delete", "编号二不用管"),
            ch("稀缺", "insert", "编号四不用管", "这件事只有我亲自做过才讲得出来。"))
    assert [c["id"] for c in r["changes"]] == ["c1", "c2", "c3", "c4"]
    assert [c["op"] for c in r["changes"]] == ["move", "replace", "delete", "insert"]
    assert BASE[r["changes"][0]["start"]:r["changes"][0]["end"]] == LAST and all(c["status"] == "pending" for c in r["changes"])
    assert r["scores"]["高密度"] == {"score": 62, "why": "x"} and r["dropped"] == [] and r["overflow"] == [] and 0 < r["budget"] <= 20


def test_density_pain_and_benefit_can_only_add_never_delete_or_replace(mod) -> None:
    r = run(mod, ch("高密度", "delete", "编号二不用管"), ch("高密度", "replace", "编号三不用管", "编号三"),
            ch("高密度", "insert", "编号四不用管", "这一段的意思是：先闭小闭环。"))
    assert [c["op"] for c in r["changes"]] == ["insert"] and r["changes"][0]["fresh"] is True  # 清单里没写 may-add 的老版本，高密度默认也能加
    assert "不能删字" in whys(r)[0] and "不能换字" in whys(r)[1]


def test_only_style_may_delete_and_only_fillers_duplicates_or_invisible_references(mod) -> None:
    unique = "这是一段完全不同的话，讲的是另外一件事：怎么把一个想法拆成能今天就动手的三步，每一步先做什么、后做什么、做到什么程度算完。"
    base = BASE.replace(PARAS[5], unique)
    r = run(mod, ch("风格", "delete", "编号二不用管"), ch("风格", "delete", unique), ch("开头", "delete", "编号三不用管"), base=base)
    assert [c["anchor"] for c in r["changes"]] == ["编号二不用管"]
    assert any("口癖、重复" in w for w in whys(r)) and any("不能删字" in w for w in whys(r))
    i = BASE.index("编号二不用管")
    assert gates.deletable(BASE, i, i + 6) == "口癖"
    # 紧挨着的两句几乎一样：后一句算重复，哪怕不短
    dup = "我觉得闭环比终局更重要，因为终局大家都看得到但是短期做不到。我觉得闭环比终局更重要，因为终局大家都看得到但是短期做不到啊。"
    b2 = "# t\n\n" + dup + "\n"
    j = b2.index("我觉得", 10)
    assert gates.deletable(b2, j, len(b2) - 1) == "重复"
    s = "你可以看到我的屏幕上有一个很长很长的东西，我现在给你看。"
    assert gates.deletable("# t\n\n" + s, 5, 5 + len(s)) == "读者看不到的指代"
    long_plain = "这是一段很长很长的原话，讲的是和前后都不一样的内容，" * 4
    assert gates.deletable("# t\n\n" + long_plain + "\n", 5, 5 + len(long_plain)) is None


def test_comments_are_gone_and_score_only_reasons_never_write_changes(mod) -> None:
    r = run(mod, ch("稀缺", "comment", "编号四不用管", note="缺你自己的数字"), ch("完整度", "insert", "编号五不用管", "补一句结尾。"),
            ch("完整度", "delete", "编号六不用管"))
    assert r["changes"] == [] and r["overflow"] == []
    assert whys(r) == ["不再有评论，只写修改", "这一项只打分，不写修改", "这一项只打分，不写修改"]


def test_a_reason_outside_the_flow_or_missing_anchors_are_dropped_not_guessed(mod) -> None:
    r = run(mod, ch("风格", "delete", "原文里根本没有的一句话"), ch("风格", "delete", "我觉得闭环比终局更重要"),
            ch("风格", "delete", "# 闭环"), ch("没有的原因", "delete", "编号三不用管"))
    assert r["changes"] == [] and whys(r) == ["原文里找不到这一句", "这一句在原文里出现了多次，没法定位", "anchor 不能是标题，也不能跨段", "原因不在这个流程里"]


def test_only_the_opening_may_move_one_whole_sentence(mod) -> None:
    r = run(mod, ch("风格", "move", LAST), ch("开头", "move", PARAS[4][:12]), ch("开头", "move", LAST), ch("开头", "move", PARAS[5][-20:]))
    assert [(c["op"], c["reason"]) for c in r["changes"]] == [("move", "开头")]
    assert "只有「开头」可以挪一句" in whys(r)[0] and "一整句" in whys(r)[1] and "已经用过了" in whys(r)[2]


def test_new_words_are_short_marked_and_never_carry_new_numbers(mod) -> None:
    ok = ch("稀缺", "insert", "编号五不用管", "这件事不只是我一个人的经历。")
    r = run(mod, ok, ch("风格", "insert", "编号六不用管", "我是风格，不该加字。"), ch("稀缺", "insert", "编号七不用管", "我已经做了 500 个。"),
            ch("稀缺", "insert", "编号八不用管", "长" * 60))
    assert [(c["op"], c["fresh"]) for c in r["changes"]] == [("insert", True)]
    ws = " ".join(whys(r))
    assert "不能新写字" in ws and "数字" in ws and "超过 50 字" in ws
    assert "这件事不只是我一个人的经历。" in wp.render(BASE, [{**r["changes"][0], "status": "accepted"}])


def test_a_replacement_must_be_his_own_shortened_sentence(mod) -> None:
    r = run(mod, ch("风格", "replace", "编号九不用管", "这是模型自己编的另外一套说法，原文里没有。"), ch("风格", "replace", "编号一不用管", "编号一"))
    assert [c["anchor"] for c in r["changes"]] == ["编号一不用管"] and "不是原句去掉口癖后的样子" in whys(r)[0]


def test_bold_only_edits_are_for_style_only_and_capped(mod) -> None:
    r = run(mod, ch("结尾", "replace", "编号一不用管", "**编号一不用管**"), ch("风格", "replace", "编号二不用管", "**编号二不用管**"))
    assert [(c["reason"], c["op"]) for c in r["changes"]] == [("风格", "replace")] and "不能换字" in whys(r)[0]
    many = [ch("风格", "replace", f"编号{n}不用管", f"**编号{n}不用管**") for n in "一二三四五六七八"]
    assert len(run(mod, *many)["changes"]) == wp.MAX_BOLD  # 最多 6 处


def test_old_words_plus_more_counts_as_adding_words(mod) -> None:
    r = run(mod, ch("风格", "replace", "编号二不用管", PARAS[6][:20] + "编号二不用管"))
    assert r["changes"] == [] and "不能新写字" in whys(r)[0]  # 风格不能加字：复制后文的企图被挡住
    r = run(mod, ch("稀缺", "replace", "编号二不用管", "这件事我亲自做过。编号二不用管"))
    c = r["changes"][0]
    assert (c["op"], c["pos"], c["fresh"], c["text"]) == ("insert", "before", True, "这件事我亲自做过。")
    text = wp.render(BASE, [{**c, "status": "accepted"}])
    assert text.count("编号二不用管") == 1 and "这件事我亲自做过。编号二不用管" in text


def test_overlapping_edits_keep_the_first(mod) -> None:
    r = run(mod, ch("风格", "delete", "编号三不用管"), ch("风格", "replace", "编号三不用", "编号三"))
    assert [c["op"] for c in r["changes"]] == ["delete"] and "重叠" in whys(r)[0]


# -- 预算和「没放进来」 ----------------------------------------------------------------------------------

def test_over_budget_edits_wait_in_overflow_not_as_comments(mod) -> None:
    cs = [ch("风格", "delete", f"编号{n}不用管") for n in "一二三四五"]
    r = run(mod, *cs, pct=3)  # 3% ≈ 19 字：三条 6 字的删除放得下
    assert [c["anchor"] for c in r["changes"]] == ["编号一不用管", "编号二不用管", "编号三不用管"]
    assert [o["anchor"] for o in r["overflow"]] == ["编号四不用管", "编号五不用管"] and all(o["status"] == "overflow" for o in r["overflow"])
    assert all(c["op"] != "comment" for c in r["changes"]) and r["budget"] <= 3.0


def test_raising_the_budget_readmits_overflow_and_lowering_never_removes_anything(mod) -> None:
    cs = [ch("风格", "delete", f"编号{n}不用管") for n in "一二三四五"]
    r = run(mod, *cs, pct=3)
    trk = {"base": BASE, "changes": r["changes"], "overflow": r["overflow"], "history": []}
    trk["changes"][0]["status"] = "accepted"
    assert wp.apply_budget(trk, 6) == 2 and trk["overflow"] == [] and trk["max_pct"] == 6
    assert [c["id"] for c in trk["changes"]][-2:] == ["c4", "c5"] and all(c["status"] == "pending" for c in trk["changes"][3:])
    assert wp.apply_budget(trk, 1) == 0 and len(trk["changes"]) == 5 and trk["changes"][0]["status"] == "accepted"  # 调低不撤销


def test_overflow_item_that_now_overlaps_stays_waiting(mod) -> None:
    r = run(mod, ch("风格", "delete", "编号一不用管"), pct=1)
    trk = {"base": BASE, "changes": [], "overflow": [{**r["changes"][0], "status": "overflow"}] if r["changes"] else
           [{"reason": "风格", "op": "delete", "anchor": "编号一不用管", "text": "", "note": "", "start": BASE.index("编号一不用管"),
             "end": BASE.index("编号一不用管") + 6, "pos": "after", "fresh": False, "downgraded": False, "status": "overflow", "edit": None, "source": "round1"}], "history": []}
    twin = {**trk["overflow"][0], "id": "c1", "status": "pending"}
    trk["changes"] = [twin]
    assert wp.apply_budget(trk, 20) == 0 and len(trk["overflow"]) == 1  # 压在已有那一条上：不放


def test_the_final_gate_moves_edits_to_overflow_instead_of_wiping_the_list(mod, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    real = gates.check

    def flaky(*a, **k):
        calls["n"] += 1
        return ["整体：假装有一条没过"] if calls["n"] == 1 else real(*a, **k)

    monkeypatch.setattr(gates, "check", flaky)
    r = run(mod, ch("风格", "delete", "编号一不用管"), ch("风格", "delete", "编号二不用管"))
    assert [c["anchor"] for c in r["changes"]] == ["编号一不用管"]  # 最后一条收进「没放进来」，前面的还在
    assert r["overflow"][0]["anchor"] == "编号二不用管" and "整体没过关卡" in r["overflow"][0]["overflow_why"] and r["gate_failures"]


# -- 应用、处理、撤销 ----------------------------------------------------------------------------------

def test_nothing_is_applied_until_he_accepts(mod) -> None:
    r = run(mod, ch("开头", "move", LAST), ch("风格", "replace", "编号一不用管", "编号一"), ch("风格", "delete", "编号二不用管"))
    cs = r["changes"]
    assert wp.render(BASE, cs) == BASE
    cs[0]["status"], cs[1]["status"], cs[1]["edit"] = "accepted", "edited", "编号 1"
    text = wp.render(BASE, cs)
    assert text.split("\n\n")[1] == LAST and "编号 1" in text and "编号二不用管" in text and text.count(LAST) == 1
    wp.set_all(cs, "accepted")
    assert "编号二不用管" not in wp.render(BASE, cs) and wp.pending_edits(cs) == 0
    wp.set_all(cs, "reset")
    assert {c["status"] for c in cs} == {"pending"} and cs[1]["edit"] is None


def test_edit_status_rules_and_undo(mod) -> None:
    trk = {"base": BASE, "changes": run(mod, ch("风格", "replace", "编号一不用管", "编号一"), ch("风格", "delete", "编号二不用管"))["changes"], "history": []}
    cs = trk["changes"]
    wp.set_status(cs, "c1", "edited", "编号 1")
    assert cs[0]["edit"] == "编号 1"
    with pytest.raises(wp.PatchError, match="用我改的"):
        wp.set_status(cs, "c2", "edited", "x")
    with pytest.raises(wp.PatchError, match="找不到"):
        wp.set_status(cs, "c9", "accepted")
    wp.snapshot(trk, "全部接受")
    wp.set_all(cs, "accepted")
    assert wp.undo(trk) == "全部接受" and [c["status"] for c in cs] == ["edited", "pending"]
    with pytest.raises(wp.PatchError, match="没有可以撤销"):
        wp.undo(trk)


def test_qa_edits_join_the_same_list_and_overflow_when_the_budget_is_gone(mod) -> None:
    trk = {"changes": run(mod, ch("风格", "delete", "编号二不用管"))["changes"], "dropped": [], "overflow": []}
    added = wp.merge_qa(trk, BASE, [
        {"kind": "错字", "before": "编号一不用管", "after": "编号一不用管。", "why": "标点"},
        {"kind": "不通顺", "before": "编号二不用管", "after": "编号二", "why": "和删除重叠"},
        {"kind": "补结尾", "before": "", "after": "好，结束。", "why": "没收住"},
        {"kind": "导语", "before": "", "after": "这篇讲闭环。", "why": "看不出是什么"},
        {"kind": "编号", "before": "", "after": "去掉编号", "why": "x"}], 20)
    assert added == 3
    qa = [c for c in trk["changes"] if c["source"] == "qa"]
    assert [(c["id"], c["reason"], c["pos"]) for c in qa] == [("q1", "错字", "after"), ("q2", "结尾", "after"), ("q3", "导语", "top")]
    assert trk["dropped"][0]["why"] == "和别的修改重叠了"
    # 预算只剩一点点：QA 的改动不丢，放进「没放进来」，调高就能放进来
    tight = {"changes": [], "dropped": [], "overflow": []}
    wp.merge_qa(tight, BASE, [{"kind": "错字", "before": "编号一不用管", "after": "编号一不用管。", "why": "x"}], 0)
    assert tight["changes"] == [] and tight["overflow"][0]["reason"] == "错字" and tight["overflow"][0]["status"] == "overflow"


def test_round_one_is_one_call_with_no_comment_option_and_retries_bad_json_once(mod) -> None:
    m, _ = mod
    calls: list[str] = []
    good = {"scores": {"痛点": {"score": 70, "why": "x"}}, "changes": [ch("风格", "delete", "编号二不用管")]}

    def model(prompt: str) -> str:
        calls.append(prompt)
        return "<<<JSON>>>\n" + json.dumps(good, ensure_ascii=False) + "\n<<<END>>>" if len(calls) > 1 else "我不会"

    res = wp.run_round1(m, m.flows["流程1"], BASE, write_fn=model)
    assert len(calls) == 2 and "上一次有问题" in calls[1] and res["steps"] == ["opening", "density", "scarcity", "ending", "style", "check-complete"]
    assert [c["op"] for c in res["changes"]] == ["delete"] and res["rules"]["opening"] == m.step_version("opening")
    p = calls[0]
    assert "每一条都是直接修改，没有评论" in p and "不超过原文的 20%" in p and BASE.strip() in p
    assert "只能加" in p and "能删" in p and "只打分、不写修改" in p and "comment（" not in p
    assert "不要写这一条" in p  # 缺他经历的地方：不写，不占位
    with pytest.raises(wp.PatchError, match="JSON"):
        wp.run_round1(m, m.flows["流程1"], BASE, write_fn=lambda p: "<<<JSON>>>\n{坏的\n<<<END>>>")


def test_the_article_can_have_its_own_budget(mod) -> None:
    m, _ = mod
    assert m.constraints["max-change-pct"] == 20
    assert write_module.with_pct(m, 35).constraints["max-change-pct"] == 35
    assert write_module.with_pct(m, 500).constraints["max-change-pct"] == 50 and write_module.with_pct(m, 0).constraints["max-change-pct"] == 1


# -- 打分项读清单里的 review（10/13 作者 的 9 项）---------------------------------------------------

def test_scores_follow_the_review_list_and_fall_back_to_the_six_without_it(tmp_path: Path) -> None:
    from test_write_module import with_review

    old = write_module.load(make_skill(tmp_path / "old"))
    assert wp.score_names(old, wp.round_steps(old, old.flows["流程1"])) == ["高密度", "完整度", "稀缺"]  # 老版本：原来的六项里有的
    m = write_module.load(with_review(tmp_path))
    steps = wp.round_steps(m, m.flows["流程1"])
    assert wp.score_names(m, steps) == ["留人", "密度", "稀缺", "口气"]
    prompt = wp.build_prompt(m, steps, BASE)
    assert "留人、密度、稀缺、口气" in prompt and '"留人": {"score": 62' in prompt
    out = wp._scores({"scores": {"留人": {"score": 130, "why": "x"}, "口气": {"score": 70, "why": "y"}, "高密度": {"score": 9, "why": "旧名字不认"}}},
                     wp.score_names(m, steps))
    assert out == {"留人": {"score": 100, "why": "x"}, "口气": {"score": 70, "why": "y"}}
    assert "留人" in wp.rescore_prompt(m, steps, BASE) and "稀缺" in wp.rescore_prompt(m, steps, BASE)
