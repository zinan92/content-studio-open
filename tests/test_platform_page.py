"""平台页（10/6 作者）：左边按平台排，每个平台一页——待发、这个平台的默认、数据、被删被限流的记录。
形式按平台多选：X、小红书可能视频、图文、文字都发。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_web import client  # noqa: F401


def _ready_topic(client: TestClient, title: str = "这一条") -> int:
    """标题定稿了的一条：加工中最后一步「标题和封面」做完，就该出现在各平台页的「待发」里。"""
    topic = client.post("/api/topics", json={"title": title}).json()
    client.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {"douyin": {"title": title, "body": "简介", "tags": ["AI"]}}})
    assert client.put(f"/api/topics/{topic['id']}/approve", json={"key": "copy"}).status_code == 200
    return topic["id"]


def test_forms_can_be_several_per_platform(client: TestClient) -> None:
    """10/6 作者：「X 和小红书，我有可能会发图文和文字，甚至有可能视频、图文、文字都发」——每个平台可多选，至少一种。"""
    for key in ("x", "xiaohongshu"):
        client.put(f"/api/platform/{key}/settings", json={"on": True})
    tid = client.post("/api/topics", json={"title": "多选"}).json()["id"]
    got = {p["key"]: p for p in client.get(f"/api/topics/{tid}/forms").json()["platforms"]}
    assert got["x"]["forms"] == ["video"]
    r = client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"], "xiaohongshu": "cards"}})
    assert r.status_code == 200
    got = {p["key"]: p for p in r.json()["platforms"]}
    assert got["x"]["forms"] == ["video", "text"] and got["xiaohongshu"]["forms"] == ["cards"]
    # 10/7：一格都不勾 = 这条不发这个平台（记成跳过）；再勾上就又发
    r = client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": []}})
    assert r.status_code == 200 and {p["key"]: p["forms"] for p in r.json()["platforms"]}["x"] == []
    r = client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["text"]}})
    assert {p["key"]: p["forms"] for p in r.json()["platforms"]}["x"] == ["text"]
    assert client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "hologram"]}}).status_code == 400
    # 平台默认也能多选，新建的那条按它来
    r = client.put("/api/platform/x/settings", json={"forms": ["text", "video"]})
    assert r.status_code == 200 and r.json()["defaults"]["forms"] == ["text", "video"]
    newer = client.post("/api/topics", json={"title": "下一条"}).json()["id"]
    assert {p["key"]: p["forms"] for p in client.get(f"/api/topics/{newer}/forms").json()["platforms"]}["x"] == ["text", "video"]
    assert client.put("/api/platform/x/settings", json={"forms": []}).status_code == 400


def test_platform_page_lists_pending_and_marks_each_form_sent(client: TestClient) -> None:
    tid = _ready_topic(client)
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"]}})
    page = client.get("/api/platform/x").json()
    assert page["key"] == "x" and page["label"] == "X" and page["core"] is True
    item = next(it for it in page["pending"] if it["topic_id"] == tid)
    rows = {r["form"]: r for r in item["rows"]}
    assert set(rows) == {"video", "text"}
    assert rows["video"]["action"] == "hand" and rows["video"]["ready"] is False and "成片" in rows["video"]["why"]
    # 10/20 作者：X 不走 API 了，文字也是他自己传
    assert rows["text"]["action"] == "hand" and rows["text"]["ready"] is False
    assert item["copy"]["title"] == "这一条"
    # 他自己发了视频、贴了链接：那一行打 ✓，文字那一行还在等；平台级记录和形式级记录都有
    r = client.post(f"/api/topics/{tid}/platform/x/sent", json={"form": "video", "url": "https://x.com/park/status/1"})
    assert r.status_code == 200
    page = client.get("/api/platform/x").json()
    rows = {r["form"]: r for r in next(it for it in page["pending"] if it["topic_id"] == tid)["rows"]}
    assert rows["video"]["sent"]["url"] == "https://x.com/park/status/1" and rows["text"]["sent"] is None
    assert client.get(f"/api/publish/desk?topic_id={tid}").json()["platforms"]
    posts = {p["topic_id"]: p for p in page["posts"]}
    assert posts[tid]["forms"] == ["video"] and posts[tid]["url"] == "https://x.com/park/status/1"
    # 文字也发了：这条就不在 X 的待发里了
    client.post(f"/api/topics/{tid}/platform/x/sent", json={"form": "text"})
    assert all(it["topic_id"] != tid for it in client.get("/api/platform/x").json()["pending"])
    # 撤回文字：又回到待发
    client.post(f"/api/topics/{tid}/platform/x/sent", json={"form": "text", "undo": True})
    assert any(it["topic_id"] == tid for it in client.get("/api/platform/x").json()["pending"])
    assert client.post(f"/api/topics/{tid}/platform/x/sent", json={"form": "video", "url": "ftp://x"}).status_code == 400
    assert client.post(f"/api/topics/{tid}/platform/nope/sent", json={"form": "video"}).status_code == 400


def test_pack_and_platform_share_form_status_without_calling_a_draft_published(client: TestClient) -> None:
    tid = _ready_topic(client)
    client.put("/api/platform/wechat_mp/settings", json={"on": True})
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"wechat_mp": ["text"]}})
    store = client.app.state.store
    job = store.create_publish_job(tid, {"platform": "wechat_mp", "mode": "draft"})
    store.update_publish_job(job["id"], state="done", result={"ok": True, "published": False, "public_url": "https://mp.weixin.qq.com/"})

    def states():
        pack = {row["form"]: row for row in client.get(f"/api/topics/{tid}/pack").json()["lanes"] if row["key"] == "wechat_mp"}
        pending = next(row for row in client.get("/api/platform/wechat_mp").json()["pending"] if row["topic_id"] == tid)
        platform = {row["form"]: row for row in pending["rows"]}
        assert {form: row["presentation"] for form, row in pack.items()} == {form: row["presentation"] for form, row in platform.items()}
        return pack

    rows = states()
    assert rows["text"]["presentation"]["state"] == "draft"
    assert rows["text"]["sent"] is None
    for state in ("awaiting_confirm", "running", "unknown", "failed"):
        store.update_publish_job(job["id"], state=state)
        assert states()["text"]["presentation"]["state"] == state
    client.post(f"/api/topics/{tid}/platform/wechat_mp/sent", json={"form": "text", "url": "https://mp.weixin.qq.com/s/abc"})
    # 发齐了就不在待发里；「发」页那一格是已发
    lane = next(row for row in client.get(f"/api/topics/{tid}/pack").json()["lanes"] if row["key"] == "wechat_mp")
    assert lane["presentation"]["state"] == "published"


def test_pack_requires_valid_copy_even_when_the_form_material_is_ready(client: TestClient, monkeypatch) -> None:
    from content_studio import approvals

    tid = _ready_topic(client)
    client.put("/api/platform/x/settings", json={"on": True})
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["text"]}})
    original = approvals.status

    def prepared_article_with_stale_copy(folder, fps):
        result = original(folder, fps)
        result["article"].update(approved=True, valid=True)
        result["copy"].update(approved=True, valid=False)
        return result

    monkeypatch.setattr(approvals, "status", prepared_article_with_stale_copy)
    lane = next(row for row in client.get(f"/api/topics/{tid}/pack").json()["lanes"] if row["key"] == "x")
    assert lane["ready"] is False and lane["why"] == "标题和文案还没定稿"
    assert lane["presentation"]["state"] == "not_ready"


def test_stale_copy_keeps_existing_delivery_evidence_visible_but_unready(client: TestClient) -> None:
    tid = _ready_topic(client)
    client.put("/api/platform/wechat_mp/settings", json={"on": True})
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"wechat_mp": ["text"]}})
    store = client.app.state.store
    job = store.create_publish_job(tid, {"platform": "wechat_mp", "mode": "draft"})
    store.update_publish_job(job["id"], state="done", result={"ok": True, "published": False})
    client.put(f"/api/topics/{tid}/copy", json={"platforms": {"douyin": {"title": "后来改过的标题", "body": "新描述", "tags": []}}})
    assert client.get(f"/api/topics/{tid}/pack").json()["copy_locked"] is False

    for job_state, expected in (("done", "draft"), ("running", "running"), ("awaiting_confirm", "awaiting_confirm"),
                                ("unknown", "unknown"), ("failed", "failed")):
        store.update_publish_job(job["id"], state=job_state)
        item = next(row for row in client.get("/api/platform/wechat_mp").json()["pending"] if row["topic_id"] == tid)
        row = item["rows"][0]
        lane = next(row for row in client.get(f"/api/topics/{tid}/pack").json()["lanes"] if row["key"] == "wechat_mp")
        assert row["presentation"] == lane["presentation"]
        assert row["presentation"]["state"] == expected
        assert row["ready"] is False and row["plan"] == "wait"
        assert len(store.publish_jobs(tid)) == 1  # GETs never start another publication.
    store.update_publish_job(job["id"], state="cancelled")
    assert all(row["topic_id"] != tid for row in client.get("/api/platform/wechat_mp").json()["pending"])


def test_platform_counts_and_others_group(client: TestClient) -> None:
    tid = _ready_topic(client, "数一数")
    counts = client.get("/api/platform/counts").json()
    assert counts["douyin"] >= 1 and counts["x"] >= 1 and "others" in counts
    assert {"youtube", "bilibili"} <= set(counts) and "x_pending" not in counts  # 10/19：X 和别的平台一个格式
    others = client.get("/api/platform/others").json()
    assert [g["key"] for g in others["groups"]] == ["bilibili", "youtube", "wechat_mp"]
    # 机器能发的才接「发」：公众号的视频要你自己传
    assert client.post(f"/api/topics/{tid}/platform/wechat_mp/send", json={"form": "video"}).status_code == 400
    assert client.get("/api/platform/hologram").status_code == 404


def test_platform_settings_and_notes(client: TestClient) -> None:
    # 常用话题 10/8 起只在设置里改：平台页显示设置里的，这个接口不收
    client.put("/api/settings", json={"traffic_tags": {"xiaohongshu": ["#AI", "创业"]}})
    r = client.put("/api/platform/xiaohongshu/settings", json={"on": True, "handle": "作者", "traffic_tags": ["别的"]})
    assert r.status_code == 200
    d = r.json()["defaults"]
    assert d["on"] is True and d["handle"] == "作者" and d["traffic_tags"] == ["AI", "创业"]
    assert client.get("/api/state").json()["settings"]["platform_accounts"]["xiaohongshu"]["handle"] == "作者"
    r = client.post("/api/platform/xiaohongshu/notes", json={"text": "标题带「赚钱」被限流", "title": "只有6000粉丝"})
    assert r.status_code == 200 and r.json()["notes"][0]["text"] == "标题带「赚钱」被限流"
    nid = r.json()["notes"][0]["id"]
    assert client.get("/api/platform/xiaohongshu").json()["notes"][0]["id"] == nid
    assert client.post("/api/platform/xiaohongshu/notes", json={"text": " "}).status_code == 400
    assert client.delete(f"/api/platform/xiaohongshu/notes/{nid}").json()["notes"] == []


def test_today_points_at_platform_pages_not_the_old_publish_page() -> None:
    from pathlib import Path

    web = (Path(__file__).resolve().parents[1] / "src/content_studio/web.py").read_text(encoding="utf-8")
    assert 'go=f"publish/' not in web
    assert 'go=f"platform/douyin/' in web
    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    index = (static / "index.html").read_text(encoding="utf-8")
    # 10/20 左栏 = 找写剪发盘：平台不再各占一行，从「盘 · 各平台」进（id="v-plats"），平台页本身还在
    assert 'data-view="platform"' not in index and 'id="v-plats"' in index and 'id="v-platform"' in index
    # 10/19 战况和汇总并成「复盘」：左栏只有 data-view="today" 一个入口
    assert 'data-view="summary"' not in index and 'data-view="today"' in index
    # 「发」是正在做的那条的标题和封面页（data-zx="fa"），不是旧的发布台
    assert 'data-view="pack" data-zx="fa"' in index and 'data-view="publish"' not in index and 'data-view="xline"' not in index
    # 10/6 拆老站：发布台的上传弹窗和 X 线那一页整页没了，「标题和封面」页只留它要的几块（packparts.js）
    assert 'id="v-publish"' not in index and 'id="v-xline"' not in index and 'id="pubDlg"' not in index
    assert not (static / "publishdesk.js").exists() and (static / "packparts.js").exists()
    css = (static / "styles.css").read_text(encoding="utf-8")
    assert "overflow-y:auto" in css.split(".rail{")[1].split("}")[0]  # 13 寸屏上左栏能滚到底


def test_ticking_platforms_decides_what_gets_made_and_each_lane_waits_only_for_its_own(client: TestClient, tmp_path) -> None:
    """10/7 作者：只发视频的那天不该要插图、排版；X 视频和文章两条线各走各的；一格都不勾的平台这条不发。"""
    root = tmp_path / "videos"
    base = root / "2026-10-07_爆款拆解"
    (base / "final").mkdir(parents=True)
    (base / "final" / "video.mp4").write_bytes(b"0" * 64)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    for key in ("x", "wechat_mp"):
        client.put(f"/api/platform/{key}/settings", json={"on": True})
    tid = client.post("/api/topics", json={"title": "爆款拆解", "formats": "video"}).json()["id"]
    client.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"x": ["video", "text"]}})

    view = client.get(f"/api/topics/{tid}/pack").json()
    assert [s["key"] for s in view["steps"]] == ["cover", "article", "figs", "wx"]
    lanes = {(lane["key"], lane["form"]): lane for lane in view["lanes"]}
    assert set(lanes) == {("douyin", "video"), ("x", "video"), ("x", "text"), ("wechat_mp", "text")}
    assert lanes[("douyin", "video")]["why"] == "封面还没定稿" and lanes[("x", "text")]["why"] == "文章还没写好"
    assert lanes[("x", "text")]["form_label"] == "文章"

    # 公众号这条不发、X 只发视频：只剩封面
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"wechat_mp": [], "x": ["video"]}})
    view = client.get(f"/api/topics/{tid}/pack").json()
    assert [s["key"] for s in view["steps"]] == ["cover"]
    assert {(lane["key"], lane["form"]) for lane in view["lanes"]} == {("douyin", "video"), ("x", "video")}
    assert "wechat_mp" not in {p["key"] for p in client.get("/api/platform/wechat_mp").json()["pending"]}

    # 一条视频都不发：封面也不做（封面从视频里抽帧，没视频就永远做不完）
    client.put(f"/api/topics/{tid}/forms", json={"forms": {"douyin": [], "x": ["text"]}})
    view = client.get(f"/api/topics/{tid}/pack").json()
    assert [s["key"] for s in view["steps"]] == ["article", "figs"]


def test_old_topics_are_frozen_before_defaults_change(tmp_path) -> None:
    """10/7：选题创建时只记了四大平台；公众号、B 站、YouTube 跟默认走。改默认前先按现在的样子补记上，
    已经在做、已经发完的内容不会突然多出要做的东西。只补缺的，不动记过的。"""
    import json

    from content_studio.store import StudioStore

    store = StudioStore(tmp_path / "s.sqlite3")
    tid = store.create_topic("老的一条")["id"]
    with store.tx() as conn:
        conn.execute("UPDATE topics SET platform_forms = ? WHERE id = ?", (json.dumps({"douyin": ["video"], "x": ["video"]}), tid))
    assert store.freeze_platform_forms() == 1
    forms = store.topic(tid)["platform_forms"]
    assert forms["wechat_mp"] == ["text"] and forms["bilibili"] == ["video"] and forms["x"] == ["video"]
    assert store.freeze_platform_forms() == 0

    store.update_settings({"platform_accounts": {"x": {"on": True, "forms": ["video", "text"]}}})
    assert store.topic(tid)["platform_forms"]["x"] == ["video"]
    assert store.create_topic("新的一条")["platform_forms"]["x"] == ["video", "text"]


# ---------------- 其他三个：自己发 + 汇总表（10/8 作者） ----------------

def test_auto_plan_decides_each_cell() -> None:
    """做好了没发的自己发；在发的、存了草稿的、服务重启不知道发没发的都不自己再发；没发成的隔半小时再试，三次为止。"""
    from datetime import datetime, timedelta, timezone

    from content_studio import platform_page as pp

    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    ago = lambda m: (now - timedelta(minutes=m)).isoformat()  # noqa: E731
    ready = {"sent": None, "action": "auto", "ready": True, "why": ""}
    plan = lambda row, jobs, login=False: pp.auto_plan(row, jobs, now, login_failed=lambda j: login)  # noqa: E731
    assert plan(ready, []) == ("due", None)
    assert plan({**ready, "sent": {"url": None}}, []) == ("sent", None)
    assert plan({**ready, "action": "hand"}, []) == ("hand", None)
    assert plan({**ready, "ready": False, "why": "封面还没定稿"}, []) == ("wait", "封面还没定稿")
    assert plan(ready, [{"state": "running"}])[0] == "running"
    assert plan(ready, [{"state": "unknown"}])[0] == "unknown"
    assert plan(ready, [{"state": "done", "result": {"published": False}}])[0] == "draft"
    assert plan(ready, [{"state": "cancelled"}])[0] == "due"  # 登录窗口关了没点发布：当没发生过
    failed = {"state": "failed", "finished_at": ago(10), "message": "页面等待超时"}
    state, again = plan(ready, [failed])
    assert state == "retry" and again == (now + timedelta(minutes=20)).isoformat()
    assert plan(ready, [{**failed, "finished_at": ago(31)}])[0] == "due"
    assert plan(ready, [failed], login=True)[0] == "due"  # 登录过期：登好了马上再发，不等半小时
    assert plan(ready, [{**failed, "finished_at": ago(90)}] * 3)[0] == "failed"


def test_summary_rows_merge_pending_and_sent_and_count_what_needs_him() -> None:
    from content_studio import platform_page as pp

    cell = lambda plan, form="video", **kw: {"form": form, "label": "视频", "plan": plan, "plan_note": None, "sent": kw.get("sent"), "job": kw.get("job")}  # noqa: E731
    groups = [
        {"key": "bilibili", "pending": []},
        {"key": "youtube", "pending": [{"topic_id": 1, "title": "新的一条", "updated_at": "2026-10-08T06:00:00+00:00", "rows": [cell("due")]}]},
        {"key": "wechat_mp", "pending": [{"topic_id": 1, "title": "新的一条", "updated_at": "2026-10-08T06:00:00+00:00",
                                          "rows": [cell("draft", "text", job={"draft_link": "https://mp.weixin.qq.com/x"})]}]},
    ]
    posts = {"bilibili": [{"topic_id": 1, "title": "新的一条", "form": "video", "url": "https://b23.tv/1", "published_at": "2026-10-08T07:00:00+00:00"},
                          {"topic_id": 2, "title": "老的", "form": "", "url": None, "published_at": "2026-08-01T00:00:00+00:00"}],
             "youtube": [], "wechat_mp": []}
    rows = pp.summary_rows(groups, posts, since="2026-09-01")
    assert [r["topic_id"] for r in rows] == [1]  # 45 天以前发的不进表
    cells = rows[0]["cells"]
    assert cells["bilibili"][0]["state"] == "sent" and cells["bilibili"][0]["url"] == "https://b23.tv/1"
    assert cells["youtube"][0]["state"] == "due" and cells["wechat_mp"][0]["draft_link"] == "https://mp.weixin.qq.com/x"
    assert pp.needs_you(rows, set()) == 1             # 只有公众号群发要他动手；YouTube 机器自己发
    assert pp.needs_you(rows, {"youtube"}) == 2       # YouTube 要扫码登录了：也算他的事


def test_others_send_themselves_and_wechat_draft_gone_means_he_sent_it(tmp_path, monkeypatch) -> None:
    """10/8 作者：主线下来的全部自动处理——B 站、YouTube 不用点「发到」，公众号不用点「存进草稿箱」；
    YouTube 等抖音先发；公众号群发了（草稿箱里没了）页面自己打 ✓。假的发布脚本，不碰真平台。"""
    import json
    import sys
    import time

    from content_studio import approvals, channel_probe
    from content_studio.extras.consults import consult
    from content_studio import web as web_module
    from tests.test_web import FakeClient

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs-home"))
    monkeypatch.setenv("CONTENT_STUDIO_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(consult.ROOT_ENV, str(tmp_path / "consults"))
    monkeypatch.setenv("CONTENT_STUDIO_NO_OPEN", "1")
    monkeypatch.setattr(channel_probe, "CACHE_PATH", tmp_path / "probes.json")
    monkeypatch.setattr(approvals, "status", lambda folder, fps: {k: {"approved": True, "valid": True, "made": True, "by": "park"}
                                                                   for k in ("copy", "cover", "article", "figs", "wx", "xhs")})
    log = tmp_path / "sent.txt"
    cred = tmp_path / "secrets.yaml"
    cred.write_text("{}")

    def fake(platform: str, result: dict, arg: str) -> list[str]:
        script = (f"import json,pathlib; p=pathlib.Path({str(log)!r}); "
                  f"p.write_text((p.read_text() if p.exists() else '') + {platform!r} + '\\n'); print(json.dumps({result!r}))")
        return [sys.executable, "-c", script, arg]

    specs = {"youtube": {"label": "YouTube", "copy_key": "youtube", "credential": cred, "login_hint": "",
                         "modes": {"public": {"label": "公开", "argv": fake("youtube", {"ok": True, "video_id": "abc"}, "{video}")}}},
             "wechat_mp": {"label": "公众号", "copy_key": "wechat_mp", "credential": cred, "login_hint": "", "no_video": True, "needs_article": True,
                           "modes": {"draft": {"label": "草稿", "argv": fake("wechat_mp", {"ok": True, "published": False, "media_id": "M1"}, "{article}")}}}}
    drafts = {"M1": True}
    cookie = tmp_path / "cookies.json"
    cookie.write_text(json.dumps({"sessionid": "x"}))
    cookie.chmod(0o600)
    app = web_module.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                                downloads_dir=tmp_path / "dl", client_factory=FakeClient, start_worker=False, drafts_dir=tmp_path / "drafts",
                                publishers=specs, draft_exists_fn=lambda media_id: drafts[media_id])

    def settle(c: TestClient) -> dict:
        for _ in range(200):
            page = c.get("/api/platform/others").json()
            if not any(cl["state"] == "running" for r in page["table"] for cs in r["cells"].values() for cl in cs):
                return page
            time.sleep(0.05)
        raise AssertionError("还在发")

    with TestClient(app, headers={"X-Content-Studio": "1"}) as c:
        root = tmp_path / "videos"
        base = root / "2026-10-08_自动发"
        (base / "final").mkdir(parents=True)
        (base / "final" / "video.mp4").write_bytes(b"0" * 64)
        c.put("/api/settings", json={"video_projects_root": str(root)})
        for key in ("youtube", "wechat_mp"):
            c.put(f"/api/platform/{key}/settings", json={"on": True})
        tid = c.post("/api/topics", json={"title": "自动发", "formats": "video"}).json()["id"]
        c.put(f"/api/topics/{tid}/video-project", json={"name": base.name})
        c.put(f"/api/topics/{tid}/copy", json={"platforms": {k: {"title": "自动发", "body": "简介", "tags": ["AI"]} for k in ("douyin", "youtube", "wechat_mp")}})
        art = tmp_path / "drafts" / f"topic-{tid}" / "article.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("# 自动发\n\n第一段。\n", encoding="utf-8")
        app.state.store.update_topic(tid, article_path=str(art))

        page = c.get("/api/platform/others").json()
        row = next(r for r in page["table"] if r["topic_id"] == tid)
        assert row["cells"]["youtube"][0]["state"] == "wait" and row["cells"]["youtube"][0]["note"] == "等抖音先发"
        assert row["cells"]["wechat_mp"][0]["state"] == "due"
        assert "bilibili" not in row["cells"]  # B 站没开：这条不发它

        # 一轮：公众号存进草稿箱（不用点）；YouTube 还在等抖音
        assert app.state.others_auto_tick() == [(tid, "wechat_mp", "text")]
        page = settle(c)
        cell = next(r for r in page["table"] if r["topic_id"] == tid)["cells"]["wechat_mp"][0]
        assert cell["state"] == "draft" and log.read_text().split() == ["wechat_mp"]
        assert c.get("/api/platform/counts").json()["others"] == 1  # 要他做的只剩去群发

        # 抖音发了：下一轮 YouTube 自己发出去
        app.state.store.update_topic(tid, published_video_id="7700000000000000001")
        assert app.state.others_auto_tick() == [(tid, "youtube", "video")]
        page = settle(c)
        cell = next(r for r in page["table"] if r["topic_id"] == tid)["cells"]["youtube"][0]
        assert cell["state"] == "sent" and cell["url"] == "https://www.youtube.com/watch?v=abc"
        assert app.state.others_auto_tick() == []  # 发过的不再发
        assert log.read_text().split() == ["wechat_mp", "youtube"]

        # 他去后台扫码群发了：草稿箱里那份没了，这里自己打 ✓
        drafts["M1"] = False
        app.state.others_auto["draft_checked"].clear()
        app.state.others_auto_tick()
        page = c.get("/api/platform/others").json()
        cell = next(r for r in page["table"] if r["topic_id"] == tid)["cells"]["wechat_mp"][0]
        assert cell["state"] == "sent"
        assert c.get("/api/platform/counts").json()["others"] == 0
        assert log.read_text().split() == ["wechat_mp", "youtube"]  # 没有再存一次草稿
    app.state.store.close()


def test_late_registration_keeps_the_real_publish_day_and_new_posts_show_in_the_sheet(client: TestClient) -> None:
    """10/20 走查：小红书昨晚发的、今天才登记，记成了今天；发出去的新内容还没对上抖音作品，复盘那张表里没有它。"""
    tid = _ready_topic(client, "昨晚发的那条")
    r = client.post(f"/api/topics/{tid}/platform/xiaohongshu/sent", json={"form": "video", "day": "2026-10-19"})
    assert r.status_code == 200
    rec = client.app.state.store.publish_records(tid)["xiaohongshu"]
    assert rec["published_at"].startswith("2026-10-19")
    assert client.post(f"/api/topics/{tid}/platform/xiaohongshu/sent", json={"form": "video", "day": "2099-01-01"}).status_code == 400
    assert client.post(f"/api/topics/{tid}/platform/xiaohongshu/sent", json={"form": "video", "day": "昨天"}).status_code == 400
    # 还没对上抖音作品：在那张表最上面，小红书那格是「发了」，日期是他说的那天
    row = next(f for f in client.get("/api/backfill").json()["fresh"] if f["topic_id"] == tid)
    assert row["done"]["xiaohongshu"] is True and row["published_at"].startswith("2026-10-19")


def test_a_channel_that_cannot_post_or_read_asks_to_reconnect(client: TestClient, monkeypatch) -> None:
    """10/20 作者：「每一个 channel 连不上的话，给用户一个提示，让他去 reconnect」。
    B 站：探测说登录还在，可最近一次投稿等不到填标题的输入框——一样算断了，给重新登录。抖音：作品读不到就要重新登录。"""
    from content_studio import publisher

    assert publisher.diagnose("bilibili", 'Page.wait_for_selector: Timeout 120000ms exceeded. waiting for locator("input[placeholder=\\"请输入稿件标题\\"]")')["fix"] == "login"
    store = client.app.state.store
    rows = {p["key"]: p for p in client.get("/api/platforms").json()["platforms"]}
    assert rows["douyin"]["can_login"] is True and "x" in rows and rows["x"]["state"] == "manual"  # X 没有通道了
    tid = _ready_topic(client, "B 站这条")
    job = store.create_publish_job(tid, {"platform": "bilibili", "mode": "upload"})
    store.update_publish_job(job["id"], state="failed", message='Page.wait_for_selector: Timeout 120000ms exceeded. locator("input[placeholder=\\"请输入稿件标题\\"]")')
    bili = {p["key"]: p for p in client.get("/api/platforms").json()["platforms"]}["bilibili"]
    assert bili["state"] == "stale" and "登录" in bili["note"] and bili["can_login"] is True
    # 自己的抖音号读作品失败（测试里没有真的号，直接给一个出错的号）
    monkeypatch.setattr(store, "self_account", lambda: {"id": 1, "nickname": "me", "status": "error", "last_error": "抖音拒绝读取作品列表"})
    dy = {p["key"]: p for p in client.get("/api/platforms").json()["platforms"]}["douyin"]
    assert dy["state"] == "stale" and "重新登录抖音" in dy["note"]
    # 抖音的重新登录：没点之前是 idle
    assert client.get("/api/douyin/login").json()["state"] == "idle"
