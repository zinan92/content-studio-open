from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from content_studio import publisher
from content_studio.extras.autopost import wechat_publish as wx

CREDS = {"appid": "wx1", "secret": "s"}
ARTICLE = "# 标题在这\n\n第一段，**关键一句**，后面还有。\n\n## 从卖课到卖产品\n\n- 甲\n- 乙\n\n1. 一\n2. 二\n\n> 信任是最贵的产品\n"


class Fake:
    def __init__(self, *, publish_status: int = 0, submit_error: int | None = None) -> None:
        self.calls: list[tuple[str, bytes | None]] = []
        self.publish_status, self.submit_error = publish_status, submit_error

    def __call__(self, request):
        url = request.full_url
        self.calls.append((url.split("?")[0], request.data))
        if "/token" in url:
            reply = {"access_token": "T"}
        elif "add_material" in url:
            reply = {"media_id": "THUMB"}
        elif "uploadimg" in url:
            reply = {"url": "https://mmbiz.qpic.cn/pic1"}
        elif "draft/add" in url:
            reply = {"media_id": "DRAFT"}
        elif "draft/get" in url:
            reply = {"news_item": [{"title": "标题在这"}]}
        elif "freepublish/submit" in url:
            reply = {"errcode": self.submit_error, "errmsg": "x"} if self.submit_error else {"publish_id": "P1"}
        else:
            reply = {"publish_status": self.publish_status, "article_detail": {"item": [{"article_url": "https://mp.weixin.qq.com/s/abc"}]}}
        return io.BytesIO(json.dumps(reply).encode())


def test_markdown_becomes_olive_inline_html() -> None:
    title, digest, body = wx.render_html(ARTICLE)
    assert title == "标题在这" and digest.startswith("第一段，关键一句")
    assert "class=" not in body and "<style" not in body
    assert 'border-bottom:2px solid #ed7b2f' in body and ">关键一句<" in body
    assert "<ul" in body and "<ol" in body and ">01<" in body and "信任是最贵的产品" in body
    assert body.count("<li") == 4


@pytest.mark.skipif(not Path.home().joinpath(".claude/skills/gzh-design/scripts/validate_gzh_html.py").is_file(), reason="gzh-design not installed")
def test_output_passes_the_gzh_design_validator(tmp_path: Path) -> None:
    page = tmp_path / "a.html"
    page.write_text(wx.render_html(ARTICLE)[2], encoding="utf-8")
    done = subprocess.run([sys.executable, str(Path.home() / ".claude/skills/gzh-design/scripts/validate_gzh_html.py"), str(page)],
                          capture_output=True, text=True, check=False)
    assert "完全合规" in done.stdout, done.stdout


