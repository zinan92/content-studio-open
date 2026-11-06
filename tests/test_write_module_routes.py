"""长文做成「打分 + 修改清单」：做的时候、逐条处理、QA 并进清单、再打分、清单有问题时。"""
from __future__ import annotations

import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_daily
from test_write_module import MANIFEST, make_skill
from test_x_daily import SUMMARY
from test_x_line import client_factory  # noqa: F401 - fixture

PARAS = [f"第{n}段：我觉得闭环比终局更重要，因为终局大家都看得到，但是短期做不到，所以小闭环先闭，大闭环后闭，编号{n}不用管。" for n in "一二三四五六七八九十"]
LAST = "所以先完成小闭环，再往上叠业务，这就是我的判断。"
NOTE = "\n\n".join([*PARAS, LAST])


def round1_json(extra: list | None = None) -> str:
    changes = [{"reason": "开头", "op": "move", "anchor": LAST, "text": "", "note": "判断提前"},
               {"reason": "风格", "op": "replace", "anchor": "编号一不用管", "text": "编号一", "note": "去口水"},
               {"reason": "风格", "op": "delete", "anchor": "编号二不用管", "text": "", "note": "口癖"},
               {"reason": "稀缺", "op": "insert", "anchor": PARAS[4][:12], "text": "这件事是我自己做出来的。", "note": "点明是你亲自做的"}, *(extra or [])]
    scores = {k: {"score": v, "why": "x"} for k, v in {"高密度": 60, "痛点": 55, "利他": 70, "完整度": 85, "共鸣": 40, "稀缺": 50}.items()}
    return "<<<JSON>>>\n" + json.dumps({"scores": scores, "changes": changes}, ensure_ascii=False) + "\n<<<END>>>"


def model_factory(calls: list[str], *, qa_changes: str = "[]"):
    def model(prompt: str) -> str:
        calls.append(prompt)
        if "<<<SUMMARY>>>" in prompt:
            return f"<<<SUMMARY>>>\n{SUMMARY}\n<<<END>>>"
        if "你在帮 作者 改他自己的一篇长文" in prompt:
            return round1_json()
        if "重新打分" in prompt:
            return "<<<JSON>>>\n" + json.dumps({"scores": {"高密度": {"score": 78, "why": "好了"}, "痛点": {"score": 80, "why": "好了"}}}, ensure_ascii=False) + "\n<<<END>>>"
        return json.dumps({"changes": json.loads(qa_changes), "checks": {}, "complete": True, "issues": [], "numbering": "keep"})  # 发前 QA
    return model


def setup(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model, manifest: str = MANIFEST, date: str | None = None):  # noqa: F811
    date = date or x_daily.now_bj().date().isoformat()  # 默认是今天写的笔记：不加 summary
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(make_skill(tmp_path, manifest)))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "闭环.md").write_text(f"---\ndate: {date} 14:55\n---\n" + NOTE, encoding="utf-8")

    def draw(path: Path) -> None:
        (path.parent / "illustrations").mkdir(exist_ok=True)
        (path.parent / "illustrations" / "01-loop.png").write_bytes(b"png")
        path.write_text(path.read_text(encoding="utf-8") + "\n![闭环](illustrations/01-loop.png)\n", encoding="utf-8")

    client: TestClient = client_factory(write_fn=model, x_illustrate_fn=draw, x_fetch_fn=lambda url: [] if "manifest" in url else {})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    key = x_daily.day_key(x_daily.now_bj())
    pid = f"{key}-L0"
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [{"id": pid, "long": True, "state": "pending", "text": "原文",
                                                             "source_id": "obsidian:003_原始输出/闭环.md"}],
                                                 "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    return client, key, pid


def post_of(client: TestClient) -> dict:
    return client.get("/api/xline/daily").json()["today"]["posts"][0]


