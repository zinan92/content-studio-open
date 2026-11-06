"""conf.py：作者 专属的东西摘成可选配置。最要紧的一条：不填 = 作者 现在的值，一个字节都不变。"""
from datetime import date
import os
from pathlib import Path

import pytest

from content_studio import conf
from content_studio.extras.consults import consult

# 摘出来之前写死在代码里的值。改默认值 = 改 作者 正在用的行为，得先问他。
DEFAULT_VALUES = {
    "ai.backend": "codex",
    "standards": "~/.claude/skills/content-qa/SKILL.md",
    "consult.folder": "010_咨询",
    "consult.workdir": "~/.config/content-studio/consults",
    "paths.content_ops": "~/work/content-ops",
    "paths.content_downloader": "~/work/content-downloader",
    "paths.xingqiu": "~/work/xingqiu-shell",
    "paths.publish_toolkit": "~/content-toolkit/capabilities/publish",
    "paths.secrets": "~/.config/content-studio/secrets.yaml",
    "paths.youtube_token": "~/.config/park/youtube-token.json",
    "paths.portraits": "~/notes/形象照",
    "paths.persona": "~/notes/persona",
    "skills.koubo": "~/.claude/skills/park-video-v2",
    "skills.gzh_design": "~/.claude/skills/gzh-design",
    "skills.shots": "~/.agents/skills/video-shotcraft/references/shots",
    "codex.model": "gpt-6.1-sol",
    "me.github": "",
    "me.site": "",
    "x_line.github_user": "",
    "x_line.site": "",
    "xops.role": "",
    "update.branch": "main",
    "update.remote": "origin",
    "service.label": "com.content-studio.app",
    "service.restart": "~/.local/bin/content-studio-restart",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for env, _ in conf.ENV_MAP.values():
        monkeypatch.delenv(env, raising=False)
    return monkeypatch


def test_nothing_configured_means_parks_current_values(clean_env) -> None:
    assert {k: default for k, (_, default) in conf.ENV_MAP.items()} == DEFAULT_VALUES
    for key, old in DEFAULT_VALUES.items():
        assert conf.value(key) == old
    assert conf.apply({}) == []
    assert conf.brand({}) == {"name": "内容工作台", "en": "CONTENT STUDIO", "slogan": "一个人的内容生产线",
                              "promise": "不交报告，交结果。", "logo": "", "editor": "Anna", "boss": "Wendy",
                              "editor_role": "流量 CEO", "boss_role": "负责人",
                              "xops": "Michael", "xops_role": "X 运营"}


def test_module_constants_still_point_where_they_did() -> None:
    from content_studio import gzh_layout, platform_stats, publisher

    home = Path.home()
    assert publisher.PUBLISH_ROOT == home / "content-toolkit/capabilities/publish"
    assert publisher.XINGQIU == home / "work/xingqiu-shell"
    assert platform_stats.BILI_COOKIES == home / "content-toolkit/capabilities/publish/cookies/bilibili_creator.json"
    assert platform_stats.CONTENT_OPS == home / "work/content-ops"
    assert gzh_layout.SKILL_DIR == home / ".claude/skills/gzh-design"
    assert consult.FOLDER == "010_咨询"


def test_a_customer_profile_overrides_but_explicit_env_wins(clean_env) -> None:
    clean_env.setenv("CONTENT_OPS_PATH", "/explicit/ops")
    written = conf.apply({"standards": "~/客户/标准/SKILL.md", "paths": {"content_ops": "/客户/ops", "xingqiu": "  "},
                          "consult": {"folder": "咨询"}})
    assert set(written) == {"standards", "consult.folder"}
    assert conf.value("standards") == "~/客户/标准/SKILL.md"
    assert conf.value("consult.folder") == "咨询"
    assert conf.value("paths.content_ops") == "/explicit/ops"  # 已经显式设了的环境变量不动
    assert conf.value("paths.xingqiu") == DEFAULT_VALUES["paths.xingqiu"]  # 空白 = 没填
    for env in ("CONTENT_STUDIO_QA_GUIDE", "CONTENT_STUDIO_CONSULT_FOLDER"):
        os.environ.pop(env, None)


def test_brand_goes_into_client_documents(tmp_path: Path) -> None:
    logo = tmp_path / "logo.svg"
    logo.write_text('<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>', encoding="utf-8")
    b = conf.brand({"brand": {"name": "小王工作室", "slogan": "做好内容", "logo": str(logo), "en": ""}})
    client = {"call": "小李", "title": "t", "body": "## 下一步\n- 发报告"}
    page = consult.render_client(client, day=date(2026, 9, 28), brand=b)
    assert "小王工作室" in page and "做好内容" in page and "内容工作台" not in page and "<circle" in page
    assert "不交报告，交结果。" in page  # 没填的项沿用默认
    default = consult.render_client(client, day=date(2026, 9, 28))
    assert "内容工作台" in default and "一个人的内容生产线" in default and "CONTENT STUDIO" in default