@pytest.mark.skipif(not shutil.which("magick"), reason="imagemagick missing")
def test_draft_then_readback_and_publish_only_when_asked(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    cover = tmp_path / "c.jpg"
    subprocess.run(["magick", "-size", "1440x1080", "xc:white", str(cover)], check=True)
    fake = Fake()
    r = wx.publish_article(article, cover=cover, creds=CREDS, send=fake, wait=lambda s: None)
    assert [c[0].rsplit("/", 1)[-1] for c in fake.calls] == ["token", "add_material", "add", "get"]
    draft = json.loads(fake.calls[2][1].decode("utf-8"))["articles"][0]
    assert draft["thumb_media_id"] == "THUMB" and draft["title"] == "标题在这"
    assert "标题在这".encode() in fake.calls[2][1]  # 原样 UTF-8，不是 \\u 转义
    assert r["published"] is False and "草稿箱" in r["message"]
    assert (tmp_path / "公众号封面.jpg").is_file()  # 4:3 垫成了 2.35:1

    fake = Fake()
    r = wx.publish_article(article, cover=cover, publish=True, creds=CREDS, send=fake, wait=lambda s: None)
    assert r["published"] is True and r["url"] == "https://mp.weixin.qq.com/s/abc"

    r = wx.publish_article(article, cover=cover, publish=True, creds=CREDS, send=Fake(submit_error=48001), wait=lambda s: None)
    assert r["published"] is False and "没有这个接口的权限" in r["message"]


def test_errors_are_explained() -> None:
    fake = lambda request: io.BytesIO(json.dumps({"errcode": 40164, "errmsg": "invalid ip"}).encode())  # noqa: E731
    with pytest.raises(wx.WechatError, match="白名单"):
        wx.get_token(CREDS, send=fake)
    with pytest.raises(wx.WechatError, match="# 标题"):
        wx.render_html("没有标题")


def test_desk_sends_the_article_and_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "python_with", lambda mods, candidates=None: "/py")
    with pytest.raises(publisher.PublishError, match="研习室文章"):
        publisher.build_payload("wechat_mp", "draft", video=None, copy=None)
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    cover = tmp_path / "w.jpg"
    cover.write_bytes(b"1")
    argv = publisher.command_for(publisher.build_payload("wechat_mp", "draft", video=None, copy=None, article=article, cover=cover))
    assert argv[1:3] == ["-m", "content_studio.extras.autopost.wechat_publish"] and "--publish" not in argv and str(cover) in argv
    with pytest.raises(publisher.PublishError, match="发布方式无效"):  # 9/27 作者：公众号只存草稿箱
        publisher.build_payload("wechat_mp", "publish", video=None, copy=None, article=article, cover=cover)


def test_yanxishi_key_travels_by_env_not_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """研习室：钥匙从 secrets.yaml 读、走环境变量；同一选题 brief_id 固定，再发会更新同一篇。"""
    monkeypatch.setattr(publisher, "_secret", lambda section, key: {"workbench_key": "K" * 96, "env_id": "cloudbase-test"}[key])
    folder = tmp_path / "topic-21"
    folder.mkdir()
    article = folder / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    with pytest.raises(publisher.PublishError, match="发布方式无效"):  # 9/29 作者：先都存草稿，他自己确认
        publisher.build_payload("miniprogram", "publish", video=None, copy=None, article=article)
    payload = publisher.build_payload("miniprogram", "draft", video=None, copy=None, article=article)
    argv = publisher.command_for(payload)
    assert argv[0] == "node" and argv[1].endswith("xingqiu-shell/scripts/workbench-submit.mjs")
    assert argv[argv.index("--env") + 1] == "cloudbase-test" and argv[argv.index("--brief-id") + 1] == "content-studio-topic-21"
    assert "--publish" not in argv and not any("K" * 96 in a for a in argv)

    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw.get("env"))
        return subprocess.CompletedProcess(cmd, 0, '{"ok": true, "articleId": "article_x", "published": true, "message": "已发布到研习室"}', "")

    monkeypatch.setattr(publisher.subprocess, "run", fake_run)
    result = publisher.run(payload)
    assert result.get("ok") is True and seen["env"]["WORKBENCH_KEY"] == "K" * 96
    assert not any("K" * 96 in a for a in seen["cmd"])


@pytest.mark.skipif(not shutil.which("magick"), reason="imagemagick missing")
def test_saving_again_updates_the_same_draft(tmp_path: Path) -> None:
    """9/27：每存一次就多一份草稿，草稿箱里攒了 3 份一样的。再存要更新原来那份。"""
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    cover = tmp_path / "c.jpg"
    subprocess.run(["magick", "-size", "1440x1080", "xc:white", str(cover)], check=True)
    wx.publish_article(article, cover=cover, creds=CREDS, send=Fake(), wait=lambda s: None)
    fake = Fake()
    r = wx.publish_article(article, cover=cover, creds=CREDS, send=fake, wait=lambda s: None)
    steps = [c[0].rsplit("/", 1)[-1] for c in fake.calls]
    assert "update" in steps and "add" not in steps and r["updated"] is True and r["media_id"] == "DRAFT"
    assert json.loads(fake.calls[steps.index("update")][1].decode("utf-8"))["media_id"] == "DRAFT"

    class Gone(Fake):  # 上次那份在后台删了
        def __call__(self, request):
            if "draft/update" in request.full_url:
                self.calls.append((request.full_url.split("?")[0], request.data))
                return io.BytesIO(json.dumps({"errcode": 40007, "errmsg": "invalid media_id"}).encode())
            return super().__call__(request)

    gone = Gone()
    r = wx.publish_article(article, cover=cover, creds=CREDS, send=gone, wait=lambda s: None)
    assert [c[0].rsplit("/", 1)[-1] for c in gone.calls].count("add") == 1 and r["updated"] is False


