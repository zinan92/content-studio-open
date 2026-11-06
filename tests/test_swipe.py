"""流量视频：贴链接就下到本机存一张卡片；「开始复刻」才变成选题（9/30 作者）。"""
from __future__ import annotations

import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio import swipe
from tests.test_web import client  # noqa: F401 - fixture


def test_clean_url_knows_the_three_platforms_and_refuses_the_rest() -> None:
    assert swipe.clean_url("看这个 https://v.douyin.com/abc123/ 复制此链接")[1] == "douyin"
    assert swipe.clean_url("https://x.com/someone/status/1234567890")[1] == "x"
    assert swipe.clean_url("https://www.xiaohongshu.com/explore/abcdef")[1] == "xiaohongshu"
    # 在主页里点开的视频：账号主页 + modal_id → 换成单条视频的地址，不能把整个主页交给下载工具
    assert swipe.clean_url("https://www.douyin.com/user/MS4wLjABAAAAK1pk?from_tab_name=main&modal_id=7690973351082881939") == (
        "https://www.douyin.com/video/7690973351082881939", "douyin")
    assert swipe.clean_url("https://www.douyin.com/video/7690973351082881939?previous_page=app")[0] == "https://www.douyin.com/video/7690973351082881939"
    with pytest.raises(swipe.SwipeError, match="账号主页"):
        swipe.clean_url("https://www.douyin.com/user/MS4wLjABAAAA")
    with pytest.raises(swipe.SwipeError, match="认得的是"):
        swipe.clean_url("https://www.youtube.com/watch?v=abc")
    with pytest.raises(swipe.SwipeError, match="贴一个"):
        swipe.clean_url("  ")


