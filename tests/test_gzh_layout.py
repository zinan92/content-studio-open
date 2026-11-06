from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import gzh_layout, publisher
from content_studio.writer import WriterError

ARTICLE = "# 标题在这\n\n第一段，**关键一句**，后面还有。\n\n## 从卖课到卖产品\n\n- 甲方\n- 乙方\n\n> 信任是最贵的产品\n"
GOOD = ('<section style="max-width:677px"><p style="font-size:24px"><span leaf="">标题在这</span></p>'
        '<p><span leaf="">第一段，</span><span style="border-bottom:2px solid #ed7b2f"><span leaf="">关键一句</span></span><span leaf="">，后面还有。</span></p>'
        '<p><span leaf="">01 从卖课到卖产品</span></p><ul><li><span leaf="">甲方</span></li><li><span leaf="">乙方</span></li></ul>'
        '<section><p><span leaf="">信任是最贵的产品</span></p></section></section>')


def _reply(markup: str) -> str:
    return f"排好了\n<<<ARTICLE>>>\n{markup}\n<<<END>>>"


def test_fidelity_catches_dropped_or_invented_text() -> None:
    gzh_layout.check_fidelity(ARTICLE, GOOD)
    with pytest.raises(WriterError, match="丢"):
        gzh_layout.check_fidelity(ARTICLE, GOOD.replace("信任是最贵的产品", ""))
    padded = GOOD.replace("</section></section>", "<p>" + "关注我获取更多干货内容每天更新" * 20 + "</p></section></section>")
    with pytest.raises(WriterError, match="多出"):
        gzh_layout.check_fidelity(ARTICLE, padded)


def test_layout_retries_then_saves_and_goes_stale_when_article_changes(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    prompts: list[str] = []

    def fn(prompt: str) -> str:
        prompts.append(prompt)
        return _reply("<section><p>只剩一句</p></section>") if len(prompts) == 1 else _reply(GOOD)

    meta = gzh_layout.layout(article, write_fn=fn, validator=tmp_path / "none.py")
    assert len(prompts) == 2 and "上一次的结果有问题" in prompts[1] and "橄榄手记" in prompts[0] and "不增不删" in prompts[0]
    assert meta["theme"] == "橄榄手记" and gzh_layout.current(article) == tmp_path / gzh_layout.FILENAME
    assert gzh_layout.state(article)["has_layout"] is True and gzh_layout.state(article)["stale"] is False
    article.write_text(ARTICLE + "\n补一句。\n", encoding="utf-8")
    assert gzh_layout.current(article) is None and gzh_layout.state(article)["stale"] is True
    assert publisher._gzh_html(str(article)) == ""  # 作废的排版不拿去发


@pytest.mark.skipif(not gzh_layout.VALIDATOR.is_file(), reason="gzh-design not installed")
def test_real_validator_is_applied() -> None:
    gzh_layout.validate('<section style="margin:0"><p style="margin:0"><span leaf="">正文</span></p></section>')
    with pytest.raises(WriterError, match="合规"):
        gzh_layout.validate('<section class="x"><style>p{}</style><p>正文</p></section>')


def test_hero_placeholder_doodle_is_removed() -> None:
    hero = ('<section style="display:flex"><section style="flex:1"><p><span leaf="">标题</span></p></section>'
            '<section style="flex-shrink:0;width:112px;border:1px dashed #bfc1b7;border-radius:6px;padding:8px;">\n'
            '<svg width="72" height="72"><circle cx="1" cy="1" r="1"></circle></svg>\n'
            '<span style="font-size:8px;"><span leaf="">DOODLE</span></span>\n</section></section>')
    out = gzh_layout.drop_placeholders(hero)
    assert "DOODLE" not in out and "<svg" not in out and "标题" in out
