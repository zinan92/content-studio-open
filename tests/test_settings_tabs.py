"""设置分七页：通用 · 流程 · 视频动效 · Skills · 内容框架 · 助手读什么 · 版本。"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/content_studio/static"


def test_settings_page_has_seven_tabs_and_each_block_sits_in_one() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for tab in ("general", "flow", "motion", "skills", "frames", "team", "update"):
        assert f'data-set="{tab}"' in index and f'data-set-tab="{tab}"' in index, tab
    assert 'id="soulBody"' in index and 'id="skillsBody"' in index and 'id="v2Defaults"' in index and 'id="updateBody"' in index
    assert "设置与 Skills" not in index and "profile.yaml" not in index.split('id="v-settings"')[1].split("</section>")[0]
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "paintSettingsTabs" in app and "cs-set-tab" in app and "#settings/${SET.tab}" in app
    skills = (STATIC / "skills.js").read_text(encoding="utf-8")
    assert "soulBody" in skills  # 助手读的文件渲染到自己那一页
