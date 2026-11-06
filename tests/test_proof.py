"""拍之前的证据（10/5 作者）：按骨架的论点找新闻、数据、原推，逐条核对；他自己的截图他传；点「要」的才算数。"""
from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from content_studio.extras.proof import proof
from content_studio.extras.proof.evidence import EvidenceError
from tests.test_web import client  # noqa: F401 - fixture

SKELETON = """# 0人工，AI能自己赚钱？

## 主线
大多数人说的「AI 赚钱」只走到了第一步。

## 开头候选
1. 你现在看到的「AI 自动赚钱」，几乎没有一个是 AI 自己赚的。

## 中间骨架

### 论点 A：大多数「AI 赚钱」的截图，停在生成这一步
证据：要补 —— 找 3 张你刷到过的「AI 自动赚钱」帖子截图。

### 论点 B：被使用、产生收入，是 AI 最接不住的两步
证据：要补 —— 去后台截一张「近 30 天收入构成」的图。

### 论点 C：大模型越来越便宜
证据：素材里有：价格一年降了九成。

## 结尾
钱从谁口袋里出，这一步还得你自己来。
"""

ANSWER = """```json
{"points": [
  {"key": "A", "found": [
     {"kind": "news", "url": "https://www.example-news.com/a/1", "source": "某某新闻", "date": "2026-03-01",
      "quote": "报告显示，九成自称 AI 自动赚钱的账号没有真实收入", "claim": "停在生成这一步", "caption": "某某新闻 3 月的报道"},
     {"kind": "news", "url": "https://example-news.com/a/2", "source": "某某新闻", "date": "",
      "quote": "同一家媒体的第二篇报道里也这么说", "claim": "x", "caption": "重复来源"}],
   "mine": ""},
  {"key": "B", "found": [
     {"kind": "data", "url": "https://stats.example.org/t", "source": "统计局", "date": "",
      "quote": "这句话页面上根本没有", "claim": "y", "caption": "编的"}],
   "mine": "打开研习室后台，截近 30 天收入构成，圈出私信成交那一块"},
  {"key": "C", "found": [
     {"kind": "tweet", "url": "https://x.com/karpathy/status/123", "screen_name": "karpathy",
      "quote": "the price of intelligence keeps falling", "claim": "越来越便宜", "caption": "Karpathy 2025 年"}],
   "mine": ""}
]}
```"""

PAGES = {"https://www.example-news.com/a/1": "报告显示，九成自称 AI 自动赚钱的账号没有真实收入。"}


def fake_page(url: str, quote: str, out: Path):
    if not proof.locate(quote, PAGES.get(url, "")):
        return None
    out.write_bytes(b"png")
    return {"title": "报道", "site": "某某新闻网", "date": "2026-03-02"}


def fake_lookup(tid: str):
    return {"text": "The price of intelligence keeps falling, fast.", "user": {"screen_name": "karpathy"},
            "created_at": "2025-06-01T00:00:00.000Z"} if tid == "123" else None


def fake_shot(tid: str, out: Path) -> None:
    out.write_bytes(b"png")


REAL_RUN = proof.run


def _run(base: Path, skeleton: str = SKELETON, answer: str = ANSWER):
    return REAL_RUN(base, "0人工，AI能自己赚钱？", skeleton, now="2026-10-05T10:00:00+08:00",
                     llm=lambda p: answer, page=fake_page, lookup=fake_lookup, shot=fake_shot)


def test_points_come_from_the_middle_of_the_skeleton() -> None:
    pts = proof.points(SKELETON)
    assert [p["key"] for p in pts] == ["A", "B", "C"]
    assert pts[1]["title"] == "被使用、产生收入，是 AI 最接不住的两步"
    assert proof.missing(pts[0]["line"]) and not proof.missing(pts[2]["line"])


