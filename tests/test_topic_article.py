"""「标题和封面」那篇文章的润色（10/13 作者）：不再整篇重写，走第一轮打分 + 修改清单，批注视图逐条处理；插图跟着段落走。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import topic_article as ta
from content_studio.extras.xline import write_patch as wp
from test_topic_script import BODY, LAST, round1_json
from test_write_module import MANIFEST, make_skill
from test_x_line import client_factory  # noqa: F401 - fixture

FIG1, FIG2 = "![问卷](illustrations/01-q.png)", "![收费](illustrations/02-p.png)"
PARAS = BODY.split("\n\n")
# 两张插图夹在正文里：一张在第二段后面，一张在第五段后面
ARTICLE = "\n\n".join(["# 闭环", *PARAS[:2], FIG1, *PARAS[2:5], FIG2, *PARAS[5:]]) + "\n"


def _trk(text: str = ARTICLE) -> dict:
    base, parts = ta.split(text)
    anchor = "编号二不用管"
    changes = [{"id": "c1", "reason": "风格", "op": "delete", "anchor": anchor, "text": "", "note": "口癖", "start": base.index(anchor),
                "end": base.index(anchor) + len(anchor), "pos": "after", "fresh": False, "downgraded": False, "inline": True,
                "status": "pending", "edit": None, "source": "round1"}]
    return wp.build_trk({"changes": changes, "overflow": [], "scores": {}, "dropped": [], "gate_failures": [], "steps": [], "rules": {}, "budget": 0.0},
                        base, parts, when="2026-10-13T12:00:00+08:00", pct=20)


def test_images_step_aside_and_come_back_after_their_paragraph(tmp_path: Path) -> None:
    base, parts = ta.split(ARTICLE)
    assert FIG1 not in base and FIG2 not in base and base.startswith("# 闭环")  # 模型只看得到正文，碰不到插图
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    assert ta.read(article) is None
    cur = ta.save_new(article, _trk(), original=ARTICLE)
    assert cur["text"] == ARTICLE  # 还没接受任何修改：和原文一模一样
    assert len(list(tmp_path.glob("article.before-polish-*.md"))) == 1  # 原文备份一份
    cur = ta.update(article, lambda t: t["changes"][0].update(status="accepted"), "接受一处")
    paras = cur["text"].strip().split("\n\n")
    assert "编号二不用管" not in cur["text"] and article.read_text(encoding="utf-8") == cur["text"]
    assert paras[3] == FIG1 and paras[7] == FIG2  # 改了第二段，图还在它后面


def test_the_list_is_void_once_the_article_was_changed_elsewhere(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    ta.save_new(article, _trk(), original=ARTICLE)
    article.write_text(ARTICLE.replace("# 闭环", "# 闭环（重写过）"), encoding="utf-8")  # 重写、手动编辑
    assert ta.read(article) is None
    with pytest.raises(ta.ArticleError, match="再点一次润色"):
        ta.update(article, lambda t: None)
    article.write_text(ARTICLE, encoding="utf-8")
    with pytest.raises(ta.ArticleError, match="被改过了"):
        ta.save_new(article, _trk(), original="# 别的\n")


def setup(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    calls: list[str] = []
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(make_skill(tmp_path, MANIFEST)))

    def model(prompt: str) -> str:
        calls.append(prompt)
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
        d = client.get(f"/api/topics/{tid}/polish").json()
        if not d["running"]:
            return d
        time.sleep(0.03)
    raise AssertionError("润色没做完")


def test_polish_proposes_changes_and_never_rewrites_the_article(client_factory, tmp_path, monkeypatch) -> None:  # noqa: F811
    client, topic, calls = setup(client_factory, tmp_path, monkeypatch)
    tid = topic["id"]
    assert client.post(f"/api/topics/{tid}/polish", json={}).status_code == 400  # 还没有文章
    article = tmp_path / "drafts" / f"topic-{tid}" / "article.md"
    article.parent.mkdir(parents=True)
    article.write_text(ARTICLE, encoding="utf-8")
    client.app.state.store.update_topic(tid, article_path=str(article))

    assert client.post(f"/api/topics/{tid}/polish", json={}).json()["started"] is True
    d = wait(client, tid)
    assert d["error"] is None and d["polish"]["text"] == ARTICLE  # 文章一个字没动，只多了一份修改清单
    assert sum("你在帮 作者 改他自己的一篇长文" in c for c in calls) == 1 and FIG1 not in calls[-1]  # 插图不交给模型
    trk = d["polish"]["trk"]
    assert [c["op"] for c in trk["changes"]] == ["move", "delete", "insert"] and trk["source"] == "article" and trk["pct_effective"] == 20

    base = f"/api/topics/{tid}/polish/trk"
    r = client.post(f"{base}/c1", json={"status": "accepted"}).json()["polish"]
    assert r["text"].split("\n\n")[1] == LAST and article.read_text(encoding="utf-8") == r["text"]
    assert FIG1 in r["text"] and FIG2 in r["text"]
    assert client.post(f"{base}/budget", json={"pct": 35}).json()["polish"]["trk"]["max_pct"] == 35
    assert client.post(f"{base}/undo").json()["undone"]

    # 处理过的修改，重来要他确认
    r = client.post(f"/api/topics/{tid}/polish", json={})
    assert r.status_code == 409 and "确定的话再点一次" in r.json()["detail"]
    assert client.post(f"/api/topics/{tid}/polish", json={"force": True}).json()["started"] is True
    assert wait(client, tid)["polish"]["trk"]["changes"][0]["status"] == "pending"

    # 文章在别处改过：清单作废，页面回到「润色」按钮
    article.write_text(ARTICLE + "\n补一句。\n", encoding="utf-8")
    assert client.get(f"/api/topics/{tid}/polish").json()["polish"] is None
    assert client.post(f"{base}/c1", json={"status": "accepted"}).status_code == 400
