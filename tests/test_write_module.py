"""park-writing 模块：读清单、关卡、一步一步跑（10/12 作者：流程在 skill 里定，工作台只读）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.extras.xline import write_gates as gates
from content_studio.extras.xline import write_module

MANIFEST = """module: park-writing
version: 2
flows:
  流程1: [opening, density, scarcity, ending, style, check-complete, check-typo]
  流程2: [opening, style, check-typo]
constraints:
  max-change-pct: 50
  keep-order: true
steps:
  opening:
    {title: 开头, group: 写, round: 1, status: whole, prompt: "references/开头.md#三种开头", does: 第一句是判断, output: changes, fix: edit, may-move: first-sentence, on-fail: warn}
  density:
    {title: 高密度骨架, group: 写, round: 1, status: whole, prompt: "references/密度.md", does: 标没付息的段, output: changes, fix: edit, on-fail: warn}
  scarcity:
    {title: 稀缺, group: 写, round: 1, status: split, prompt: "references/共鸣.md#稀缺", does: 让人感到只有他能讲, output: changes, fix: edit, may-add: bridge-sentence, on-fail: warn}
  ending:
    {title: 结尾钩子, group: 写, round: 1, status: whole, prompt: "references/骨架.md#结尾", does: 回扣开头, output: changes, fix: edit, on-fail: warn}
  style:
    {title: 11 条风格, group: 风格, round: 1, status: whole, prompt: "SKILL.md#第 4 步", does: 按 11 点放大, output: changes, fix: edit, on-fail: warn}
  check-complete:
    {title: 完整度, group: 查, round: 1, status: whole, prompt: "references/QA.md#完整度", only: [长文], does: 五项打分, output: changes, fix: comment, on-fail: swap-if-ending-unfinished}
  check-resonance:
    {title: 共鸣面, group: 查, round: 1, status: planned, prompt: null, does: 扩受众, output: changes, fix: edit, may-add: bridge-sentence, on-fail: warn}
  check-typo:
    {title: 错字, group: 查, round: 2, status: whole, prompt: "references/QA.md#只允许改这几种", does: 改错字, output: article, fix: edit, on-fail: warn}