def test_only_checked_sources_survive_and_one_outlet_is_used_once(tmp_path: Path) -> None:
    res = _run(tmp_path)
    by = {p["key"]: p for p in res["points"]}
    assert [i["url"] for i in by["A"]["items"]] == ["https://www.example-news.com/a/1"]
    assert by["A"]["items"][0]["date"] == "2026-03-02" and by["A"]["items"][0]["pick"] is None  # 还没点「要」
    assert by["B"]["items"] == []  # 页面上没有那句话：扔掉
    assert by["C"]["items"][0]["kind"] == "tweet" and by["C"]["items"][0]["url"] == "https://x.com/karpathy/status/123"
    whys = {r["caption"]: r["why"] for r in res["rejected"]}
    assert "已经用过" in whys["重复来源"] and "找不到这句原话" in whys["编的"]
    # 只有他能拿的：写成待办，模型没写就用骨架里的「要补」
    assert "研习室后台" in by["B"]["mine"] and by["A"]["mine"].startswith("要补")
    assert (tmp_path / "proof" / by["A"]["items"][0]["file"]).is_file()


def test_a_quote_must_be_on_the_page_word_for_word_except_stray_footnote_marks() -> None:
    page = "Claude's performance review. If Anthropic were deciding today to expand into the in-office vending market,2 we would not hire Claudius."
    assert proof.locate("If Anthropic were deciding today to expand into the in-office vending market, we would not hire Claudius.", page)
    assert proof.locate("we would not hire Claudius", page) == "wewouldnothireclaudius"
    assert proof.locate("If Anthropic were deciding today to expand into the vending market, we would hire Claudius.", page) is None
    assert proof.locate("九成账号没有收入", "报告显示，九成自称 AI 自动赚钱的账号没有真实收入。") is None  # 中间换了说法：不算
    assert proof.locate("we would hire Claudius", page) is None  # 页面上是 would not hire：不能跳过 not
    assert proof.locate("短", "短") is None


def test_the_prompt_says_never_make_things_up_and_names_the_points() -> None:
    prompt = proof.build_prompt("t", SKELETON, proof.points(SKELETON), avoid=["x:naval"])
    assert "绝不编" in prompt and "论点 B：被使用" in prompt and "x:naval" in prompt


def test_a_rerun_keeps_what_he_picked_and_what_he_uploaded(tmp_path: Path) -> None:
    first = _run(tmp_path)
    kept = first["points"][0]["items"][0]["file"]
    proof.pick(tmp_path, kept, True)
    dropped = first["points"][2]["items"][0]["file"]  # 没点「要」的原推
    proof.add_mine(tmp_path, "B", "收入", "后台.png", b"img", now="2026-10-05T10:00:00", read=lambda paths: {p: "近 30 天收入构成" for p in paths})
    again = _run(tmp_path, answer='```json\n{"points": []}\n```')
    by = {p["key"]: p for p in again["points"]}
    assert [i["file"] for i in by["A"]["items"]] == [kept]
    assert [i["kind"] for i in by["B"]["items"]] == ["mine"]
    assert by["C"]["items"] == [] and not (tmp_path / "proof" / dropped).exists()
    assert [i["point"] for i in proof.chosen(tmp_path)] == ["A", "B"]


def test_his_own_screenshot_is_refused_if_it_shows_private_things(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError, match="隐私"):
        proof.add_mine(tmp_path, "B", "收入", "后台.png", b"img", now="2026-10-05", read=lambda paths: {p: "联系 13812345678" for p in paths})
    assert not list((tmp_path / "proof").glob("mine-*"))
    with pytest.raises(EvidenceError, match="只收图片"):
        proof.add_mine(tmp_path, "B", "收入", "录屏.mov", b"x", now="2026-10-05", read=lambda paths: {})


def test_found_evidence_is_never_deleted_only_unpicked(tmp_path: Path) -> None:
    res = _run(tmp_path)
    with pytest.raises(EvidenceError, match="不删"):
        proof.remove(tmp_path, res["points"][0]["items"][0]["file"])


def test_the_view_follows_the_current_skeleton_and_flags_changed_points(tmp_path: Path) -> None:
    _run(tmp_path)
    proof.pick(tmp_path, proof.load(tmp_path)["points"][2]["items"][0]["file"], True)
    edited = SKELETON.replace("### 论点 C：大模型越来越便宜\n证据：素材里有：价格一年降了九成。\n", "### 论点 D：新的\n证据：要补 —— 新的截图\n")
    st = proof.view(tmp_path, edited)
    assert st["stale"] and [p["key"] for p in st["points"]] == ["A", "B", "D", "C"]
    assert st["points"][-1]["gone"] and st["chosen"] == 1
    assert not proof.view(tmp_path, SKELETON)["stale"]


