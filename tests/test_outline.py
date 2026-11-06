from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import outline
from content_studio.writer import WriterError

HOOKS = "\n".join(f"{i}. 「暴论第 {i} 条：你的粉丝一分钱都不值。」（绝对否定 · 靠原文「信任变贵了」那段）" for i in range(1, 7))
POINTS = """### 论点 A：产品变便宜了，信任才是贵的那头
证据：原文里的推理——产品从一百个变成一万个，用户挑不过来。

### 论点 B：分发权正在从平台掉到个人手里
证据：要补 —— 去后台截一张「近 30 天收入构成」的图，圈出哪部分是你本人在场才赚到的。

### 论点 C：做产品的门槛没了
证据：作者自己写代码做了内容工作台和研习室小程序，都在用。"""
GOOD = f"""# 未来的分发者

## 主线
分发权正在从平台下沉到每一个有私域流量的人。

## 开头候选
{HOOKS}

## 中间骨架
{POINTS}

## 结尾
如果你有私域流量但不知道怎么变现，欢迎来找我。
"""


@pytest.fixture
def workflows(tmp_path: Path) -> Path:
    """测试不读 作者 真实 vault 里的框架——他随时会改，改一次测试就开始飘。"""
    root = tmp_path / "workflows"
    root.mkdir()
    (root / outline.FRAMEWORK_FILE).write_text(
        "---\nmode: skeleton\n---\n\n# 一勾式骨架\n\n用绝对词，但不许硬拗。证据没有的写成一行具体的待办。\n",
        encoding="utf-8",
    )
    return root


def test_four_sections_are_required() -> None:
    assert outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>").startswith("# 未来的分发者")
    with pytest.raises(WriterError, match="没有按格式"):
        outline.extract_outline("模型今天话很多，但没给我标记")
    with pytest.raises(WriterError, match="缺少标题"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('# 未来的分发者', '未来的分发者', 1)}\n<<<END>>>")
    # 四节都是下游真会读的：主线给开头检查，候选给反差，骨架给痛点，结尾给交付。
    for name in outline.SECTIONS:
        with pytest.raises(WriterError, match=f"缺少「{name}」"):
            outline.extract_outline(f"<<<ARTICLE>>>\n{GOOD.replace('## ' + name, '## 别的')}\n<<<END>>>")


def test_park_needs_enough_hooks_to_choose_from() -> None:
    """他要的是挑，不是收一条。给一条等于替他做了决定。"""
    thin = GOOD.replace(HOOKS, "1. 「只给一条。」")
    with pytest.raises(WriterError, match="开头候选要 5–10 条"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{thin}\n<<<END>>>")


def test_one_argument_is_not_a_skeleton() -> None:
    only_one = GOOD.replace(POINTS, "### 论点 A：就一个\n证据：无。")
    with pytest.raises(WriterError, match="至少 2 个论点"):
        outline.extract_outline(f"<<<ARTICLE>>>\n{only_one}\n<<<END>>>")


def test_framework_drives_the_prompt_and_no_full_script(workflows: Path) -> None:
    text = outline.load_framework(workflows)
    prompt = outline.build_prompt({"title": "t", "memo": "结尾用：欢迎来找我"}, [], framework=text)
    assert "用绝对词，但不许硬拗" in prompt and "结尾用：欢迎来找我" in prompt
    assert "不要写成稿" in prompt and "不写口播全文" in prompt
    assert "写成一行具体的待办" in prompt
    adjusted = outline.build_prompt({"title": "t"}, [], framework="F", adjustments=["前 15 秒说结论"])
    assert "最近一次每周复盘" not in adjusted and "前 15 秒说结论" not in adjusted
    assert "每周复盘" not in outline.build_prompt({"title": "t"}, [], framework="F")


def test_missing_framework_says_which_file(tmp_path: Path) -> None:
    with pytest.raises(WriterError, match="找不到框架文件"):
        outline.load_framework(tmp_path)
    (tmp_path / outline.FRAMEWORK_FILE).write_text("---\nmode: skeleton\n---\n", encoding="utf-8")
    with pytest.raises(WriterError, match="是空的"):
        outline.load_framework(tmp_path)


def test_write_and_read_back(tmp_path: Path, workflows: Path) -> None:
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "乱写" if len(calls) == 1 else f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>"

    result = outline.write_outline({"id": 3, "title": "t", "note_paths": []},
                                   vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=fake, workflows=workflows)
    assert "上一次输出有问题" in calls[1]
    assert result["outline_path"].endswith(outline.FILENAME) and result["mode_label"] == outline.LABEL
    data = outline.read_outline({"outline_path": result["outline_path"]})
    assert data["markdown"].startswith("# 未来的分发者") and data["topic_id"] == 3


def test_older_drafts_still_open(tmp_path: Path) -> None:
    """以前写的 outline.md / bookend.md 还得能打开。"""
    for name in ("outline.md", "outline-restructured.md", "bookend.md"):
        legacy = tmp_path / name
        legacy.write_text("# 老稿子\n\n## 主线\n一句话。\n", encoding="utf-8")
        assert outline.read_outline({"outline_path": str(legacy)})["markdown"].startswith("# 老稿子")
    assert outline.read_outline({}) is None
    assert outline.read_outline({"outline_path": str(tmp_path / "没有这个.md")}) is None
