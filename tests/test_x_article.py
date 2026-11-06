from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from content_studio import publisher
from content_studio.extras.xline import x_article
from content_studio.x_post import XError

CREDS = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_secret": "a"}
ARTICLE = """# 我终于理解了dontbesilent为什么开源dbskill

开头一段，**产品变便宜了**，信任变贵了。
接着同一段。

## 一、用便宜的东西换贵的东西

- 内容便宜
1. 先做产品

> 信任是最贵的产品

![截图](shot.png)
"""


class Fake:
    """记下每个请求，按网址回话。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict]] = []

    def __call__(self, request):
        self.calls.append((request.full_url, request.data, dict(request.headers)))
        url = request.full_url
        if url.endswith("/media/upload"):
            reply = {"data": {"id": f"m{len(self.calls)}"}}
        elif url.endswith("/articles/draft"):
            reply = {"data": {"id": "a1"}}
        else:
            reply = {"data": {"post_id": "99"}}
        return io.BytesIO(json.dumps(reply).encode())


def test_markdown_becomes_draftjs_blocks() -> None:
    title, items = x_article.parse_markdown(ARTICLE)
    assert title == "我终于理解了dontbesilent为什么开源dbskill"
    kinds = [i["type"] for i in items]
    assert kinds == ["unstyled", "header-one", "unordered-list-item", "unstyled", "blockquote", "image"]
    assert items[0]["text"] == "开头一段，产品变便宜了，信任变贵了。 接着同一段。"
    assert items[0]["styles"] == [{"offset": 5, "length": 6, "style": "bold"}]
    state = x_article.content_state(items, {"shot.png": "m9"})
    atomic = state["blocks"][-1]
    assert atomic["type"] == "atomic" and atomic["entity_ranges"][0]["key"] == 0
    assert state["entities"][0]["value"]["data"]["media_items"][0] == {"media_category": "tweet_image", "media_id": "m9"}


def test_offsets_count_utf16() -> None:
    _, styles = x_article._inline("👍好**棒**")
    assert styles == [{"offset": 3, "length": 1, "style": "bold"}]


def test_cover_goes_into_the_cover_slot_not_the_body(tmp_path: Path) -> None:
    """9/24：封面放进 X 文章自己的 cover_media；正文第一块不再是一张图。"""
    (tmp_path / "a.md").write_text(ARTICLE, encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG....")
    cover = tmp_path / "x-cover.jpg"
    cover.write_bytes(b"\xff\xd8....")
    fake = Fake()
    result = x_article.publish_article(tmp_path / "a.md", cover=cover, creds=CREDS, send=fake)
    urls = [c[0] for c in fake.calls]
    assert urls == [x_article.UPLOAD, x_article.UPLOAD, f"{x_article.API}/articles/draft"]
    draft = json.loads(fake.calls[2][1])
    assert draft["cover_media"] == {"media_id": "m1", "media_category": "tweet_image"}
    assert draft["content_state"]["blocks"][0]["type"] == "unstyled"  # 正文从文字开始
    assert result["images"] == 1 and result["published"] is False and result["url"] == "https://x.com/compose/articles"
    assert all("OAuth " in c[2]["Authorization"] for c in fake.calls)

    fake = Fake()
    done = x_article.publish_article(tmp_path / "a.md", cover=cover, publish=True, creds=CREDS, send=fake)
    assert fake.calls[-1][0] == f"{x_article.API}/articles/a1/publish" and done["url"].endswith("/99")


def test_default_cover_is_made_from_the_title_and_bad_images_stop_early(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# 只有字的标题\n\n正文", encoding="utf-8")
    made = []

    def fake_cover(title: str, out: Path) -> Path:
        made.append(title)
        out.write_bytes(b"\xff\xd8")
        return out

    fake = Fake()
    x_article.publish_article(tmp_path / "a.md", creds=CREDS, send=fake, make_cover=fake_cover)
    assert made == ["只有字的标题"] and json.loads(fake.calls[-1][1])["cover_media"]["media_id"] == "m1"
    (tmp_path / "b.md").write_text("# 标题\n\n![](missing.png)", encoding="utf-8")
    fake = Fake()
    with pytest.raises(XError, match="找不到图片"):
        x_article.publish_article(tmp_path / "b.md", creds=CREDS, send=fake, make_cover=fake_cover)
    assert fake.calls == []


def test_x_has_no_publishing_channel_any_more() -> None:
    """10/20 作者：「X 的 API 拿掉，X 也是手动上传的」——发布台没有 X 通道，X 和视频号、小红书一样他自己传。"""
    assert "x" not in publisher.PUBLISHERS
    with pytest.raises(publisher.PublishError):
        publisher.build_payload("x", "article_draft", video=None, copy={"x": {"body": "一句话"}})


def test_channels_run_with_a_python_that_has_their_libraries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """9/24：B 站投稿报没有 playwright——PATH 里第一个 python3 没装它。按通道要的库挑解释器。"""
    import sys

    publisher._PYTHON_FOR.clear()
    assert publisher.python_with(("json",), candidates=("/nope/python", sys.executable)) == sys.executable
    with pytest.raises(publisher.PublishError, match="找不到装了 no_such_mod_xyz"):
        publisher.python_with(("no_such_mod_xyz",), candidates=(sys.executable,))
    assert publisher.python_with(()) == sys.executable

    seen = []
    monkeypatch.setattr(publisher, "python_with", lambda mods, candidates=None: seen.append(mods) or "/picked/python")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0")
    payload = publisher.build_payload("bilibili", "upload", video=video, copy={"bilibili": {"title": "标题", "body": "简介"}})
    assert publisher.command_for(payload)[0] == "/picked/python" and seen[-1] == ("playwright",)


def test_bilibili_upload_carries_the_landscape_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "python_with", lambda mods, candidates=None: "/py")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0")
    cover = tmp_path / "横封面.jpg"
    cover.write_bytes(b"1")
    copy = {"bilibili": {"title": "标题", "body": "简介"}}
    argv = publisher.command_for(publisher.build_payload("bilibili", "upload", video=video, copy=copy, cover=cover))
    assert argv[-2:] == ["--cover", str(cover)]
    bare = publisher.command_for(publisher.build_payload("bilibili", "upload", video=video, copy=copy))
    assert bare[-2:] == ["--cover", ""]  # 没有封面：脚本照旧，让 B 站自己截帧


def test_failure_reason_reaches_the_page() -> None:
    """9/24：X 报「需要 Premium」，页面上只显示「发布失败」。"""
    assert "Premium" in publisher.explain({"ok": False, "error": "X 不让发（403）：发图文文章需要账号开通 X Premium"})
    assert publisher.explain({"ok": False}) == "发布失败"


@pytest.mark.skipif(__import__("importlib").util.find_spec("playwright") is None, reason="playwright missing")
def test_text_cover_is_a_5_to_2_banner(tmp_path: Path) -> None:
    from content_studio import x_cover

    out = x_cover.make_cover("产品越来越便宜，信任越来越贵，自媒体的下半场才刚刚开始", tmp_path / "c.jpg")
    data = out.read_bytes()
    assert data[:2] == b"\xff\xd8"
    # JPEG SOF0 里读宽高
    i = data.index(b"\xff\xc0")
    height, width = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
    assert (width, height) == (1500, 600)
    assert "自媒体的下半场" in x_cover.cover_html("产品越来越便宜，信任越来越贵，自媒体的下半场才刚刚开始")


def test_publish_refused_keeps_the_draft(tmp_path: Path) -> None:
    """补发时直接发 X；被拒（9/24 就是 403 要 Premium）就退回草稿，不算失败。"""
    import urllib.error

    (tmp_path / "a.md").write_text(ARTICLE, encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG....")
    cover = tmp_path / "x-cover.jpg"
    cover.write_bytes(b"\xff\xd8....")

    class Refuse(Fake):
        def __call__(self, request):
            if request.full_url.endswith("/publish"):
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"detail":"Premium required"}'))
            return super().__call__(request)

    done = x_article.publish_article(tmp_path / "a.md", cover=cover, publish=True, creds=CREDS, send=Refuse())
    assert done["published"] is False and done["id"] == "a1" and "已存草稿" in done["message"]


def test_a_dropped_connection_is_retried_but_a_lost_reply_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """10/3 补发：「连不上 X：SSL UNEXPECTED_EOF」，过一会儿再连就好了。
    连接、握手时断的（URLError）X 还没收到请求，自动再试；读回应时断的可能已经发出去了，不重试。"""
    import ssl
    import urllib.error
    import urllib.request

    waits: list[float] = []
    monkeypatch.setattr(x_article.time, "sleep", waits.append)
    request = urllib.request.Request("https://api.x.com/2/articles/draft", data=b"{}")
    tries = {"n": 0}

    def flaky(_request):
        tries["n"] += 1
        if tries["n"] < 3:
            raise urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol"))
        return io.BytesIO(b'{"data": {"id": "a1"}}')

    assert x_article._call(request, flaky) == {"data": {"id": "a1"}}
    assert tries["n"] == 3 and waits == list(x_article.RETRY_WAITS)

    def down(_request):
        raise urllib.error.URLError(ssl.SSLEOFError(8, "EOF"))

    with pytest.raises(XError, match="连不上 X"):
        x_article._call(request, down)

    lost = {"n": 0}

    def reply_lost(_request):
        lost["n"] += 1
        raise ConnectionResetError("reset while reading")

    with pytest.raises(XError, match="连不上 X"):
        x_article._call(request, reply_lost)
    assert lost["n"] == 1
