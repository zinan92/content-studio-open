"""进项每一条的「发 X」（10/5 作者）：按他的风格写建议稿，他删改、他点了才发。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import outline
from content_studio.extras.xline import x_suggest
from test_x_line import client_factory  # noqa: F401 - fixture

ITEM = {"title": "OpenAI 发了新模型", "text": "OpenAI 今天发布 GPT-9，价格降了 80%。", "url": "https://example.com/a", "source": "AI 日报"}


def test_code_rejects_made_up_experience_invented_numbers_and_long_posts() -> None:
    assert x_suggest.check("OpenAI 说 GPT-9 降价 80%。慢就是快。\nhttps://example.com/a", ITEM) is None
    assert "经历" in x_suggest.check("我试了一下 GPT-9，真香。", ITEM)
    assert "我的客户" in x_suggest.check("我的客户都在用。", ITEM)
    assert "数字" in x_suggest.check("GPT-9 降价 95%。", ITEM)
    assert "太长" in x_suggest.check("长" * 141, ITEM)
    assert x_suggest.x_length("看 https://e.com/a") == 2 + 1 + 15  # 和发帖用同一把尺子：中文算 2，链接按实际字数


def test_suggest_rewrites_once_then_gives_up_and_always_carries_the_link() -> None:
    prompts: list[str] = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return "<<<POST>>>\n我用了 GPT-9，降价 80%。\n<<<END>>>"
        return "<<<POST>>>\nOpenAI 说 GPT-9 降价 80%。AI 会替代大部分脑力劳动。\n<<<END>>>"

    post = x_suggest.suggest(ITEM, style="# X 写作风格\n短句。", beliefs="AI 会替代大部分脑力劳动", write_fn=model)
    assert post.endswith("https://example.com/a")  # 模型忘了带出处：代码补上
    assert len(prompts) == 2 and "编了他没说过的经历" in prompts[1]
    assert "不许写成 作者 的原创" in prompts[0] and "AI 会替代大部分脑力劳动" in prompts[0]
    with pytest.raises(x_suggest.SuggestError, match="再点一次"):
        x_suggest.suggest(ITEM, style="s", beliefs="", write_fn=lambda p: "<<<POST>>>\n我试了，涨了 999%。\n<<<END>>>")


def test_style_file_goes_to_obsidian_never_into_the_repo_and_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(outline.WORKFLOWS_ENV, raising=False)
    assert x_suggest.style_path() == tmp_path / "home" / x_suggest.STYLE_FILE  # 没配 Obsidian：本机配置目录，不进仓库示例
    flows = tmp_path / "flows"
    monkeypatch.setenv(outline.WORKFLOWS_ENV, str(flows))
    assert x_suggest.style_path() == flows / x_suggest.STYLE_FILE
    vault = tmp_path / "v"
    (vault / x_suggest.PUBLISHED_FOLDER).mkdir(parents=True)
    (vault / x_suggest.PUBLISHED_FOLDER / "a.md").write_text("---\nt: 1\n---\nAI 时代赚钱只靠常识。", encoding="utf-8")
    seen: list[str] = []
    path, style, fresh = x_suggest.ensure_style(vault, lambda p: seen.append(p) or "# X 写作风格\n" + "短句，先下判断。" * 20)
    assert fresh and path.is_file() and "AI 时代赚钱只靠常识" in seen[0]
    path.write_text("# X 写作风格\n我自己改过的", encoding="utf-8")
    assert x_suggest.ensure_style(vault, lambda p: pytest.fail("不该重写"))[1] == "# X 写作风格\n我自己改过的"


def test_intake_post_to_x_end_to_end(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    flows = tmp_path / "flows"
    monkeypatch.setenv(outline.WORKFLOWS_ENV, str(flows))
    park_os = tmp_path / "worldview.md"
    park_os.write_text("# 世界观\n## 二、我信什么\n- 慢就是快。\n## 三、我怎么判断\n### 交易\n- 只做看得懂的。\n## 四、我怎么干活\n", encoding="utf-8")
    monkeypatch.setenv(x_suggest.WORLDVIEW_ENV, str(park_os))
    vault = tmp_path / "vault"
    (vault / "003_原始输出").mkdir(parents=True)
    (vault / "003_原始输出" / "always-on.md").write_text("# Always On\n工具一直在变。", encoding="utf-8")
    (vault / "002_个人收藏").mkdir()
    (vault / "002_个人收藏" / "a.md").write_text("---\ntitle: 别人的文章\nsource: https://example.com/a\nauthor: 某人\n---\nGPT-9 降价 80%。", encoding="utf-8")
    prompts: list[str] = []

    def write(prompt: str) -> str:
        prompts.append(prompt)
        if "总结他的说话、写作风格" in prompt:
            return "# X 写作风格\n" + "短句，先下判断。" * 20
        if "整理成可以直接发 X 的帖子" in prompt:
            return "<<<POST>>>\n工具一直在变。\n<<<END>>>"
        if "抖音视频" in prompt:
            return "<<<POST>>>\n千雪这条爆了。慢就是快。\n<<<END>>>"
        return "<<<POST>>>\n某人说 GPT-9 降价 80%。慢就是快。\n<<<END>>>"

    sent: list[str] = []
    client: TestClient = client_factory(write_fn=write, x_post_fn=lambda text: sent.append(text) or {"id": "1", "url": "https://x.com/i/web/status/1"})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})

    r = client.post("/api/xline/suggest", json={"kind": "note", "path": "002_个人收藏/a.md"}).json()
    assert r["own"] is False and r["style_new"] is True and r["posts"] == ["某人说 GPT-9 降价 80%。慢就是快。\nhttps://example.com/a"]
    assert (flows / x_suggest.STYLE_FILE).is_file() and "工具一直在变" in prompts[0]  # 风格从他自己的话里来
    assert "慢就是快" in prompts[1] and "只做看得懂的" not in prompts[1]  # 判断取自 世界观文件，交易那节不进来
    assert not sent  # 只写建议，没发

    again = client.post("/api/xline/suggest", json={"kind": "note", "path": "002_个人收藏/a.md"}).json()
    assert again["style_new"] is False and sum("总结他的说话" in p for p in prompts) == 1

    own = client.post("/api/xline/suggest", json={"kind": "note", "path": "003_原始输出/always-on.md"}).json()
    assert own["own"] is True and own["posts"] == ["工具一直在变。"]  # 他自己的话：只整理，不按风格重写

    feed = client.post("/api/xline/suggest", json={"kind": "feed", "url": "https://www.douyin.com/video/9", "title": "爆款", "author": "千雪"}).json()
    assert feed["source_id"] == "in:feed:https://www.douyin.com/video/9" and feed["posts"][0].endswith("https://www.douyin.com/video/9")
    assert client.post("/api/xline/suggest", json={"kind": "note"}).status_code == 400

    client.post("/api/xline/post", json={"text": r["posts"][0], "source_id": r["source_id"]})
    assert sent == [r["posts"][0]]  # 他点了「确定」才发
    assert client.get("/api/xline").json()["today"] == 1  # X 单独一条线的「今天几条」也算上
