from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from content_studio import qa
from content_studio.extras.team import anna
from content_studio.extras.positioning import positioning


DOC = """# 作者 的定位

## 我的定位（三问）

### 一、我是谁
十年交易，从 0 建了 AI 交易系统。

### 三、我卖给客户什么
状态：待拍板

## 待拍板（Anna 提议）

<!-- 工作台维护：Anna 提议 · 开始 -->
<!-- 工作台维护：Anna 提议 · 结束 -->
"""


@pytest.fixture
def doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    guide = tmp_path / "SKILL.md"
    guide.write_text("---\nname: content-qa\n---\n\n# 标准\n", encoding="utf-8")
    monkeypatch.setenv(qa.QA_GUIDE_ENV, str(guide))
    path = tmp_path / positioning.FILE_NAME
    path.write_text(DOC, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_lives_next_to_the_qa_skill(doc: Path) -> None:
    assert positioning.positioning_path() == doc
    data = positioning.read()
    assert data["exists"] and "我是谁" in data["markdown"] and data["proposals"] == []


def test_missing_file_is_a_state_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(qa.QA_GUIDE_ENV, str(tmp_path / "SKILL.md"))
    data = positioning.read()
    assert data["exists"] is False and data["markdown"] == ""
    with pytest.raises(positioning.PositioningError):
        positioning.add_proposal("先写三问", path=tmp_path / "nope.md")


def test_proposals_only_touch_the_marker_block(doc: Path) -> None:
    before = doc.read_text(encoding="utf-8")
    a = positioning.add_proposal("只对博主，交易者留在私域", source="Anna", today=date(2026, 9, 24))
    positioning.add_proposal("标题主语是观众不是我", today=date(2026, 9, 25))
    after = doc.read_text(encoding="utf-8")

    # 作者's words above the block are byte-for-byte his.
    assert after.startswith(before[: before.index(positioning.BLOCK_START)])
    assert doc.stat().st_mode & 0o777 == 0o600
    assert [(p["at"], p["source"], p["text"]) for p in positioning.proposals()] == [
        ("2026-09-24", "Anna", "只对博主，交易者留在私域"),
        ("2026-09-25", "", "标题主语是观众不是我"),
    ]
    with pytest.raises(positioning.PositioningError):
        positioning.add_proposal("只对博主，交易者留在私域")  # same sentence twice
    with pytest.raises(positioning.PositioningError):
        positioning.add_proposal("a｜b")  # the separator itself

    assert positioning.remove_proposal(a["id"]) is True
    assert positioning.remove_proposal(a["id"]) is False
    assert [p["text"] for p in positioning.proposals()] == ["标题主语是观众不是我"]


def test_a_file_without_a_block_gets_one_at_the_end(tmp_path: Path) -> None:
    path = tmp_path / "positioning.md"
    path.write_text("# 定位\n\n我是谁：略\n", encoding="utf-8")
    positioning.add_proposal("卖定制软件", path=path, today=date(2026, 9, 24))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 定位\n\n我是谁：略\n")
    assert text.index(positioning.HEADING) < text.index(positioning.BLOCK_START)
    assert positioning.proposals(path)[0]["text"] == "卖定制软件"


def test_anna_reads_the_positioning_and_knows_the_action(doc: Path, tmp_path: Path) -> None:
    role = tmp_path / "Anna.md"
    role.write_text("# Anna\n\n让对的人看得更久。\n", encoding="utf-8")
    soul = anna.load_soul(role, tmp_path / "SKILL.md")
    assert "作者 的定位" in soul["text"] and "十年交易" in soul["text"]
    assert str(doc) in soul["sources"]
    assert "记进定位" in anna.WORKBENCH_RULES
    assert anna.ACTION_KINDS["记进定位"] == "positioning"
    assert anna.SCOPE_LABELS["positioning"] == "定位"


def test_structured_data_sits_beside_the_markdown(doc: Path) -> None:
    import json

    assert positioning.read_data() is None and positioning.read()["data"] is None
    data = doc.with_name(positioning.DATA_NAME)
    data.write_text(json.dumps({"company": {"name": "内容工作台"}, "questions": []}, ensure_ascii=False), encoding="utf-8")
    assert positioning.read_data()["company"]["name"] == "内容工作台"
    assert positioning.read()["data"]["company"]["name"] == "内容工作台"
    data.write_text("{not json", encoding="utf-8")
    with pytest.raises(positioning.PositioningError):
        positioning.read_data()
    data.write_text('{"company": {}}', encoding="utf-8")
    with pytest.raises(positioning.PositioningError):
        positioning.read_data()


def test_page_is_six_tabs_like_the_codex_draft_with_the_words_in_his_json() -> None:
    """10/6 作者：照 Codex 的稿子分六个页签，一模一样（再加一点 monday.com 的颜色），#positioning/offers 能直达。
    版式在 positioning.js；字在 positioning.json 的 page / tabs / flow 和各块里，JS 里不写他的话（别人装了是别人的字）。"""
    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    js = (static / "positioning.js").read_text(encoding="utf-8")
    for key, label in (("overview", "定位三问"), ("growth", "增长飞轮"), ("difference", "差异化"),
                       ("offers", "服务与定价"), ("profile", "对外简介"), ("principles", "原则与自测"), ("persona", "我的形象")):
        assert f"['{key}', '{label}']" in js
    assert "cs-pos-tab" in js and "#positioning/${POS.tab}" in js
    app = (static / "app.js").read_text(encoding="utf-8")
    assert "#positioning/${POS.tab}" in app and "POS_TAB_KEYS" in app
    # 新键都可选：p.tabs / p.flow / page 没有时退回老字段
    assert "p.tabs || {}" in js and "p.flow ||" in js and "p.page || {}" in js and "c.core_title ||" in js
    # Codex 稿里的字在他的 json 里，不写死在页面代码里
    for words in ("让一次交付", "从第一位客户开始", "就是我的差异", "每周回来，对齐一次", "一个人的内容生产线"):
        assert words not in js
    assert "<th>服务</th><th>价格</th><th>规格</th><th>交付内容</th>" in js
    # 颜色：10/9 起 tone-1…5 全用全站强调色（不再五种颜色）；样式表里有，且不在 JS 里拼 style=
    css = (static / "styles.css").read_text(encoding="utf-8")
    assert ".tone-1,.tone-2,.tone-3,.tone-4,.tone-5{--tone:var(--accent)}" in css and ".pos-pill{" in css and ".pos-tile{" in css
    assert 'style="' not in js