@pytest.mark.skipif(not shutil.which("magick"), reason="imagemagick missing")
def test_article_illustrations_are_uploaded_into_the_body(tmp_path: Path) -> None:
    """作者 9/27：公众号文章也要带配图。本地图传到微信，正文里换成微信的地址。"""
    (tmp_path / "illustrations").mkdir()
    subprocess.run(["magick", "-size", "320x180", "xc:white", str(tmp_path / "illustrations" / "01-a.png")], check=True)
    article = tmp_path / "article.md"
    article.write_text(ARTICLE + "\n![小黑推加息](illustrations/01-a.png)\n", encoding="utf-8")
    cover = tmp_path / "c.jpg"
    subprocess.run(["magick", "-size", "1440x1080", "xc:white", str(cover)], check=True)
    fake = Fake()
    wx.publish_article(article, cover=cover, creds=CREDS, send=fake, wait=lambda s: None)
    steps = [c[0].rsplit("/", 1)[-1] for c in fake.calls]
    assert steps.count("uploadimg") == 1
    content = json.loads(fake.calls[steps.index("add")][1].decode("utf-8"))["articles"][0]["content"]
    assert 'src="https://mmbiz.qpic.cn/pic1"' in content and "illustrations/01-a.png" not in content


def test_flaky_network_is_retried_but_wechat_errors_are_not() -> None:
    import urllib.request as ur

    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
        return io.BytesIO(b'{"url": "https://mmbiz.qpic.cn/x"}')

    assert wx._call(ur.Request("https://api.weixin.qq.com/x"), flaky, pause=lambda s: None)["url"].startswith("https://")
    assert len(calls) == 3
    with pytest.raises(wx.WechatError, match="试了 4 次"):
        wx._call(ur.Request("https://api.weixin.qq.com/x"), lambda r: (_ for _ in ()).throw(OSError("eof")), pause=lambda s: None)


def test_draft_check_uses_stable_token_and_only_missing_draft_counts_as_gone() -> None:
    """10/8：群发之后草稿从草稿箱里没了，工作台靠这个知道「群发了」。令牌用 stable_token，不把正在用的那个挤掉；
    只有「没有这份草稿」（40007）算没了，IP 白名单这类错照常报，不能当成发了。"""
    def fake(draft_reply: dict):
        calls: list[str] = []

        def send(request):
            calls.append(request.full_url.split("?")[0])
            if "stable_token" in request.full_url:
                assert json.loads(request.data)["force_refresh"] is False
                return io.BytesIO(json.dumps({"access_token": "T"}).encode())
            return io.BytesIO(json.dumps(draft_reply).encode())
        return send, calls

    send, calls = fake({"news_item": [{"title": "标题在这"}]})
    assert wx.draft_exists("M1", creds=CREDS, send=send) is True
    assert calls == [wx.STABLE_TOKEN_URL, f"{wx.API}/draft/get"]
    send, _ = fake({"errcode": 40007, "errmsg": "invalid media_id"})
    assert wx.draft_exists("M1", creds=CREDS, send=send) is False
    send, _ = fake({"errcode": 40164, "errmsg": "invalid ip 1.2.3.4"})
    with pytest.raises(wx.WechatError):
        wx.draft_exists("M1", creds=CREDS, send=send)