def wait_for(client: TestClient, field: str, gone: bool = True) -> dict:
    for _ in range(200):
        p = post_of(client)
        if bool((p.get("trk") or {}).get(field)) != gone:
            return p
        time.sleep(0.05)
    raise AssertionError("后台没做完")


def test_long_article_is_one_round_one_call_and_changes_wait_for_him(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory(calls))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    post = post_of(client)
    assert post["prep"] == "ready", post.get("prep_error")
    assert sum("你在帮 作者 改他自己的一篇长文" in c for c in calls) == 1  # 第一轮一次调用，不是一步一次
    assert not any("<<<SUMMARY>>>" in c for c in calls)  # 今天写的新内容不加 summary
    trk = post["trk"]
    assert [c["op"] for c in trk["changes"]] == ["move", "replace", "delete", "insert"]  # 没有评论
    assert trk["pct"] == 20 and trk["overflow"] == []
    assert trk["scores"]["before"]["稀缺"]["score"] == 50 and trk["budget"] > 0
    # 修改没处理之前，正文还是他的原文（加配图）
    assert LAST in post["text"].split("\n\n")[-2] and "编号二不用管" in post["text"] and "illustrations/01-loop.png" in post["text"]
    assert post["flow"][0]["id"] == "opening" and post["flow"][0]["status"] == "ran" and "改了 1 处" in post["flow"][0]["note"]
    scarcity = [r for r in post["flow"] if r["id"] == "scarcity"][0]
    assert scarcity["status"] == "ran" and "改了 1 处" in scarcity["note"] and "评论" not in scarcity["note"]


def test_summary_is_written_only_for_old_notes_and_follows_the_toggle(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory(calls), date="2026-04-30")
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    post = post_of(client)
    assert any("<<<SUMMARY>>>" in c for c in calls) and post["summary"] is True and post["trk"]["parts"]["summary"] == SUMMARY
    assert post["text"].split("\n\n")[1] == SUMMARY
    off = client.post(f"/api/xline/daily/{key}/{pid}/trk/summary", json={"on": False}).json()["post"]
    assert off["text"].split("\n\n")[1] != SUMMARY and post_of(client)["summary"] is False

    calls2: list[str] = []
    client2, key2, pid2 = setup(client_factory, tmp_path / "b", monkeypatch, model_factory(calls2))
    client2.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    assert not any("<<<SUMMARY>>>" in c for c in calls2) and post_of(client2)["summary"] is False  # 今天写的新内容不加


def test_accepting_editing_and_rejecting_changes_rebuilds_the_text_and_the_file(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([]))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    url = f"/api/xline/daily/{key}/{pid}/trk"
    r = client.post(f"{url}/c1", json={"status": "accepted"}).json()["post"]
    assert r["text"].split("\n\n")[1] == LAST and r["trk"]["changes"][0]["status"] == "accepted"
    assert Path(r["article"]).read_text(encoding="utf-8") == r["text"] and "illustrations/01-loop.png" in r["text"]  # 配图还在
    r = client.post(f"{url}/c2", json={"status": "edited", "edit": "编号 1"}).json()["post"]
    assert "编号 1" in r["text"] and client.post(f"{url}/c3", json={"status": "edited", "edit": "x"}).status_code == 400
    assert client.post(f"{url}/c4", json={"status": "resolved"}).status_code == 400  # 修改没有「知道了」，只能接受 / 不要
    # 还有一处没处理：不能勾、不能存草稿
    assert client.patch(f"/api/xline/daily/{key}/{pid}", json={"state": "approved"}).status_code == 400
    x_daily.set_post(x_daily.path(), key, pid, manual_publish=True)
    assert "还有 2 处修改没处理" in client.post(f"{url[:-4]}/draft").json()["detail"]
    r = client.post(url, json={"all": "rejected"}).json()["post"]  # 剩下的修改都不要；评论不碰（它们不挡着往下走）
    assert [c["status"] for c in r["trk"]["changes"]] == ["accepted", "edited", "rejected", "rejected"]
    assert "编号二不用管" in r["text"] and client.patch(f"/api/xline/daily/{key}/{pid}", json={"state": "approved"}).status_code == 200
    assert client.patch(f"/api/xline/daily/{key}/{pid}", json={"text": "我自己改"}).status_code == 400  # 带清单的：要改字在批注视图里改


