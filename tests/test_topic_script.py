"""加工中的口播稿：付息稿 → 口播逐字稿 → 第一轮打分 + 修改清单，处理修改和 X 长文共用一套（10/12 作者）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import topic_script as ts
from test_write_module import MANIFEST, make_skill
from test_x_line import client_factory  # noqa: F401 - fixture

PARAS = [f"第{n}段：我觉得闭环比终局更重要，因为终局大家都看得到，但是短期做不到，所以小闭环先闭，大闭环后闭，编号{n}不用管。" for n in "一二三四五六七八九十"]
LAST = "所以先完成小闭环，再往上叠业务，这就是我的判断。"
BODY = "\n\n".join([*PARAS, LAST])
SCRIPT = f"# 闭环\n\n{BODY}\n"
TOPIC = {"id": 7, "title": "闭环"}


# -- 生成的检查 ------------------------------------------------------------------------------------

def test_a_generated_script_must_be_spoken_prose_in_his_words() -> None:
    ts.check_generated(SCRIPT, blob=BODY)  # 好的
    with pytest.raises(ts.ScriptError, match="太短"):
        ts.check_generated("# 闭环\n\n太短了。", blob=BODY)
    for bad in ("## 小标题\n\n" + BODY, "- 第一\n- 第二\n\n" + BODY, "0:18–0:28 发债\n\n" + BODY, "1. 先说这个\n\n" + BODY, "第一点 先说这个\n\n" + BODY):
        with pytest.raises(ts.ScriptError, match="小标题、列表或时间标注"):
            ts.check_generated("# 闭环\n\n" + bad, blob=BODY)
    with pytest.raises(ts.ScriptError, match="数字或英文词"):
        ts.check_generated("# 闭环\n\n" + BODY + "我已经做了 500 个。", blob=BODY)
    with pytest.raises(ts.ScriptError, match="对不上"):
        ts.check_generated("# 闭环\n\n" + "完全是另外一套说法，模型自己编的东西，和原话没有关系。" * 12, blob=BODY)


def test_generate_retries_once_with_the_reason_then_gives_up() -> None:
    prompts: list[str] = []
    outs = iter(["<<<ARTICLE>>>\n# 闭环\n\n短。\n<<<END>>>", f"<<<ARTICLE>>>\n{SCRIPT}<<<END>>>"])

    def fn(p: str) -> str:
        prompts.append(p)
        return next(outs)

    text = ts.generate(TOPIC, coupon=BODY, skeleton="", sources=[], style_rules="1. 先给结论。", write_fn=fn)
    assert text.startswith("# 闭环") and len(prompts) == 2 and "上一次有问题" in prompts[1] and "太短" in prompts[1]
    assert "先给结论" in prompts[0] and "不要小标题、不要列表" in prompts[0] and "付息稿（时间线" in prompts[0]
    with pytest.raises(ts.ScriptError, match="没写成"):
        ts.generate(TOPIC, coupon=BODY, skeleton="", sources=[], style_rules="", write_fn=lambda p: "没有标记", attempts=1)


def test_pasted_text_is_the_original_it_gets_a_title_line_and_is_not_rewritten() -> None:
    assert ts.base_from("闭环", "就是我自己写的一段话。") == "# 闭环\n\n就是我自己写的一段话。\n"
    assert ts.base_from("闭环", "# 他自己的标题\n\n正文") == "# 他自己的标题\n\n正文\n"
    assert ts.parts_for("# 闭环\n\n正文\n") == {"title": "# 闭环", "summary": None, "images": []}


# -- 存储 ----------------------------------------------------------------------------------------

def _trk(base: str = SCRIPT):
    from content_studio.extras.xline import write_patch as wp

    changes = [{"id": "c1", "reason": "风格", "op": "delete", "anchor": "编号二不用管", "text": "", "note": "口癖", "start": base.index("编号二不用管"),
                "end": base.index("编号二不用管") + 6, "pos": "after", "fresh": False, "downgraded": False, "inline": True, "status": "pending", "edit": None, "source": "round1"},
               {"id": "c2", "reason": "稀缺", "op": "insert", "anchor": "编号四不用管", "text": "这件事是我亲自做的。", "note": "x", "start": base.index("编号四不用管"),
                "end": base.index("编号四不用管") + 6, "pos": "after", "fresh": True, "downgraded": False, "inline": True, "status": "pending", "edit": None, "source": "round1"}]
    return wp.build_trk({"changes": changes, "overflow": [], "scores": {"高密度": {"score": 60, "why": ""}}, "dropped": [], "gate_failures": [],
                         "steps": [], "rules": {}, "budget": 0.0}, base, ts.parts_for(base), when="2026-10-12T12:00:00+08:00", pct=20)


def test_the_file_is_always_the_original_plus_what_he_accepted(tmp_path: Path) -> None:
    assert ts.read(tmp_path, 7) is None
    ts.save_new(tmp_path, 7, _trk())
    assert (tmp_path / "topic-7" / "script.md").read_text(encoding="utf-8") == SCRIPT
    cur = ts.update(tmp_path, 7, lambda t: t["changes"][0].update(status="accepted"), "接受一处")
    assert "编号二不用管" not in cur["text"] and (tmp_path / "topic-7" / "script.md").read_text(encoding="utf-8") == cur["text"]
    assert cur["trk"]["history"][-1]["label"] == "接受一处" and cur["trk"]["budget"] > 0
    # 撤销：文字和文件一起回去
    from content_studio.extras.xline import write_patch as wp
    cur = ts.update(tmp_path, 7, lambda t: wp.undo(t))
    assert cur["text"] == SCRIPT and (tmp_path / "topic-7" / "script.md").read_text(encoding="utf-8") == SCRIPT
    # 改后的分是上一版文字打的：文字变了就标过期
    cur = ts.update(tmp_path, 7, lambda t: t["scores"].update(after={"高密度": {"score": 70, "why": ""}}))
    cur = ts.update(tmp_path, 7, lambda t: t["changes"][1].update(status="accepted"), "接受一处")
    assert cur["trk"]["scores"]["stale"] is True
    with pytest.raises(ts.ScriptError, match="还没有口播稿"):
        ts.update(tmp_path, 99, lambda t: None)


# -- 页面接口 ------------------------------------------------------------------------------------

def round1_json() -> str:
    changes = [{"reason": "开头", "op": "move", "anchor": LAST, "text": "", "note": "判断提前"},
               {"reason": "风格", "op": "delete", "anchor": "编号二不用管", "text": "", "note": "口癖"},
               {"reason": "稀缺", "op": "insert", "anchor": "编号四不用管", "text": "这件事是我亲自做的。", "note": "点明是你"}]
    scores = {k: {"score": v, "why": "x"} for k, v in {"高密度": 60, "痛点": 55, "利他": 70, "完整度": 85, "共鸣": 40, "稀缺": 50}.items()}
    return "<<<JSON>>>\n" + json.dumps({"scores": scores, "changes": changes}, ensure_ascii=False) + "\n<<<END>>>"


def setup(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[str] | None = None):  # noqa: F811
    calls = calls if calls is not None else []
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(make_skill(tmp_path, MANIFEST)))

    def model(prompt: str) -> str:
        calls.append(prompt)
        if "整理成「口播逐字稿」" in prompt:
            return f"<<<ARTICLE>>>\n{SCRIPT}<<<END>>>"
        if "你在帮 作者 改他自己的一篇长文" in prompt:
            return round1_json()
        if "重新打分" in prompt:
            return "<<<JSON>>>\n" + json.dumps({"scores": {"高密度": {"score": 78, "why": "好了"}}}, ensure_ascii=False) + "\n<<<END>>>"
        return ""

    client: TestClient = client_factory(write_fn=model, drafts_dir=tmp_path / "drafts", x_fetch_fn=lambda url: [] if "manifest" in url else {})
    topic = client.post("/api/topics", json={"title": "闭环", "formats": "video"}).json()
    return client, topic, calls


def wait(client: TestClient, tid: int) -> dict:
    for _ in range(300):
        d = client.get(f"/api/topics/{tid}/script").json()
        if not d["running"]:
            return d
        time.sleep(0.03)
    raise AssertionError("口播稿没做完")


def put_coupon(tmp_path: Path, tid: int) -> None:
    (tmp_path / "drafts" / f"topic-{tid}").mkdir(parents=True, exist_ok=True)
    (tmp_path / "drafts" / f"topic-{tid}" / "coupon.md").write_text("# 闭环\n\n" + BODY + "\n", encoding="utf-8")


def test_script_from_the_coupon_then_changes_are_handled_like_on_x(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, topic, calls = setup(client_factory, tmp_path, monkeypatch)
    tid = topic["id"]
    d = client.get(f"/api/topics/{tid}/script").json()
    assert d["script"] is None and d["has"] == {"note": False, "coupon": False, "skeleton": False, "transcript": False} and d["available"] is True
    assert d["mode"]["mode"] == "draft" and d["mode"]["auto"] is True
    assert client.post(f"/api/topics/{tid}/script", json={"source": "coupon"}).json()["started"] is True
    d = wait(client, tid)
    assert d["error"] and "先写骨架" in d["error"]  # 还没有付息稿和骨架

    put_coupon(tmp_path, tid)
    client.post(f"/api/topics/{tid}/script", json={"source": "coupon"})
    d = wait(client, tid)
    assert d["error"] is None and d["script"]["text"] == SCRIPT  # 修改没处理之前，就是整理出来的口播稿
    trk = d["script"]["trk"]
    assert [c["op"] for c in trk["changes"]] == ["move", "delete", "insert"] and trk["pct_effective"] == 20 and trk["source"] == "coupon"
    assert sum("整理成「口播逐字稿」" in c for c in calls) == 1 and sum("你在帮 作者 改他自己的一篇长文" in c for c in calls) == 1

    base = f"/api/topics/{tid}/script/trk"
    r = client.post(f"{base}/c1", json={"status": "accepted"}).json()["script"]
    assert r["text"].split("\n\n")[1] == LAST
    assert (tmp_path / "drafts" / f"topic-{tid}" / "script.md").read_text(encoding="utf-8") == r["text"]
    client.post(f"{base}/c2", json={"status": "edited", "edit": "我先做了一遍。"})
    client.post(base, json={"all": "accepted"})  # 处理完了：自己开始打分
    for _ in range(200):
        s = client.get(f"/api/topics/{tid}/script").json()["script"]["trk"]["scores"]
        if s.get("after"):
            break
        time.sleep(0.03)
    assert s["after"]["高密度"]["score"] == 78 and s["stale"] is False
    u = client.post(f"{base}/undo").json()
    assert u["undone"] == "全部接受" and client.get(f"/api/topics/{tid}/script").json()["script"]["trk"]["scores"]["stale"] is True
    b = client.post(f"{base}/budget", json={"pct": 35}).json()
    assert b["script"]["trk"]["max_pct"] == 35 and client.post(f"{base}/budget", json={"pct": 99}).status_code == 400
    assert client.post(f"{base}/c9", json={"status": "accepted"}).status_code == 400


def test_regenerating_never_silently_wipes_what_he_handled(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, topic, _ = setup(client_factory, tmp_path, monkeypatch)
    tid = topic["id"]
    put_coupon(tmp_path, tid)
    client.post(f"/api/topics/{tid}/script", json={"source": "coupon"})
    wait(client, tid)
    client.post(f"/api/topics/{tid}/script/trk/c1", json={"status": "accepted"})
    r = client.post(f"/api/topics/{tid}/script", json={"source": "coupon"})
    assert r.status_code == 409 and "清掉你已经处理的 1 处" in r.json()["detail"]
    assert client.post(f"/api/topics/{tid}/script", json={"source": "coupon", "force": True}).json()["started"] is True
    d = wait(client, tid)
    assert d["script"]["trk"]["changes"][0]["status"] == "pending"
    folder = tmp_path / "drafts" / f"topic-{tid}"
    assert (folder / "script.md.bak").is_file() and (folder / "script.trk.json.bak").is_file()  # 旧的留了备份


def test_his_own_pasted_script_is_not_rewritten_and_short_ones_are_refused(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    client, topic, calls = setup(client_factory, tmp_path, monkeypatch, calls)
    tid = topic["id"]
    client.post(f"/api/topics/{tid}/script", json={"source": "paste", "text": "太短了"})
    assert "不到 200 字" in wait(client, tid)["error"]
    client.post(f"/api/topics/{tid}/script", json={"source": "paste", "text": BODY})
    d = wait(client, tid)
    assert d["error"] is None and d["script"]["text"] == f"# 闭环\n\n{BODY}\n" and d["script"]["trk"]["source"] == "paste"
    assert not any("整理成「口播逐字稿」" in c for c in calls)  # 他自己的稿子：不重写，直接第一轮
    assert client.post(f"/api/topics/{tid}/script", json={"source": "乱"}).status_code == 400
    assert client.get("/api/topics/99999/script").status_code == 404


def test_transcript_source_uses_the_recorded_words_and_says_so_when_there_are_none(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, topic, _ = setup(client_factory, tmp_path, monkeypatch)
    tid = topic["id"]
    client.post(f"/api/topics/{tid}/script", json={"source": "transcript"})
    assert "还没有转写的逐字稿" in wait(client, tid)["error"]
    # 补发的旧视频：拆解时转写的逐字稿在下载目录里
    client.app.state.store.update_topic(tid, published_video_id="7000001")
    folder = tmp_path / "dl" / "douyin" / "acct" / "7000001"
    folder.mkdir(parents=True)
    (folder / "transcript.json").write_text(json.dumps({"full_text": BODY}, ensure_ascii=False), encoding="utf-8")
    assert client.get(f"/api/topics/{tid}/script").json()["has"]["transcript"] is True
    client.post(f"/api/topics/{tid}/script", json={"source": "transcript"})
    d = wait(client, tid)
    assert d["error"] is None and d["script"]["trk"]["source"] == "transcript" and d["script"]["text"] == f"# 闭环\n\n{BODY}\n"



# -- 10/12 作者：已经有自己的话的内容，不走骨架、密度，原话直接走第一轮 ---------------------------------------------

def own_topic(client: TestClient, tmp_path: Path) -> dict:
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True, exist_ok=True)
    (vault / "003_原始输出" / "闭环.md").write_text("---\ndate: 2026-10-11\n---\n" + BODY + "\n", encoding="utf-8")
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    return client.post("/api/topics", json={"title": "闭环", "formats": "video", "note_paths": ["003_原始输出/闭环.md"]}).json()


def test_his_own_note_is_the_base_word_for_word_and_the_mode_is_own(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    client, _, calls = setup(client_factory, tmp_path, monkeypatch, calls)
    topic = own_topic(client, tmp_path)
    tid = topic["id"]
    listed = next(t for t in client.get("/api/topics").json() if t["id"] == tid)
    assert listed["content_mode"] == {"mode": "own", "auto": True, "why": "挂了你原始输出里的笔记"}
    d = client.get(f"/api/topics/{tid}/script").json()
    assert d["has"]["note"] is True and d["mode"]["mode"] == "own"
    client.post(f"/api/topics/{tid}/script", json={"source": "note"})
    d = wait(client, tid)
    assert d["error"] is None and d["script"]["text"] == f"# 闭环\n\n{BODY}\n" and d["script"]["trk"]["source"] == "note"  # 一个字没少
    assert not any("整理成「口播逐字稿」" in c for c in calls)  # 不重写
    # 他可以改判断：改成「还没有」，再改回自动
    r = client.put(f"/api/topics/{tid}/mode", json={"mode": "draft"}).json()["content_mode"]
    assert r == {"mode": "draft", "auto": False, "why": "你在这条内容上选的"}
    assert client.put(f"/api/topics/{tid}/mode", json={"mode": "auto"}).json()["content_mode"]["mode"] == "own"
    assert client.put(f"/api/topics/{tid}/mode", json={"mode": "乱"}).status_code == 400


def test_the_archive_line_in_a_spoken_note_never_reaches_the_script(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    """10/13：口述存档的笔记里夹着一行「下面每一句都是我自己说的话」，那是给骨架看的标记，不是他念的话。"""
    client, _, calls = setup(client_factory, tmp_path, monkeypatch, [])
    topic = own_topic(client, tmp_path)
    note = tmp_path / "vault" / "003_原始输出" / "闭环.md"
    note.write_text("---\ntype: 原始输出\n---\n\n# 闭环\n\n> 下面每一句都是我（作者）自己说的话，是我自己的经历和判断。别人的材料只是话题，里面的话一句都没用。\n\n" + BODY + "\n", encoding="utf-8")
    client.post(f"/api/topics/{topic['id']}/script", json={"source": "note"})
    d = wait(client, topic["id"])
    assert d["error"] is None and "下面每一句" not in d["script"]["text"] and BODY in d["script"]["text"]


def test_the_schedule_batch_prepares_scripts_for_own_words_and_writes_no_skeleton(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    client, _, calls = setup(client_factory, tmp_path, monkeypatch, calls)
    topic = own_topic(client, tmp_path)
    tid = topic["id"]
    store = client.app.state.store
    store.set_focus(tid)
    d = client.get("/api/schedule").json()
    pack = next(p for p in [*d["pool"], *[q["pack"] for q in d["queue"] if q.get("pack")]] if p["id"] == tid)
    assert pack["own"] is True and pack["script"] is False
    r = client.post("/api/schedule/write").json()
    assert r["started"] is True
    for _ in range(300):
        job = client.get("/api/schedule").json()["write"]["job"]
        if job and not job["running"]:
            break
        time.sleep(0.03)
    assert job["wrote"] == 1 and job["failed"] == [], job
    assert (tmp_path / "drafts" / f"topic-{tid}" / "script.md").is_file()
    assert not any("骨架" in c[:200] and "<<<" in c for c in calls if "整理成「口播逐字稿」" not in c and "你在帮 作者 改他自己的一篇长文" not in c and "重新打分" not in c)
    assert store.topic(tid).get("outline_path") is None and not (tmp_path / "drafts" / f"topic-{tid}" / "coupon.md").exists()


def test_without_the_writing_module_the_old_skeleton_path_stays(tmp_path: Path) -> None:
    from content_studio import schedule

    t = {"id": 3, "note_paths": ["003_原始输出/a.md"]}
    drafts = tmp_path / "drafts"
    assert schedule.targets([t], [3], "003_原始输出", drafts, script=False)["ids"] == [3]   # 老路：写骨架
    assert schedule.targets([t], [3], "003_原始输出", drafts, script=True)["ids"] == [3]    # 新路：准备口播稿
    (drafts / "topic-3").mkdir(parents=True)
    (drafts / "topic-3" / "script.md").write_text("x", encoding="utf-8")
    assert schedule.targets([t], [3], "003_原始输出", drafts, script=True)["ids"] == []     # 已经有了不重来
    schedule.set_mode(drafts, 3, "draft")
    assert schedule.targets([t], [3], "003_原始输出", drafts, script=True)["ids"] == [3]    # 他改成「还没有」：照老路写骨架
    assert schedule.content_mode({"id": 4, "note_paths": [], "video_project": "v1"}, "003_原始输出", drafts)["mode"] == "own"
    assert schedule.content_mode({"id": 5, "note_paths": ["002_对标内容/x.md"]}, "003_原始输出", drafts)["mode"] == "draft"