"""
FILES = {
    "references/开头.md": "# 开头\n\n## 三种开头\n\n数字、暴论、直接说。\n\n### 数字\n\n带单位的数字。\n\n## 标题\n\n不相干。\n",
    "references/密度.md": "# 密度\n\n每一段要付息。\n",
    "references/骨架.md": "# 骨架\n\n## 结尾\n\n回扣开头那句。\n\n## 通用禁止\n\n不喊关注。\n",
    "SKILL.md": "---\nname: park-writing\n---\n# 作者 writing\n\n## 第 4 步 整理：怎么说话\n\n1. 先给结论。\n\n## 输出\n\n四行。\n",
    "references/QA.md": "# QA\n\n## 完整度：逐项打分\n\n开头、递进、结尾。\n\n## 价值\n\n痛点。\n\n## 只允许改这几种\n\n错字。\n",
    "references/共鸣.md": "# 共鸣与稀缺\n\n## 共鸣面\n\n扩受众。\n\n## 稀缺\n\n证据放显眼。\n",
}


def make_skill(tmp_path: Path, manifest: str = MANIFEST) -> Path:
    root = tmp_path / "park-writing"
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "module.yaml").write_text(manifest, encoding="utf-8")
    return root


# -- 读清单 ------------------------------------------------------------------------------------

def test_manifest_is_read_in_fixed_order_and_the_budget_comes_from_the_page(tmp_path: Path) -> None:
    root = make_skill(tmp_path)
    m = write_module.load(root)
    assert m.version == 2 and list(m.flows) == ["流程1", "流程2"]
    assert m.constraints["max-change-pct"] == 20 and m.asked_change_pct == 50  # 清单里写的只当建议；页面上的预算默认 20
    assert write_module.load(root, max_change_pct=35).constraints["max-change-pct"] == 35
    assert write_module.load(root, max_change_pct=900).constraints["max-change-pct"] == 50  # 最多能调到 50
    assert [s.id for s in m.ordered()] == ["opening", "density", "scarcity", "ending", "style", "check-complete", "check-typo", "check-resonance"]
    assert [s.id for s in m.round_steps(m.flows["流程1"], 1)] == ["opening", "density", "scarcity", "ending", "style", "check-complete"]  # 第一轮，能跑的
    # 用户的流程只能开关：不管点的先后，顺序按清单
    assert [s.id for s in m.flow_steps(["style", "opening"])] == ["opening", "style"]
    assert m.steps["check-resonance"].runnable is False and m.steps["opening"].may_move == "first-sentence"
    assert m.steps["check-complete"].fix == "comment" and m.steps["opening"].round == 1 and m.steps["check-typo"].round == 2


def test_a_step_reads_only_its_own_section_and_its_version_follows_the_text(tmp_path: Path) -> None:
    root = make_skill(tmp_path)
    m = write_module.load(root)
    assert m.step_text("opening") == "## 三种开头\n\n数字、暴论、直接说。\n\n### 数字\n\n带单位的数字。"  # 到下一个同级标题为止，不含「标题」那节
    assert m.step_text("ending") == "## 结尾\n\n回扣开头那句。"
    before = m.step_version("ending")
    (root / "references/骨架.md").write_text(FILES["references/骨架.md"].replace("回扣开头那句", "落回了解自己"), encoding="utf-8")
    assert write_module.load(root).step_version("ending") != before
    assert write_module.load(root).step_version("opening") == m.step_version("opening")  # 别的步骤不受影响


@pytest.mark.parametrize("old,new,expect", [
    ("keep-order: true", "keep-order: true\n  make-it-good: true", "make-it-good"),            # 不认识的关卡
    ("[opening, density, scarcity, ending, style, check-complete, check-typo]", "[opening, nope]", "nope"),  # 流程里有不存在的步骤
    ('prompt: "references/密度.md"', 'prompt: "references/没有.md"', "规则找不到"),
    ('prompt: "references/骨架.md#结尾"', 'prompt: "references/骨架.md#不存在的标题"', "没有以「不存在的标题」开头的标题"),
    ("status: planned, prompt: null", "status: planned, prompt: x.md", "planned"),
    ("output: changes, fix: edit, on-fail: warn}\n  scarcity", "output: changes, fix: edit, flavour: x, on-fail: warn}\n  scarcity", "flavour"),
    ("round: 1, status: whole, prompt: \"references/密度.md\"", "round: 3, status: whole, prompt: \"references/密度.md\"", "round"),
    ("may-move: first-sentence", "may-move: last-paragraph", "may-move"),
])
def test_a_manifest_the_workbench_does_not_understand_is_refused_with_every_reason(tmp_path: Path, old: str, new: str, expect: str) -> None:
    assert old in MANIFEST
    with pytest.raises(write_module.ModuleError, match=expect):
        write_module.load(make_skill(tmp_path, MANIFEST.replace(old, new, 1)))


def test_without_a_manifest_the_workbench_says_so_instead_of_guessing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", "off")
    assert write_module.available() is False
    root = make_skill(tmp_path)
    (root / "module.yaml").unlink()
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(root))
    assert write_module.available() is False
    with pytest.raises(write_module.ModuleError):
        write_module.load(root)


# -- 关卡 --------------------------------------------------------------------------------------

SENTENCES = [f"这是第{c}句话，讲的是闭环比终局重要，所以小闭环先闭" for c in "一二三四五六七八九十"]
ORIGINAL = "# 闭环\n\n" + "。".join(SENTENCES[:5]) + "。\n\n" + "。".join(SENTENCES[5:]) + "。\n\n所以先完成小闭环，再往上叠业务，这就是我的判断。"
GATES = {"max-change-pct": 10, "keep-order": True, "original-words": True, "no-new-facts": True}


def test_gates_pass_an_unchanged_article_and_ignore_title_and_images() -> None:
    assert gates.check(ORIGINAL, ORIGINAL, constraints=GATES) == []
    with_image = ORIGINAL.replace("\n\n所以", "\n\n![图](illustrations/a.png)\n\n所以")
    assert gates.check(ORIGINAL, with_image, constraints=GATES) == []


def test_gate_stops_big_cuts_new_numbers_and_loose_reordering() -> None:
    cut = "# 闭环\n\n" + "。".join(SENTENCES[:3]) + "。\n\n所以先完成小闭环，再往上叠业务，这就是我的判断。"
    assert any("超过上限 10%" in f for f in gates.check(ORIGINAL, cut, constraints=GATES))
    assert any("原文里没有的数字" in f and "500" in f for f in gates.check(ORIGINAL, ORIGINAL.replace("第三句", "第三句有 500 万人"), constraints=GATES))
    assert any("原文里没有的数字或英文词" in f and "closure" in f for f in gates.check(ORIGINAL, ORIGINAL + "。closure", constraints=GATES))
    swapped = ORIGINAL.replace(SENTENCES[0], "@@").replace(SENTENCES[1], SENTENCES[0]).replace("@@", SENTENCES[1])
    assert any("挪了位置" in f for f in gates.check(ORIGINAL, swapped, constraints={**GATES, "max-change-pct": 30}))


def test_only_the_opening_may_lift_one_sentence_to_the_front() -> None:
    last = "所以先完成小闭环，再往上叠业务，这就是我的判断。"
    many = [f"这是第{i}句话，讲的是闭环比终局重要，所以小闭环先闭" for i in range(30)]
    long_orig = "# 闭环\n\n" + "。".join(many) + "。\n\n" + last
    lifted = "# 闭环\n\n" + last + "\n\n" + "。".join(many) + "。"
    loose = {**GATES, "max-change-pct": 30}
    assert gates.check(long_orig, lifted, constraints=loose, may_move="first-sentence") == []
    assert any("挪了位置" in f for f in gates.check(long_orig, lifted, constraints=loose))
    middle = "# 闭环\n\n" + "。".join(many[:10]) + "。\n\n" + last + "\n\n" + "。".join(many[10:]) + "。"
    assert any("挪到了别的地方" in f for f in gates.check(long_orig, middle, constraints=loose, may_move="first-sentence"))


# -- 评判清单和拍后批注（10/13 作者：9 项在 skill 里定，工作台只读）-------------------------------------

REVIEW = """review:
  - {id: retain, title: 留人, from: [opening]}
  - {id: density, title: 密度, from: [density]}
  - {id: scarcity, title: 稀缺, from: [scarcity]}
  - {id: tone, title: 口气, from: [style]}
  - {id: typo, title: 错字通顺和导语, from: [check-typo]}