def test_qa_edits_join_the_change_list_and_the_text_is_not_edited_behind_his_back(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    qa = json.dumps([{"kind": "错字", "before": "编号三不用管", "after": "编号三不用管。", "why": "标点"}], ensure_ascii=False)
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([], qa_changes=qa))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    before = post_of(client)["text"]
    client.app.state.x_long_qa(key, post_of(client))
    post = post_of(client)
    q = [c for c in post["trk"]["changes"] if c["source"] == "qa"]
    assert post["qa"] == "ready" and [(c["id"], c["reason"], c["status"]) for c in q] == [("q1", "错字", "pending")]
    assert post["text"] == before and post["qa_changes"] == []  # 没接受之前正文不动
    rows = {r["id"]: r for r in post["flow"]}
    assert rows["check-typo"]["status"] == "ran" and rows["check-typo"]["note"] == "提了 1 处"
    client.post(f"/api/xline/daily/{key}/{pid}/trk/q1", json={"status": "accepted"})
    assert "编号三不用管。" in post_of(client)["text"]


def test_rescoring_after_he_is_done_shows_before_and_after(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([]))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    assert client.post(f"/api/xline/daily/{key}/{pid}/trk/rescore").json()["started"] is True
    for _ in range(200):
        t = post_of(client)["trk"]
        if t["scores"]["after"]:
            break
        time.sleep(0.05)
    t = post_of(client)["trk"]
    assert t["scores"]["after"]["高密度"]["score"] == 78 and t["rescoring"] is False
    assert "分数 60 → 78" in [r for r in post_of(client)["flow"] if r["id"] == "density"][0]["note"]


def test_prep_refuses_to_run_on_a_manifest_it_does_not_understand(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    bad = MANIFEST.replace("keep-order: true", "keep-order: true\n  make-it-good: true")
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, lambda p: pytest.fail("不该调模型"), bad)
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    post = post_of(client)
    assert post["prep"] == "failed" and "make-it-good" in post["prep_error"] and "没运行" in post["prep_error"]


def test_module_info_and_saved_flows_follow_the_manifest(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, lambda p: "")
    info = client.get("/api/xline/write/module").json()
    assert info["ok"] and info["default"] == "流程1" and list(info["flows"]) == ["流程1", "流程2"]
    assert [(s["id"], s["round"], s["fix"]) for s in info["steps"]][:3] == [("opening", 1, "edit"), ("density", 1, "edit"), ("scarcity", 1, "edit")]
    assert info["constraints"]["max-change-pct"] == 20 and info["max_change_pct"] == 20 and info["asked_change_pct"] == 50
    assert info["max_change_pct_limit"] == 50
    saved = client.put("/api/xline/write/flow", json={"save": {"name": "我的", "steps": ["style", "opening"]}, "default": "我的"}).json()
    assert saved["write_flow"] == {"default": "我的", "custom": {"我的": ["opening", "style"]}, "max_change_pct": 20}
    assert client.put("/api/xline/write/flow", json={"save": {"name": "流程1", "steps": ["opening"]}}).status_code == 400
    assert client.put("/api/xline/write/flow", json={"save": {"name": "乱", "steps": ["nope"]}}).status_code == 400
    client.put("/api/xline/write/flow", json={"save": {"name": "二", "steps": ["opening"]}})
    assert client.put("/api/xline/write/flow", json={"save": {"name": "三", "steps": ["opening"]}}).status_code == 400
    x_daily.set_post(x_daily.path(), key, pid, prep="failed")
    assert client.post(f"/api/xline/daily/{key}/{pid}/prep", json={"flow": "没有"}).status_code == 400
    assert client.post(f"/api/xline/daily/{key}/{pid}/prep", json={"flow": "流程2"}).json()["post"]["flow_name"] == "流程2"
    assert client.put("/api/xline/write/flow", json={"delete": "二"}).json()["write_flow"]["custom"] == {"我的": ["opening", "style"]}


