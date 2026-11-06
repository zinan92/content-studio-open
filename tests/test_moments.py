"""朋友圈（10/18）：读 X 用假的 fxtwitter，存公众号草稿用假的微信；不联网、不碰真密钥。"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from content_studio.extras.moments import moments as mo
from tests.test_web import client  # noqa: F401

HEAD = {"x-content-studio": "1"}
NOW = 1792332171


def raw(pid: str, text: str, *, at: int = NOW, photos: int = 0, reply: bool = False, repost: bool = False) -> dict[str, Any]:
    return {"id": pid, "url": f"https://x.com/example_user/status/{pid}", "text": text, "created_timestamp": at,
            "replying_to": "someone" if reply else None, "reposted_by": {"screen_name": "x"} if repost else None,
            "media": {"all": [{"type": "photo", "url": f"https://pbs.twimg.com/media/p{pid}-{n}.jpg"} for n in range(photos)]}}


class Fake:
    """按 URL 回 fxtwitter 的 JSON；fail 次数内先回 404（fxtwitter 真会这样）。"""

    def __init__(self, timeline: list[dict[str, Any]], fail: int = 0) -> None:
        self.timeline, self.fail, self.urls = timeline, fail, []

    def __call__(self, request: Any) -> io.BytesIO:
        url = request.full_url
        self.urls.append(url)
        if url.startswith("https://pbs.twimg.com/"):
            return io.BytesIO(b"\xff\xd8jpeg")
        if self.fail:
            self.fail -= 1
            return io.BytesIO(json.dumps({"code": 404, "results": []}).encode())
        if "/statuses" in url:
            return io.BytesIO(json.dumps({"code": 200, "results": self.timeline}).encode())
        pid = url.rsplit("/", 1)[-1]
        return io.BytesIO(json.dumps({"code": 200, "tweet": raw(pid, "一句话：未来的这个世界一定是非常非常赌场化的。")}).encode())


def make(tmp_path: Path, fake: Fake, **kw: Any) -> mo.Moments:
    return mo.Moments(tmp_path / "moments", opener=fake, pause=lambda _s: None, **kw)


def test_check_keeps_only_his_own_posts_and_retries(tmp_path: Path) -> None:
    fake = Fake([raw("1", "原创"), raw("2", "回复", reply=True), raw("3", "转发", repost=True), raw("4", "老的", at=NOW - 86400 * 5)], fail=2)
    view = make(tmp_path, fake).check()
    assert view["error"] is None
    assert [p["id"] for p in view["posts"]] == ["1", "4"]  # 新的在上面；回复、转发不搬
    assert len([u for u in fake.urls if "/statuses" in u]) == 3


def test_check_falls_back_to_saved_posts_when_x_is_unreachable(tmp_path: Path) -> None:
    m = make(tmp_path, Fake([raw("1", "原创")]))
    m.check()
    m.opener = Fake([], fail=9)
    view = m.check()
    assert "读不到 X" in view["error"]
    assert [p["id"] for p in view["posts"]] == ["1"]


def test_replicate_copies_text_verbatim_and_downloads_photos(tmp_path: Path) -> None:
    text = "今天，我写了一个 skill 叫做 internalize。\nhttps://github.com/zinan92/park-knowledge\n就这样。"
    m = make(tmp_path, Fake([raw("9", text, photos=2)]))
    m.check()
    pack = m.replicate("9")
    assert pack["images"] == ["img-1.jpg", "img-2.jpg"]
    for key in ("xhs", "douyin", "wechat"):
        assert pack["packs"][key]["body"] == text  # 一个字不改，链接也在
        assert pack["packs"][key]["images"] == 2
    assert pack["packs"]["xhs"]["title"] == "今天，我写了一个 skill 叫做"  # 超 20 字在停顿处断
    assert m.view()["posts"][0]["done"]
    assert not m.view()["posts"][0]["new"]


def test_text_only_and_long_posts_get_plain_notes(tmp_path: Path) -> None:
    m = make(tmp_path, Fake([raw("5", "长" * 1200)]))
    m.check()
    packs = m.replicate("5")["packs"]
    assert any("文字配图" in n for n in packs["xhs"]["notes"])
    assert any("1000" in n for n in packs["xhs"]["notes"])
    assert any("没图" in n for n in packs["wechat"]["notes"])


def test_title_is_his_first_sentence() -> None:
    assert mo.first_line("交易的本质就是带着止损去赌一把。后面") == "交易的本质就是带着止损去赌一把"
    assert mo.first_line("https://x.com/i/article/1") == ""
    assert len(mo.first_line("一" * 40)) == 20


def test_add_by_link(tmp_path: Path) -> None:
    m = make(tmp_path, Fake([]))
    post = m.add("https://x.com/example_user/status/2111820307858403840?s=20")
    assert post["id"] == "2111820307858403840"
    assert post["text"].endswith("赌场化的。")
    try:
        m.add("随便一段字")
    except mo.MomentsError as exc:
        assert "链接" in str(exc)
    else:
        raise AssertionError("not a link should fail")


class FakeWechat:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __call__(self, request: Any) -> io.BytesIO:
        path = request.full_url.split("cgi-bin/", 1)[1].split("?", 1)[0]
        body = request.data
        self.calls.append((path, json.loads(body) if body and path.startswith("draft") else None))
        reply = {"token": {"access_token": "T"}, "material/add_material": {"media_id": f"M{len(self.calls)}"},
                 "draft/add": {"media_id": "D1"}, "draft/update": {}}[path]
        return io.BytesIO(json.dumps(reply).encode())


def test_wechat_draft_is_a_newspic_with_his_images_and_updates_next_time(tmp_path: Path) -> None:
    wx = FakeWechat()
    m = make(tmp_path, Fake([raw("7", "几张图，几句话。", photos=2)]), wechat_send=wx, wechat_creds={"appid": "a", "secret": "s"})
    m.check()
    m.replicate("7")
    first = m.wechat_draft("7")
    assert first["media_id"] == "D1" and not first["updated"]
    added = next(body for path, body in wx.calls if path == "draft/add")["articles"][0]
    assert added["article_type"] == "newspic"
    assert added["content"] == "几张图，几句话。"
    assert len(added["image_info"]["image_list"]) == 2
    again = m.wechat_draft("7")
    assert again["updated"]
    assert [p for p, _ in wx.calls].count("draft/add") == 1


def test_wechat_draft_needs_an_image(tmp_path: Path) -> None:
    m = make(tmp_path, Fake([raw("8", "只有一句话")]), wechat_send=FakeWechat(), wechat_creds={"appid": "a", "secret": "s"})
    m.check()
    m.replicate("8")
    try:
        m.wechat_draft("8")
    except mo.MomentsError as exc:
        assert "一张图" in str(exc)
    else:
        raise AssertionError("no image should fail")


def test_routes(client, tmp_path: Path) -> None:  # noqa: F811
    client.app.state.moments = make(tmp_path, Fake([raw("1", "原创", photos=1)]))
    assert client.get("/moments").status_code == 200
    assert client.get("/moments/page.js").status_code == 200
    assert client.post("/api/moments/check", headers=HEAD, json={}).json()["posts"][0]["id"] == "1"
    pack = client.post("/api/moments/1/replicate", headers=HEAD, json={}).json()
    assert client.get(f"/api/moments/1/img/{pack['images'][0]}").status_code == 200
    assert client.get("/api/moments/1/img/..%2Fstate.json").status_code == 404
    assert client.post("/api/moments/nope/replicate", headers=HEAD, json={}).status_code == 400