def test_the_skeleton_page_finds_picks_and_takes_uploads_through_the_api(client, tmp_path: Path, monkeypatch) -> None:
    topic = client.post("/api/topics", json={"title": "AI 赚钱"}).json()
    tid = topic["id"]
    assert client.post(f"/api/topics/{tid}/proof").status_code == 400  # 还没骨架
    sk = tmp_path / "drafts" / f"topic-{tid}" / "skeleton.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(SKELETON, encoding="utf-8")
    client.app.state.store.update_topic(tid, outline_path=str(sk))
    st = client.get(f"/api/topics/{tid}/proof").json()
    assert not st["searched"] and [p["key"] for p in st["points"]] == ["A", "B", "C"] and st["points"][0]["missing"]

    monkeypatch.setattr(proof, "run", lambda base, title, skeleton, now: _run(base, skeleton))
    assert client.post(f"/api/topics/{tid}/proof").json()["started"]
    for _ in range(50):
        st = client.get(f"/api/topics/{tid}/proof").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    assert st["searched"] and not st["error"]
    item = st["points"][0]["items"][0]
    assert item["kind_label"] == "新闻" and client.get(item["src"]).status_code == 200
    st = client.post(f"/api/topics/{tid}/proof/pick", json={"file": item["file"], "pick": True}).json()
    assert st["chosen"] == 1

    monkeypatch.setattr(proof, "ocr", lambda paths: {p: "近 30 天收入构成" for p in paths})
    st = client.post(f"/api/topics/{tid}/proof/mine", files={"file": ("后台.png", b"img", "image/png")}, data={"key": "B"}).json()
    mine = st["points"][1]["items"][0]
    assert mine["kind"] == "mine" and mine["pick"] and st["chosen"] == 2
    st = client.post(f"/api/topics/{tid}/proof/remove", json={"file": mine["file"]}).json()
    assert st["chosen"] == 1
    assert client.get(f"/api/topics/{tid}/proof-file/..%2Fskeleton.md").status_code == 404
    assert json.loads((tmp_path / "drafts" / f"topic-{tid}" / "proof" / "proof.json").read_text())["points"]


def test_what_he_picks_or_uploads_while_the_search_runs_survives_it(tmp_path: Path) -> None:
    """找要 3–8 分钟，页面上说「可以先做别的」：这期间点的「要」、传的截图，找完不能被开跑前的旧快照冲掉。"""
    first = _run(tmp_path)
    keep = first["points"][2]["items"][0]["file"]  # 上一轮的原推

    def llm(prompt: str) -> str:
        proof.pick(tmp_path, keep, True)
        proof.add_mine(tmp_path, "B", "收入", "后台.png", b"img2", now="2026-10-05", read=lambda paths: {p: "收入" for p in paths})
        return '```json\n{"points": []}\n```'

    res = REAL_RUN(tmp_path, "t", SKELETON, now="2026-10-05", llm=llm, page=fake_page, lookup=fake_lookup, shot=fake_shot)
    by = {p["key"]: p for p in res["points"]}
    assert [i["file"] for i in by["C"]["items"]] == [keep] and (tmp_path / "proof" / keep).is_file()
    mine = [i for i in by["B"]["items"] if i["kind"] == "mine"]
    assert len(mine) == 1 and (tmp_path / "proof" / mine[0]["file"]).is_file()


def test_articles_on_one_platform_by_different_authors_are_different_sources() -> None:
    a = {"url": "https://mp.weixin.qq.com/s/abc", "source": "晚点 LatePost"}
    b = {"url": "https://mp.weixin.qq.com/s/xyz", "source": "36氪"}
    assert proof.source_key(a) != proof.source_key(b)
    assert proof.source_key(a) == proof.source_key({**a, "url": "https://mp.weixin.qq.com/s/other"})
    assert proof.source_key({"url": "https://www.reuters.com/a"}) == proof.source_key({"url": "https://reuters.com/b", "source": "x"})
    assert proof.source_key({"url": "https://x.com/naval/status/1"}) == "x:naval"