def _fake_download(tmp_path: Path):
    def download(url: str, platform: str, *, out_dir: Path, cookies):
        folder = out_dir / platform / "author" / "vid1"
        (folder / "media").mkdir(parents=True, exist_ok=True)
        (folder / "media" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        (folder / "media" / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        (folder / "content_item.json").write_text(json.dumps({
            "platform": platform, "content_id": "vid1", "title": "Opus 5.5 做的 15 种风格", "author_name": "Vincent",
            "media_files": ["media/video.mp4"], "cover_file": "media/cover.jpg", "likes": "12000", "collects": 3400, "shares": "900",
        }), encoding="utf-8")
        return folder
    return download


def _wait(client: TestClient, swipe_id: int) -> dict:
    for _ in range(100):
        v = next(x for x in client.get("/api/swipe").json()["videos"] if x["id"] == swipe_id)
        if v["status"] != "downloading":
            return v
        time.sleep(0.02)
    raise AssertionError("download did not finish")


def test_paste_a_link_saves_a_card_and_start_makes_a_topic(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(swipe, "download", _fake_download(tmp_path))
    res = client.post("/api/swipe", json={"url": "https://x.com/vincent/status/1234567890"})
    assert res.status_code == 200
    v = _wait(client, res.json()["video"]["id"])
    assert v["status"] == "saved" and v["title"] == "Opus 5.5 做的 15 种风格" and v["likes"] == 12000 and v["collects"] == 3400
    assert client.get(v["cover"]).status_code == 200 and client.get(v["video"]).status_code == 200
    # 同一条不存两遍
    assert client.post("/api/swipe", json={"url": "https://x.com/vincent/status/1234567890"}).status_code == 400

    client.patch(f"/api/swipe/{v['id']}", json={"note": "一个人做出广告公司的片子", "collection": "一个人加 AI 做成的"})
    assert client.patch(f"/api/swipe/{v['id']}", json={"collection": "随便写的"}).status_code == 400

    topic = client.post(f"/api/swipe/{v['id']}/start").json()["topic"]
    assert topic["title"].startswith("复刻：Opus 5.5") and "一个人做出广告公司的片子" in topic["memo"]
    v = next(x for x in client.get("/api/swipe").json()["videos"] if x["id"] == v["id"])
    assert v["status"] == "making" and v["topic"]["id"] == topic["id"]
    # 出现在「今天」的「接下来要拍的」最上面；再点一次不会建第二条
    notes = client.get("/api/today").json()["ship"]["notes"]
    assert notes[0]["topic_id"] == topic["id"]
    assert client.post(f"/api/swipe/{v['id']}/start").json()["topic"]["id"] == topic["id"]

    assert client.delete(f"/api/swipe/{v['id']}").status_code == 200
    assert client.get("/api/swipe").json()["videos"] == []
    assert not (tmp_path / "data" / "swipe" / "x" / "author" / "vid1").exists()


def test_douyin_links_are_capped_per_day_and_failures_can_retry(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(url, platform, *, out_dir, cookies):
        calls["n"] += 1
        if calls["n"] == 1:
            raise swipe.SwipeError("没下下来：抖音拒绝了")
        return _fake_download(tmp_path)(url, platform, out_dir=out_dir, cookies=cookies)

    monkeypatch.setattr(swipe, "download", flaky)
    first = client.post("/api/swipe", json={"url": "https://www.douyin.com/video/7000000000000000001"}).json()["video"]
    v = _wait(client, first["id"])
    assert v["status"] == "failed" and "抖音拒绝了" in v["error"]
    client.post(f"/api/swipe/{v['id']}/retry")
    assert _wait(client, v["id"])["status"] == "saved"
    for i in range(2, swipe.DOUYIN_DAILY_CAP + 1):
        assert client.post("/api/swipe", json={"url": f"https://www.douyin.com/video/700000000000000000{i}"}).status_code == 200
    over = client.post("/api/swipe", json={"url": "https://www.douyin.com/video/7000000000000000099"})
    assert over.status_code == 400 and "明天再存" in over.json()["error"]
    assert client.get("/api/swipe").json()["douyin_left"] == 0
    # X 不走抖音登录，不受这个上限
    last = client.post("/api/swipe", json={"url": "https://x.com/a/status/1"})
    assert last.status_code == 200
    # 下载线程必须在 fixture 关闭数据库、撤回 monkeypatch 前结束。
    # 等最后一条不够：前面并行下载的几条也可能仍在写库。
    import threading
    for thread in threading.enumerate():
        if thread.name.startswith("swipe-"):
            thread.join(timeout=5)
            assert not thread.is_alive(), thread.name


def test_stylesheet_still_has_every_page(tmp_path: Path) -> None:
    """9/30：另一个改动把 styles.css 后面 362 行截掉了，今天页、咨询、概览、打包的样式全没了，测试却全过。
    每一页挑一个选择器守着：少了哪个，就是样式文件又被截了。"""
    css = (Path(__file__).resolve().parents[1] / "src/content_studio/static/styles.css").read_text(encoding="utf-8")
    for selector in (".ri", ".td-row", ".td-pack", ".pp-item", ".ov-core", ".pk-row", ".mx-wrap", ".mx-dot", ".k-svg path.l", ".sw-card", ".fd-row", ".pf-var"):
        assert selector in css, f"styles.css 里没有 {selector}"
    assert css.count("{") == css.count("}")


def test_feed_lists_new_posts_by_teacher_and_benchmark_and_marks_seen(client: TestClient) -> None:
    """9/30 作者：老师和对标新发的他都自己去看；不筛、不拆，看过了点一下。"""
    from tests.test_web import SEC, _wait_sync

    acct = client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"}).json()["account"]
    _wait_sync(client)
    feed = client.get("/api/feed").json()
    assert feed["teacher"] == [] and len(feed["benchmark"]) >= 1  # 新加的默认是对标
    assert feed["counts"]["benchmark"]["unseen"] == len(feed["benchmark"])
    row = feed["benchmark"][0]
    assert row["url"].endswith(row["video_id"]) and row["seen_at"] is None and row["job"] is None

    # 改成老师：整个号的新视频挪到「老师」一栏
    assert client.patch(f"/api/accounts/{acct['id']}", json={"kind": "teacher"}).json()["account"]["kind"] == "teacher"
    assert client.patch(f"/api/accounts/{acct['id']}", json={"kind": "boss"}).status_code == 400
    feed = client.get("/api/feed").json()
    assert feed["benchmark"] == [] and len(feed["teacher"]) >= 1 and feed["accounts"]["teacher"] == ["对标号"]

    vid = feed["teacher"][0]["video_id"]
    row = lambda: next(r for r in client.get("/api/feed").json()["teacher"] if r["video_id"] == vid)  # noqa: E731
    # 点「去看」只记成点开过，不算看过：看完要复刻、要拆解，这一行得还在
    client.put(f"/api/feed/{vid}", json={"opened": True})
    assert row()["opened_at"] and row()["seen_at"] is None
    client.put(f"/api/feed/{vid}", json={"note": "先给结论再讲为什么"})
    assert row()["note"] == "先给结论再讲为什么" and row()["seen_at"] is None  # 记一句也不算看过
    client.put(f"/api/feed/{vid}", json={"seen": True})
    assert row()["seen_at"]  # 只有他点「看过了」才算
    client.put(f"/api/feed/{vid}", json={"seen": False})
    assert row()["seen_at"] is None
    assert client.put("/api/feed/nope", json={"seen": True}).status_code == 400


def test_the_board_layout_class_is_defined_once() -> None:
    """10/1：「今天」的周历借用了加工中页的 .wk-grid 类名，把加工中的左右两栏挤成了四列 153px 的窄条。
    加工中的布局只能在一处定义。"""
    css = (Path(__file__).resolve().parents[1] / "src/content_studio/static/styles.css").read_text(encoding="utf-8")
    top = [line for line in css.splitlines() if line.startswith(".wk-grid{")]
    assert top == [".wk-grid{display:grid;grid-template-columns:minmax(300px,380px) 1fr;gap:16px;align-items:start}"]


def test_past_days_are_green_or_red_by_shipping() -> None:
    """10/5 作者：月历只看出摊——出摊了绿，没出摊红（原来 10/1 是按减了几分）。10/9 加回变现动作：有一件没做到就红。"""
    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    js = (static / "today.js").read_text(encoding="utf-8")
    css = (static / "styles.css").read_text(encoding="utf-8")
    assert "c.ship === 'miss' || c.mn === 'miss' ? 'mo-fail' : c.ship === 'ok' ? 'mo-pass'" in js
    assert ".mo-day.mo-pass{" in css and ".mo-day.mo-fail{" in css
    # 选中那一天的描边要压在红绿之上
    assert css.index(".mo-day.mo-fail{") < css.index(".mo-day.sel{")


def test_saved_profiles_are_locked_until_park_asks_to_edit() -> None:
    """10/1 作者：对外简介存好了还是开着的，要 lock in。存过的默认只读，点「改这一版」才出输入框。"""
    js = (Path(__file__).resolve().parents[1] / "src/content_studio/static/profiles.js").read_text(encoding="utf-8")
    assert "if ((cur.name || cur.bio) && !PFX.editing[v.key])" in js and "data-pf-unlock" in js and "delete PFX.editing[key]" in js


def test_feed_marks_how_many_times_usual_and_puts_the_hot_ones_on_top(client: TestClient) -> None:
    """10/4 作者：进项里对标的视频标上「是他平时的几倍」，1.5 倍以上的放最上面；其余照发布时间，照样全列。"""
    from tests.test_web import SEC, _wait_sync

    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}"})
    _wait_sync(client)
    store = client.app.state.store
    rows = client.get("/api/feed?days=30").json()["benchmark"]
    assert len(rows) >= 3 and all("multiple" in r and "hot" in r for r in rows)
    newest_first = [r["video_id"] for r in rows if not r["hot"]]
    # 把一条不爆的点赞拉到比谁都高：它跳到最上面，标着倍数；爆的按倍数排，不爆的还按发布时间
    old = next(r for r in reversed(rows) if not r["hot"])
    top = max(r["likes"] or 0 for r in rows)
    with store.tx() as conn:
        conn.execute("UPDATE videos SET likes = ? WHERE video_id = ?", (top * 10, old["video_id"]))
    rows = client.get("/api/feed?days=30").json()["benchmark"]
    assert rows[0]["video_id"] == old["video_id"] and rows[0]["hot"] and rows[0]["multiple"] >= 1.5
    hot = [r for r in rows if r["hot"]]
    assert [r["multiple"] for r in hot] == sorted((r["multiple"] for r in hot), reverse=True)
    assert rows[: len(hot)] == hot  # 爆的都在最上面
    assert [r["video_id"] for r in rows if not r["hot"]] == [v for v in newest_first if v != old["video_id"]]
    assert all(r["multiple"] is None or r["multiple"] < 1.5 for r in rows if not r["hot"])


def test_today_page_is_numbers_one_card_and_the_calendar() -> None:
    """10/5 作者：「第一页就保留数据和 calendar 还有 Wendy 的对话框就好了。」出摊行、先处理、读日报、补发入口、杂事都不在这页。
    同一天晚些加回当前任务和接下来3条。10/8 Codex 把任务挪到数据前面，10/9 作者 要求换回：数据在最上面。
    10/11 变现动作和接下来 3 条撤掉，换成 Wendy 每日复盘。"""
    js = (Path(__file__).resolve().parents[1] / "src/content_studio/static/today.js").read_text(encoding="utf-8")
    # 10/13 作者：「以战况页面为主页面……calendar 可以保留，其他的好像都没有 value add 了。」复盘 → KPI → 月历 → 改目标
    order = [js.index(x) for x in ("dailyReviewBlock(TD.review)", "k.kpis.map(kpiCard)", "monthBlock(TD.month", "kpiTargets(k.targets)")]
    assert order == sorted(order)
    assert "function resultsBlock(" not in js and "todayOneBlock" not in js and "kpiStrip" not in js
    assert not any(f"function {name}(" in js for name in ("shipRow", "firstBlock", "readLine", "backfillLine", "wrapBlock", "todayMoneyAction", "todayNextBlock"))
