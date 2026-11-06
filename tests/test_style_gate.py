"""样式档位的关卡（10/6 作者 看完《Refactoring UI》那 20 条：字号、圆角要成档，照着选）。

10/5 量出来的现状：29 种字号、23 种圆角、191 种内边距，是 8 天 135 次提交各自挑出来的。只修一遍还会长回来，
所以先上一道棘轮：现有的值算「上限」，新改动只能从档位里取，不能再加新值；把旧值往档位上收，这里的清单就跟着缩。

档位（目标，不是现状）：
  字号   12 / 13 / 14 / 16 / 20 / 26 / 34 px（正文不小于 13）
  圆角   6 / 10 / 14 px，胶囊 999px，圆 50%
  间距   4 / 8 / 12 / 16 / 24 / 32 px
  颜色   只从 :root 的变量里取
"""
from __future__ import annotations

from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "src/content_studio/static"
CSS = "\n".join(p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.css")))

SCALE_FONT = {"12px", "13px", "14px", "16px", "20px", "26px", "34px"}
# 现在还在用、还没收进档位的（棘轮：只许减，不许加）
LEGACY_FONT: set[str] = set()  # 10/8 全部收进档位
SCALE_RADIUS = {"6px", "10px", "14px", "999px", "50%", "0"}
LEGACY_RADIUS: set[str] = set()  # 10/8 全部收进档位
MAX_HEX_OUTSIDE_TOKENS = 87   # :root 变量块以外写死的色值（次数）
MAX_INLINE_STYLES = 29        # JS 里拼出来的 style="…"


def _font_sizes() -> set[str]:
    return set(re.findall(r"font-size:\s*([0-9.]+(?:px|em|rem|%))", CSS))


def _radii() -> set[str]:
    """每个角单独算：「0 6px 6px 0」这种只要每个角都在档位里就行。"""
    return {part for v in re.findall(r"border-radius:\s*([^;}]+)", CSS) for part in v.split()}


def test_font_sizes_come_from_the_scale_or_the_shrinking_legacy_list() -> None:
    extra = _font_sizes() - SCALE_FONT - LEGACY_FONT
    assert not extra, f"新字号 {sorted(extra)}：从档位里挑一个（12 / 13 / 14 / 16 / 20 / 26 / 34），别再加一档"
    gone = LEGACY_FONT - _font_sizes()
    assert not gone, f"这些旧字号已经没人用了，把它们从 LEGACY_FONT 删掉，关卡才会往前走：{sorted(gone)}"


def test_radii_come_from_the_scale_or_the_shrinking_legacy_list() -> None:
    extra = _radii() - SCALE_RADIUS - LEGACY_RADIUS
    assert not extra, f"新圆角 {sorted(extra)}：用 6 / 10 / 14 / 999px，别再加一档"
    gone = LEGACY_RADIUS - _radii()
    assert not gone, f"这些旧圆角已经没人用了，从 LEGACY_RADIUS 删掉：{sorted(gone)}"


def test_hard_coded_colors_and_inline_styles_do_not_grow() -> None:
    legacy_css = (STATIC / "styles.css").read_text(encoding="utf-8")
    body = legacy_css[legacy_css.index('[data-stage="in"]'):]  # :root 的变量块在它前面
    hexes = re.findall(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", body)
    assert len(hexes) <= MAX_HEX_OUTSIDE_TOKENS, f"样式表里又多了写死的色值（{len(hexes)} 处）：颜色从 :root 的变量里取"
    inline = sum(len(re.findall(r'style="', p.read_text(encoding="utf-8"))) for p in STATIC.glob("*.js"))
    assert inline <= MAX_INLINE_STYLES, f"JS 里拼的 style= 又多了（{inline} 处）：写成 class，样式进 styles.css"


def test_new_stylesheets_use_tokens_instead_of_literal_colors() -> None:
    for path in STATIC.glob("*.css"):
        if path.name == "styles.css":
            continue
        text = re.sub(r":root[^{}]*\{[^{}]*\}", "", path.read_text(encoding="utf-8"))
        assert not re.search(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", text), path.name