def test_an_iphone_heic_screenshot_is_turned_into_png(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(proof, "to_png", lambda src, dest: dest.write_bytes(b"png"))
    item = proof.add_mine(tmp_path, "B", "收入", "IMG_0001.HEIC", b"heic", now="2026-10-05", read=lambda paths: {p: "收入" for p in paths})
    assert item["file"].endswith(".png") and (tmp_path / "proof" / item["file"]).is_file()
    assert not list((tmp_path / "proof").glob("*.heic"))

    def broken(src, dest):
        raise EvidenceError("这张 HEIC 转不成 PNG")

    monkeypatch.setattr(proof, "to_png", broken)
    with pytest.raises(EvidenceError, match="HEIC"):
        proof.add_mine(tmp_path, "B", "收入", "IMG_0002.heic", b"heic2", now="2026-10-05", read=lambda paths: {})
    assert not list((tmp_path / "proof").glob("*.heic"))


def test_picking_and_uploading_wait_until_the_search_is_done(client, tmp_path: Path, monkeypatch) -> None:
    import threading

    topic = client.post("/api/topics", json={"title": "AI 赚钱"}).json()
    tid = topic["id"]
    sk = tmp_path / "drafts" / f"topic-{tid}" / "skeleton.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(SKELETON, encoding="utf-8")
    client.app.state.store.update_topic(tid, outline_path=str(sk))
    gate = threading.Event()
    monkeypatch.setattr(proof, "run", lambda base, title, skeleton, now: gate.wait(5) and _run(base, skeleton))
    assert client.post(f"/api/topics/{tid}/proof").json()["started"]
    r = client.post(f"/api/topics/{tid}/proof/pick", json={"file": "x.png", "pick": True})
    assert r.status_code == 400 and "找完再挑" in r.json()["error"]
    assert client.post(f"/api/topics/{tid}/proof/mine", files={"file": ("a.png", b"img", "image/png")}, data={"key": "B"}).status_code == 400
    gate.set()
    for _ in range(50):
        if not client.get(f"/api/topics/{tid}/proof").json()["running"]:
            break
        time.sleep(0.05)
    assert client.get(f"/api/topics/{tid}/proof").json()["searched"]


# -- 证据单（10/9 作者 在流程板上拍的）-------------------------------------------------------

SHEET = """```json
{"own": true, "points": [
  {"key": "A", "use": "outside", "why": "外面有报道", "found": [
     {"kind": "news", "url": "https://www.example-news.com/a/1", "source": "某某新闻", "date": "",
      "quote": "报告显示，九成自称 AI 自动赚钱的账号没有真实收入", "claim": "x", "caption": "报道"}], "mine": ""},
  {"key": "B", "use": "mine", "why": "讲的是他自己的后台", "found": [], "mine": "打开工作台「汇总」页，截近 30 天收入，圈出私信成交"},
  {"key": "C", "found": [], "mine": ""}
]}
```"""


def test_every_point_gets_one_way_to_prove_it_and_a_piece_about_himself_is_screenshot_first(tmp_path: Path) -> None:
    res = _run(tmp_path, answer=SHEET)
    by = {p["key"]: p for p in res["points"]}
    assert res["own"] and res["sheet"]
    assert by["A"]["use"] == "outside" and by["B"]["use"] == "mine"
    assert by["C"]["use"] == "illustration"  # 模型没给：没待办、没找到 → 只能画插图
    prompt = proof.build_prompt("t", SKELETON, proof.points(SKELETON))
    assert "工作台的页面也是他自己截" in prompt and '"own"' in prompt and "第一个答「是」就停" in prompt


def test_old_answers_without_a_sheet_still_get_one_by_the_same_order() -> None:
    assert proof.decide({"found": [], "mine": "去后台截"}) == "mine"
    assert proof.decide({"found": [{"url": "u"}], "mine": ""}) == "outside"
    assert proof.decide({"found": [], "mine": "", "use": "nonsense"}) == "illustration"


def test_what_he_sets_for_a_point_survives_a_rerun(tmp_path: Path) -> None:
    _run(tmp_path, answer=SHEET)
    proof.set_use(tmp_path, "B", "被使用、产生收入", "none")
    res = _run(tmp_path, answer=SHEET)
    b = next(p for p in res["points"] if p["key"] == "B")
    assert b["use"] == "none" and b["use_by"] == "park"
    with pytest.raises(EvidenceError):
        proof.set_use(tmp_path, "B", "x", "ai-picture")


def test_a_missing_screenshot_holds_publishing_until_uploaded_or_changed(tmp_path: Path) -> None:
    assert proof.missing_shots(tmp_path, SKELETON) == []  # 没有证据单的老选题不卡
    _run(tmp_path)  # 老格式回答：A、B 骨架里写着「要补」、B 有待办 → 都算截图
    assert [p["key"] for p in proof.missing_shots(tmp_path, SKELETON)] == ["A", "B"]
    _run(tmp_path, answer=SHEET)
    assert [p["key"] for p in proof.missing_shots(tmp_path, SKELETON)] == ["B"]
    proof.add_mine(tmp_path, "B", "收入", "后台.png", b"img", now="2026-10-09", read=lambda paths: {p: "收入" for p in paths})
    assert proof.missing_shots(tmp_path, SKELETON) == []


def test_illustrations_only_go_to_concept_points(tmp_path: Path) -> None:
    assert proof.illustration_plan(tmp_path, SKELETON) is None
    _run(tmp_path, answer=SHEET)
    plan = proof.illustration_plan(tmp_path, SKELETON)
    assert plan == {"draw": ["大模型越来越便宜"], "skip": ["大多数「AI 赚钱」的截图，停在生成这一步", "被使用、产生收入，是 AI 最接不住的两步"]}


def test_the_point_for_today_starts_its_sheet_by_itself_once(client, tmp_path: Path, monkeypatch) -> None:
    store = client.app.state.store
    tid = client.post("/api/topics", json={"title": "AI 赚钱"}).json()["id"]
    once = client.app.state.auto_proof_once
    assert once() is None  # 没有正在做的
    store.set_focus(tid)
    assert once() is None  # 还没骨架
    sk = tmp_path / "drafts" / f"topic-{tid}" / "skeleton.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(SKELETON, encoding="utf-8")
    store.update_topic(tid, outline_path=str(sk))
    monkeypatch.setattr(proof, "run", lambda base, title, skeleton, now: _run(base, skeleton, SHEET))
    assert once() == tid
    for _ in range(50):
        st = client.get(f"/api/topics/{tid}/proof").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    assert st["sheet"] and st["own"]
    assert once() is None  # 找过了就不再自己跑

    hold = client.app.state.proof_hold(tid)
    assert "论点 B" in hold and "截图" in hold
    st = client.post(f"/api/topics/{tid}/proof/use", json={"key": "B", "use": "outside"}).json()
    assert next(p for p in st["points"] if p["key"] == "B")["use_by"] == "park"
    assert client.app.state.proof_hold(tid) == ""
    assert client.post(f"/api/topics/{tid}/proof/use", json={"key": "Z", "use": "mine"}).status_code == 400


def test_screenshots_must_reach_the_article_and_shot_topics_never_start_by_themselves(client, tmp_path: Path, monkeypatch) -> None:
    """截图都传了、还没放进文章：照样先不发（整篇截图优先时 AI 插图已经拿掉，不能一张图都没有就发）。
    已经接上视频项目的那条，上线也不会自己出证据单、被卡住。"""
    from content_studio.extras.proof import evidence

    store = client.app.state.store
    tid = client.post("/api/topics", json={"title": "工作台"}).json()["id"]
    base = tmp_path / "drafts" / f"topic-{tid}"
    sk = base / "skeleton.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(SKELETON, encoding="utf-8")
    art = base / "article.md"
    art.write_text("# 工作台\n\n正文。\n", encoding="utf-8")
    store.update_topic(tid, outline_path=str(sk), article_path=str(art), video_project="2026-10-09 工作台")
    store.set_focus(tid)
    assert client.app.state.auto_proof_once() is None

    _run(base, answer=SHEET)
    proof.add_mine(base, "B", "收入", "后台.png", b"img", now="2026-10-09", read=lambda paths: {p: "收入" for p in paths})
    assert "放进文章" in client.app.state.proof_hold(tid)
    monkeypatch.setattr(evidence, "status", lambda article: {"state": "skipped"})
    assert client.app.state.proof_hold(tid) == ""