def test_without_the_skill_the_old_single_pass_still_works(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    def long_model(prompt: str) -> str:
        if "<<<SUMMARY>>>" in prompt:
            return f"<<<SUMMARY>>>\n{SUMMARY}\n<<<END>>>"
        return "<<<ARTICLE>>>\n# 闭环\n\n" + NOTE + "\n<<<END>>>"

    client, key, pid = setup(client_factory, tmp_path, monkeypatch, long_model, date="2026-04-30")
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", "off")
    assert client.get("/api/xline/write/module").json()["installed"] is False
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    post = post_of(client)
    assert post["prep"] == "ready" and post["trk"] is None and post["summary"] is True  # 老路径：整理一次，summary 照旧
    rows = {r["id"]: r for r in post["flow"]}
    assert rows["style"]["status"] == "ran" and rows["opening"]["status"] == "bundled"


def test_a_flow_that_blocks_incomplete_articles_refuses_to_save_the_draft(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    blocked = MANIFEST.replace("on-fail: swap-if-ending-unfinished", "on-fail: block")
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, lambda p: "", blocked)
    x_daily.set_post(x_daily.path(), key, pid, manual_publish=True, prep="ready", article=str(tmp_path / "a" / "article.md"),
                     qa="ready", qa_complete=False)
    r = client.post(f"/api/xline/daily/{key}/{pid}/draft")
    assert r.status_code == 400 and "拦住" in r.json()["detail"]


def test_undo_goes_back_step_by_step_and_reset_restores_everything(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([]))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    url = f"/api/xline/daily/{key}/{pid}/trk"
    original = post_of(client)["text"]
    client.post(f"{url}/c1", json={"status": "accepted"})
    client.post(f"{url}/c2", json={"status": "edited", "edit": "编号 1"})
    client.post(url, json={"all": "accepted"})
    hist = post_of(client)["trk"]["history"]
    assert [h["label"] for h in hist] == ["接受一处", "改了一处", "全部接受"]
    r = client.post(f"{url}/undo").json()
    assert r["undone"] == "全部接受" and r["post"]["trk"]["changes"][2]["status"] == "pending"  # 全部接受之前的状态回来了
    assert "编号 1" in r["post"]["text"] and Path(r["post"]["article"]).read_text(encoding="utf-8") == r["post"]["text"]
    client.post(f"{url}/undo")
    client.post(f"{url}/undo")
    assert post_of(client)["text"] == original and client.post(f"{url}/undo").status_code == 400  # 撤到头了
    client.post(url, json={"all": "accepted"})
    r = client.post(url, json={"all": "reset"}).json()["post"]
    assert {c["status"] for c in r["trk"]["changes"]} == {"pending"} and r["text"] == original
    assert client.post(f"{url}/undo").json()["post"]["trk"]["changes"][0]["status"] == "accepted"  # 全部还原也能撤销


def test_scores_are_redone_by_themselves_once_every_edit_is_handled(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([]))
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    url = f"/api/xline/daily/{key}/{pid}/trk"
    client.post(f"{url}/c1", json={"status": "accepted"})
    time.sleep(0.2)
    assert post_of(client)["trk"]["scores"]["after"] is None and not post_of(client)["trk"]["rescoring"]  # 还有没处理的：不打
    client.post(url, json={"all": "accepted"})  # 处理完了：自己开始打分，不用再点
    for _ in range(200):
        if post_of(client)["trk"]["scores"]["after"]:
            break
        time.sleep(0.05)
    sc = post_of(client)["trk"]["scores"]
    assert sc["after"]["高密度"]["score"] == 78 and sc["stale"] is False
    # 之后又改了：旧分标成过期；处理完再自动打
    client.post(f"{url}/undo")
    assert post_of(client)["trk"]["scores"]["stale"] is True


def test_the_summary_checkbox_stays_on_while_it_is_being_written(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    gate = {"open": False}

    def slow_model(prompt: str) -> str:
        if "<<<SUMMARY>>>" in prompt:
            for _ in range(100):
                if gate["open"]:
                    break
                time.sleep(0.02)
            return f"<<<SUMMARY>>>\n{SUMMARY}\n<<<END>>>"
        return model_factory([])(prompt)

    client, key, pid = setup(client_factory, tmp_path, monkeypatch, slow_model, date="2026-04-30")
    gate["open"] = True
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    client.post(f"/api/xline/daily/{key}/{pid}/trk/summary", json={"on": False})
    gate["open"] = False
    assert client.post(f"/api/xline/daily/{key}/{pid}/trk/summary", json={"on": True}).json()["started"] is True
    p = post_of(client)
    assert p["summary_busy"] is True and p["summary_mode"] == "on"  # 写好之前不会被页面自己取消勾
    assert client.post(f"/api/xline/daily/{key}/{pid}/trk/summary", json={"on": False}).status_code == 409
    gate["open"] = True
    for _ in range(200):
        if not post_of(client).get("summary_busy"):
            break
        time.sleep(0.05)
    p = post_of(client)
    assert p["summary"] is True and p["trk"]["parts"]["summary"] == SUMMARY and p["text"].split("\n\n")[1] == SUMMARY




def test_the_budget_is_a_setting_and_each_article_can_have_its_own(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model_factory([]))
    # 设置里的默认：存了、读得回来；超出范围的拒绝
    assert client.put("/api/xline/write/flow", json={"max_change_pct": 30}).json()["write_flow"]["max_change_pct"] == 30
    assert client.get("/api/xline/write/module").json()["max_change_pct"] == 30
    assert client.put("/api/xline/write/flow", json={"max_change_pct": 99}).status_code == 400
    assert client.put("/api/xline/write/flow", json={"max_change_pct": 0}).status_code == 400
    assert client.get("/api/xline/write/module").json()["max_change_pct"] == 30
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    t = post_of(client)["trk"]
    assert t["pct"] == 30 and post_of(client)["trk"]["pct_effective"] == 30
    # 这一篇自己改：只影响这一篇；调低不会动已有的修改
    url = f"/api/xline/daily/{key}/{pid}/trk"
    client.post(f"{url}/c2", json={"status": "accepted"})
    r = client.post(f"{url}/budget", json={"pct": 1}).json()
    assert r["post"]["trk"]["max_pct"] == 1 and post_of(client)["trk"]["pct_effective"] == 1
    assert [c["status"] for c in r["post"]["trk"]["changes"]][1] == "accepted"
    assert client.post(f"{url}/budget", json={"pct": 80}).status_code == 400
    assert client.get("/api/xline/write/module").json()["max_change_pct"] == 30  # 默认没被改
    # 撤销回到改预算之前
    u = client.post(f"{url}/undo").json()["post"]["trk"]
    assert u.get("max_pct") is None and post_of(client)["trk"]["pct_effective"] == 30


def test_changes_that_do_not_fit_wait_and_come_in_when_the_budget_is_raised(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    def model(prompt: str) -> str:
        if "你在帮 作者 改他自己的一篇长文" in prompt:
            changes = [{"reason": "风格", "op": "delete", "anchor": f"编号{n}不用管", "text": "", "note": "口癖"} for n in "一二三四五"]
            return "<<<JSON>>>\n" + json.dumps({"scores": {}, "changes": changes}, ensure_ascii=False) + "\n<<<END>>>"
        return model_factory([])(prompt)

    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model)
    client.put("/api/xline/write/flow", json={"max_change_pct": 3})
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    t = post_of(client)["trk"]
    assert len(t["changes"]) == 3 and len(t["overflow"]) == 2 and all(c["op"] != "comment" for c in t["changes"])
    r = client.post(f"/api/xline/daily/{key}/{pid}/trk/budget", json={"pct": 10}).json()
    assert r["added"] == 2 and len(r["post"]["trk"]["changes"]) == 5 and r["post"]["trk"]["overflow"] == []
    u = client.post(f"/api/xline/daily/{key}/{pid}/trk/undo").json()["post"]["trk"]  # 撤销：放进来的又收回去
    assert len(u["changes"]) == 3 and len(u["overflow"]) == 2


def test_close_without_saving_puts_back_how_it_was_when_opened(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    """10/13 作者：批注视图右上角「保存」/「不保存，关闭」。每一下本来就存了；不保存 = 退回打开时的样子（含预算放进来的），
    卡片上写他几点存的。"""
    def model(prompt: str) -> str:
        if "你在帮 作者 改他自己的一篇长文" in prompt:
            changes = [{"reason": "风格", "op": "delete", "anchor": f"编号{n}不用管", "text": "", "note": "口癖"} for n in "一二三四五"]
            return "<<<JSON>>>\n" + json.dumps({"scores": {}, "changes": changes}, ensure_ascii=False) + "\n<<<END>>>"
        return model_factory([])(prompt)

    client, key, pid = setup(client_factory, tmp_path, monkeypatch, model)
    client.put("/api/xline/write/flow", json={"max_change_pct": 3})
    client.app.state.x_long_prep(*x_daily.prep_next(x_daily.path()))
    opened = post_of(client)
    t = opened["trk"]
    snap = {"state": {c["id"]: [c["status"], c.get("edit")] for c in t["changes"]}, "max_pct": t.get("max_pct"), "overflow": t["overflow"]}
    assert not opened.get("trk_saved_at")
    url = f"/api/xline/daily/{key}/{pid}/trk"
    client.post(f"{url}/budget", json={"pct": 10})
    client.post(url, json={"all": "accepted"})
    now = post_of(client)
    assert now["text"] != opened["text"] and now["trk_saved_at"]  # 已经存了，卡片上有时间

    r = client.post(url, json={"all": "restore", "snapshot": snap})
    assert r.status_code == 200
    back = post_of(client)
    assert back["text"] == opened["text"] and len(back["trk"]["changes"]) == 3 and len(back["trk"]["overflow"]) == 2
    assert all(c["status"] == "pending" for c in back["trk"]["changes"]) and back["trk"].get("max_pct") is None
    assert client.post(f"{url}/undo").json()["undone"] == "不保存，退回打开时"  # 退回这一步本身也能撤销

    # 打开时分是新的：退回以后文字和打开时一样，不重打
    x_daily.trk_update(x_daily.path(), key, pid, lambda t: t["scores"].update(after={"痛点": {"score": 85, "why": ""}}, stale=False))
    fresh = post_of(client)["trk"]
    snap2 = {"state": {c["id"]: [c["status"], c.get("edit")] for c in fresh["changes"]}, "max_pct": fresh.get("max_pct"),
             "overflow": fresh["overflow"], "scores_fresh": True}
    client.post(url, json={"all": "reset"})
    assert post_of(client)["trk"]["scores"]["stale"] is True
    client.post(url, json={"all": "restore", "snapshot": snap2})
    t2 = post_of(client)["trk"]
    assert t2["scores"]["stale"] is False and not t2.get("rescoring")
    assert client.post(url, json={"all": "restore", "snapshot": {"state": {}}}).status_code == 400
    assert client.post(url, json={"all": "restore", "snapshot": {"state": {"c1": ["done", None]}}}).status_code == 400