post-shoot:
  {title: 拍后批注, prompt: "references/评判.md#评判", does: 只批注}
"""


def with_review(tmp_path: Path, extra: str = REVIEW) -> Path:
    root = make_skill(tmp_path, MANIFEST + extra)
    (root / "references" / "评判.md").write_text("# 视频框架\n\n## 评判：9 项\n\n每项 0–10 分。\n", encoding="utf-8")
    return root


def test_review_and_post_shoot_are_read_and_old_manifests_without_them_still_load(tmp_path: Path) -> None:
    m = write_module.load(with_review(tmp_path))
    assert [i.title for i in m.review] == ["留人", "密度", "稀缺", "口气", "错字通顺和导语"]
    assert "每项 0–10 分" in m.post_shoot_text()
    plain = write_module.load(make_skill(tmp_path / "old"))
    assert plain.review == () and plain.post_shoot is None


def test_review_items_follow_the_steps_that_are_switched_on(tmp_path: Path) -> None:
    m = write_module.load(with_review(tmp_path))
    steps = m.round_steps(["opening", "density", "style", "check-typo"], 1)
    assert [i.title for i in m.review_items(steps)] == ["留人", "密度", "口气"]  # 稀缺关了；错字是第二轮，第一轮不打


@pytest.mark.parametrize("bad, message", [
    ("review:\n  - {id: x, title: 留人, from: [nope]}\n", "不在 steps 里"),
    ("review:\n  - {id: a, title: 留人, from: [opening]}\n  - {id: b, title: 留人, from: [density]}\n", "重复"),
    ("review:\n  - {id: a, title: 留人}\n", "都要有 id、title、from"),
    ("post-shoot:\n  {title: x}\n", "没写 prompt"),
    ("post-shoot:\n  {title: x, prompt: 'references/评判.md#没有这一节'}\n", "规则找不到"),
])
def test_a_broken_review_or_post_shoot_is_refused_with_the_reason(tmp_path: Path, bad: str, message: str) -> None:
    root = with_review(tmp_path, bad)
    with pytest.raises(write_module.ModuleError, match=message):
        write_module.load(root)
