from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import handoff

ARTICLE = """# 你不是没有闭环，你是没有让工作真正结束

> 把连贯决策变成离散决策，才有真正的 closure。

很多人以为，自己之所以没有闭环，是因为结果不够好，或者做得还不够多。

我最近意识到，很多时候都不是。
"""


def test_handoff_writes_only_the_pipeline_entry_not_a_fake_full_package(tmp_path: Path) -> None:
    """作者 那套 wechat-package 有排版、封面、图文 QA、回执——工作台不伪造这些，
    只把正文送到入口，下游照旧跑。"""
    got = handoff.handoff(tmp_path, topic={"id": 7, "title": "有 closure 才算真的闭环"}, markdown=ARTICLE, today="2026-09-21")

    folder = Path(got["folder"])
    assert folder.parent.name == "004_内容加工中"
    written = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert written == ["README.md", "wechat-package/wechat-article.md"]

    article = (folder / "wechat-package" / "wechat-article.md").read_text(encoding="utf-8")
    assert 'title: "你不是没有闭环，你是没有让工作真正结束"' in article
    assert 'author: "作者"' in article
    assert 'summary: "把连贯决策变成离散决策，才有真正的 closure。"' in article
    assert 'from_workbench: "topic-7"' in article
    # 封面是 cover/ 渲染器的产物，工作台留空并说明，不编一个不存在的路径
    assert 'coverImage: ""' in article and "cover/ 渲染器" in article
    # 正文原样带过去，frontmatter 不重复
    assert article.count("# 你不是没有闭环") == 1 and "很多人以为" in article


def test_handoff_never_overwrites_work_already_in_the_pipeline(tmp_path: Path) -> None:
    handoff.handoff(tmp_path, topic={"id": 7, "title": "同一个题"}, markdown=ARTICLE, today="2026-09-21")
    with pytest.raises(handoff.HandoffError, match="已经交接过"):
        handoff.handoff(tmp_path, topic={"id": 7, "title": "同一个题"}, markdown=ARTICLE, today="2026-09-22")


def test_an_article_without_a_heading_is_refused_because_the_pipeline_needs_a_title(tmp_path: Path) -> None:
    with pytest.raises(handoff.HandoffError, match="一级标题"):
        handoff.handoff(tmp_path, topic={"id": 1, "title": "x"}, markdown="没有标题的正文\n\n第二段", today="2026-09-21")


def test_summary_falls_back_to_the_first_paragraph_when_there_is_no_quote(tmp_path: Path) -> None:
    got = handoff.handoff(tmp_path, topic={"id": 2, "title": "无引语"},
                          markdown="# 标题在这\n\n这是第一段正文，应该成为摘要。\n\n第二段。", today="2026-09-21")
    assert got["summary"].startswith("这是第一段正文")
