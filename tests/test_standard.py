from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from content_studio import qa, standard


GUIDE = """---
name: content-qa
description: 作者 的内容 QA。
---

# 标准

## 四、输出格式

```
## 能不能拍：可以拍
```

## 参考与致谢

- 来源甲
"""


@pytest.fixture
def guide(tmp_path: Path) -> Path:
    path = tmp_path / "SKILL.md"
    path.write_text(GUIDE, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_a_saved_rule_reaches_the_scorer(guide: Path) -> None:
    """The whole point: a lesson from a teardown must show up in what QA actually reads."""
    standard.add_rule("高客单要靠认知型深度内容", source="一勾工作号", path=guide, today=date(2026, 9, 20))
    assert "高客单要靠认知型深度内容" in qa.load_guide(guide)


def test_rules_go_above_the_credits_and_leave_the_rest_of_the_file_alone(guide: Path) -> None:
    before = guide.read_text(encoding="utf-8")
    standard.add_rule("第一条", path=guide, today=date(2026, 9, 20))
    standard.add_rule("第二条", source="小胡", path=guide, today=date(2026, 9, 21))
    after = guide.read_text(encoding="utf-8")

    # Frontmatter is what makes Claude Code find the skill; it must survive untouched.
    assert after.startswith(before[: before.index("\n# 标准")])
    assert after.index(standard.HEADING) < after.index(standard.ANCHOR)
    assert after.rstrip().endswith("- 来源甲")
    assert guide.stat().st_mode & 0o777 == 0o600

    saved = standard.rules(guide)
    assert [(r["at"], r["source"], r["text"]) for r in saved] == [("2026-09-20", "", "第一条"), ("2026-09-21", "小胡", "第二条")]

    assert standard.remove_rule(saved[0]["id"], guide) is True
    assert [r["text"] for r in standard.rules(guide)] == ["第二条"]
    assert standard.remove_rule("nosuch", guide) is False

    standard.remove_rule(saved[1]["id"], guide)
    assert standard.rules(guide) == []
    # Removing the last rule leaves the file exactly as it was before the first one.
    assert guide.read_text(encoding="utf-8") == before


def test_duplicate_blank_and_oversized_rules_are_refused(guide: Path) -> None:
    standard.add_rule("只此一条", path=guide)
    with pytest.raises(standard.StandardError, match="已经在标准里"):
        standard.add_rule(" 只此一条 ", path=guide)
    with pytest.raises(standard.StandardError, match="空的"):
        standard.add_rule("   ", path=guide)
    with pytest.raises(standard.StandardError, match="最多"):
        standard.add_rule("长" * (standard.MAX_RULE_CHARS + 1), path=guide)


def test_a_rule_that_would_push_the_guide_past_what_qa_reads_is_refused(guide: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the cap, QA silently scores against a guide missing its newest rules while Anna still sees them."""
    monkeypatch.setattr(standard, "MAX_GUIDE_CHARS", 120)
    with pytest.raises(standard.StandardError, match="太长了"):
        standard.add_rule("这一条会把文件撑过上限", path=guide)
    assert standard.BLOCK_START not in guide.read_text(encoding="utf-8")
