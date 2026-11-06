"""可选配置：把「只在 作者 这台电脑上成立」的东西摘成 profile.yaml 里的项。

作者 9/28：工作台要装到客户（博主）的 Mac 上，但「不要动我现在在用的」。所以这里的规矩是：

- **不填 = 作者 现在的值。** 每一项的默认值就是原来写死在代码里的那个值，
  作者 的 profile.yaml 里没有这些项，他这台电脑的行为一个字节都不变。
- 给客户装机时，作者 在客户那份 profile.yaml 里填客户自己的值。
- 落地方式沿用已有的做法：profile 里填了的项在启动时写成环境变量（环境变量已经设了的不动，
  那是显式覆盖），各模块读环境变量，读不到用默认值。
- `apply()` 在包导入时就跑（见 __init__.py），这样各模块在导入时算出的常量也能拿到。

对照表（给人看的版本）在 作者 的 vault：009_product-os/内容工作台/配置单.md。
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

SKIP_ENV = "CONTENT_STUDIO_SKIP_PROFILE_ENV"  # 测试里设上，别让本机 profile.yaml 漏进测试

# profile.yaml 里的点分路径 → 环境变量 → 不填时的默认值（= 作者 现在的值）
ENV_MAP: dict[str, tuple[str, str]] = {
    "standards": ("CONTENT_STUDIO_QA_GUIDE", "~/.claude/skills/content-qa/SKILL.md"),
    "consult.folder": ("CONTENT_STUDIO_CONSULT_FOLDER", "010_咨询"),
    "consult.workdir": ("CONTENT_STUDIO_CONSULTS", "~/.config/content-studio/consults"),
    "paths.content_ops": ("CONTENT_OPS_PATH", "~/work/content-ops"),
    "paths.content_downloader": ("CONTENT_DOWNLOADER_PATH", "~/work/content-downloader"),
    "paths.xingqiu": ("CONTENT_STUDIO_XINGQIU", "~/work/xingqiu-shell"),
    "paths.publish_toolkit": ("CONTENT_STUDIO_PUBLISH_TOOLKIT", "~/content-toolkit/capabilities/publish"),
    "paths.secrets": ("CONTENT_STUDIO_SECRETS", "~/.config/content-studio/secrets.yaml"),
    "paths.youtube_token": ("CONTENT_STUDIO_YOUTUBE_TOKEN", "~/.config/park/youtube-token.json"),
    # 形象照：出封面时「好看版的他」（10/1 作者：视频那一帧是普通版，和这几张合起来出封面上的人）
    "paths.portraits": ("CONTENT_STUDIO_PORTRAITS", "~/notes/形象照"),
    # 个人形象：头像、全身像、四视图、动作参考、角色设定，和每次配图存下来的图（10/7，见 persona.py）。
    # 作者 的在 Obsidian 里他的配图 skill 下面
    "paths.persona": ("CONTENT_STUDIO_PERSONA", "~/notes/persona"),
    "skills.koubo": ("CONTENT_STUDIO_KOUBO_SKILL", "~/.claude/skills/park-video-v2"),  # 10/21：口播剪辑全收进 park-video-v2（ask-park-video 已归档）
    "skills.gzh_design": ("CONTENT_STUDIO_GZH_SKILL", "~/.claude/skills/gzh-design"),
    "skills.shots": ("CONTENT_STUDIO_SHOTS", "~/.agents/skills/video-shotcraft/references/shots"),
    # 出封面、配插图用的 Codex 模型（10/1 作者：固定用 gpt-6.1-sol；不跟着本机 ~/.codex/config.toml 的默认值变）
    "codex.model": ("CONTENT_STUDIO_CODEX_MODEL", "gpt-6.1-sol"),
    # 后台 AI 用哪个命令行：codex（默认，10/6 作者 定）或 claude。各模块的命令按 claude 写，选 codex 时由 llm.py 翻译
    "ai.backend": ("CONTENT_STUDIO_AI", "codex"),
    # 在哪找到我：GitHub（用户名或主页链接）和个人网站。定位页顶上那一行、X 那条线的素材都读这一份（10/6）
    # 写在前面：同一个环境变量，me.* 填了就用它；没填才看下面老的 x_line.*（10/4 那会儿写在那里）
    "me.github": ("CONTENT_STUDIO_X_GITHUB", ""),
    "me.site": ("CONTENT_STUDIO_X_SITE", ""),
    # X 那条线的素材：谁的 GitHub 公开仓库、哪个网站的原则 / 预测 / Good Product（10/4）
    # 10/6：X 短帖的素材来源不再默认是 作者 的仓库和网站——装到别人电脑上，空着就是空着，在 profile 里填自己的
    "x_line.github_user": ("CONTENT_STUDIO_X_GITHUB", ""),
    "x_line.site": ("CONTENT_STUDIO_X_SITE", ""),
    # X 运营 Agent 的角色文件（10/9）：空着用仓库里附带的通用版 examples/xops/X运营.md
    "xops.role": ("CONTENT_STUDIO_XOPS_ROLE", ""),
    # 「检查更新」拉哪个分支；客户装机时填 stable（作者 挑好的版本），作者自己是 main
    "update.branch": ("CONTENT_STUDIO_UPDATE_BRANCH", "main"),
    "update.remote": ("CONTENT_STUDIO_UPDATE_REMOTE", "origin"),
    # 后台服务：launchd 的名字和安全重启脚本
    "service.label": ("CONTENT_STUDIO_SERVICE_LABEL", "com.content-studio.app"),
    "service.restart": ("CONTENT_STUDIO_RESTART", "~/.local/bin/content-studio-restart"),
}

# 品牌：工作台左上角、给客户的纪要和报告。不填 = 内容工作台。
BRAND_DEFAULT: dict[str, str] = {
    "name": "内容工作台",
    "en": "CONTENT STUDIO",
    "slogan": "一个人的内容生产线",
    "promise": "不交报告，交结果。",
    "logo": "",  # 一个 SVG 文件的路径；不填用对勾
    # 两个虚拟同事叫什么（10/6：装到别人电脑上，名字跟着品牌走；角色文件另配）
    "editor": "Anna",
    "boss": "Wendy",
    # 10/9 变现流程板：Anna 管触达，Wendy 管收入；头衔也跟着品牌走，装到别人那里可以改
    "editor_role": "流量 CEO",
    # 10/12 作者：Wendy 是整个项目的负责人（背 KPI），Anna、Michael 先停用
    "boss_role": "负责人",
    # X 页常驻的那个人（10/9 晚 作者：「X 那个 agent 名字叫做 Michael 吧」）
    "xops": "Michael",
    "xops_role": "X 运营",
}


def _get(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _load() -> dict[str, Any]:
    from . import profile

    try:
        return profile.load()
    except Exception:  # noqa: BLE001 - profile 写坏了不该让工作台起不来；`content-studio check` 会报出来
        return {}


def apply(data: dict[str, Any] | None = None) -> list[str]:
    """profile 里填了的项写成环境变量。返回这次写了哪些（给 check / 日志用）。"""
    if data is None and os.environ.get(SKIP_ENV):
        return []
    data = _load() if data is None else data
    written = []
    for key, (env, _default) in ENV_MAP.items():
        value = _get(data, key)
        if value is None or not str(value).strip() or os.environ.get(env):
            continue
        os.environ[env] = str(value).strip()
        written.append(key)
    return written


def value(key: str) -> str:
    """这一项现在生效的值：环境变量 → 默认值。"""
    env, default = ENV_MAP[key]
    return os.environ.get(env) or default


def path(key: str) -> Path:
    return Path(value(key)).expanduser()


def brand(data: dict[str, Any] | None = None) -> dict[str, str]:
    if data is None:
        data = {} if os.environ.get(SKIP_ENV) else _load()
    cfg = data.get("brand") if isinstance(data.get("brand"), dict) else {}
    return {k: str(cfg.get(k) or "").strip() or v for k, v in BRAND_DEFAULT.items()}


_GITHUB_URL = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})(?:[/?#].*)?$", re.IGNORECASE)
_GITHUB_LOGIN = re.compile(r"^@?([A-Za-z0-9-]{1,39})$")
_SITE = re.compile(r"^(?:https?://)?[^\s/]+\.[^\s/]+(?:/\S*)?$", re.IGNORECASE)


def github_login(raw: str | None) -> str:
    """GitHub 用户名：填用户名、@用户名或主页链接都行；认不出返回空。"""
    text = (raw or "").strip().rstrip("/")
    m = _GITHUB_URL.match(text) or _GITHUB_LOGIN.match(text)
    return m.group(1) if m else ""


def site_url(raw: str | None) -> str:
    """个人网站：没写 https:// 的补上，去掉结尾的斜杠；不像网址返回空。"""
    text = (raw or "").strip().rstrip("/")
    if not text or not _SITE.match(text):
        return ""
    return text if re.match(r"^https?://", text, re.IGNORECASE) else f"https://{text}"


def me_links() -> dict[str, str]:
    """在哪找到我：现在生效的 GitHub 和网站（空 = 没填）。"""
    login = github_login(value("me.github"))
    return {"github_user": login, "github": f"https://github.com/{login}" if login else "", "site": site_url(value("me.site"))}
