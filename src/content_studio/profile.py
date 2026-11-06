"""profile.yaml：一个人用这个工作台需要告诉它的所有事，集中在一个文件里。

模板在仓库根目录 profile.example.yaml，逐项标了 [必填] / [可选]。真实的 profile.yaml
在 .gitignore 里，永远不进仓库。

这是把「长在一台机器上的工具」变成「别人也能装的产品」的第一层：先有一个标准的
地方放配置，再一处一处把写死的路径和名字换成从这里读。所以这个模块只负责三件事——
找到文件、读出来、逐项说清楚哪些填了哪些没填——不负责改任何业务逻辑。

密钥不在这里。这里只记「密钥文件在哪」。
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from . import writing_rules

from .paths import config_dir
import re
from typing import Any, Callable

PROFILE_ENV = "CONTENT_STUDIO_PROFILE"
# 找文件的顺序：环境变量 → 仓库根目录 → 用户配置目录
SEARCH_PATHS = (
    Path(__file__).resolve().parents[2] / "profile.yaml",
    config_dir() / "profile.yaml",
)
EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "profile.example.yaml"

PLATFORM_KEYS = ("channels", "xiaohongshu", "wechat_mp", "miniprogram", "x", "bilibili", "youtube", "xiaoyuzhou")
DOUYIN_USER = re.compile(r"douyin\.com/user/[A-Za-z0-9_-]+")
AI_BACKENDS = ("codex", "claude", "claude-cli")


@dataclass
class Check:
    key: str            # 点分路径，如 vault.folders.my_writing
    label: str          # 给人看的名字
    required: bool
    ok: bool
    hint: str = ""      # 没通过时告诉用户该做什么


def find_profile(explicit: Path | None = None) -> Path | None:
    """第一个存在的就是它；都不存在返回 None（不是错误，是「还没配」）。"""
    candidates = [explicit] if explicit else []
    if os.environ.get(PROFILE_ENV):
        candidates.append(Path(os.environ[PROFILE_ENV]).expanduser())
    candidates.extend(SEARCH_PATHS)
    return next((p for p in candidates if p and p.is_file()), None)


def load(path: Path | None = None) -> dict[str, Any]:
    """读 profile.yaml。没有文件返回空 dict——上层用 check() 判断缺什么，不在这里抛。"""
    target = find_profile(path)
    if target is None:
        return {}
    import yaml

    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{target} 顶层得是一个映射（key: value），不是列表或字符串")
    data["_path"] = str(target)
    return data


def setup_path() -> Path:
    """工作台自己写 profile 时写到哪：已经有的那份；没有就是用户配置目录里的（仓库根目录那份是开发机才有的）。"""
    return find_profile() or (config_dir() / "profile.yaml")


def save(changes: dict[str, Any], path: Path | None = None) -> Path:
    """把几项合进 profile.yaml（没有就新建）。只动给的键，别的原样保留；注释会丢，所以只在工作台「开始用」那几步用。"""
    import yaml

    target = (path or setup_path()).expanduser()
    data: dict[str, Any] = {}
    if target.is_file():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    def merge(into: dict[str, Any], new: dict[str, Any]) -> None:
        for key, value in new.items():
            if isinstance(value, dict) and isinstance(into.get(key), dict):
                merge(into[key], value)
            else:
                into[key] = value

    merge(data, changes)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def _get(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _filled(value: Any) -> bool:
    return bool(str(value).strip()) if value is not None else False


def check(data: dict[str, Any] | None = None) -> list[Check]:
    """逐项核对，返回一张清单。必填项没通过 → 工作台起不来或什么都做不了；可选项没填 → 少一项能力。"""
    data = load() if data is None else data
    out: list[Check] = []

    def item(key: str, label: str, required: bool, test: Callable[[Any], bool], hint: str) -> None:
        value = _get(data, key)
        out.append(Check(key, label, required, bool(test(value)), hint))

    def folder_exists(root_key: str) -> Callable[[Any], bool]:
        def _test(value: Any) -> bool:
            root = _get(data, root_key)
            if not _filled(value) or not _filled(root):
                return False
            return (Path(str(root)).expanduser() / str(value)).is_dir()
        return _test

    item("me.name", "你的名字", True, _filled, "提示词里「作者是 ___」用它")
    item("me.douyin", "你的抖音主页链接", True,
         lambda v: _filled(v) and bool(DOUYIN_USER.search(str(v))),
         "形如 https://www.douyin.com/user/MS4wLjAB…；数据从这个号自动同步")
    item("me.platforms", "其他平台账号", False,
         lambda v: isinstance(v, dict) and any(_filled(v.get(k)) for k in PLATFORM_KEYS),
         "填了的平台会在「发布」页出现一张卡")
    item("ai.backend", "后台模型", True,
         lambda v: _filled(v) and str(v).strip() in AI_BACKENDS,
         "使用本机 Codex 或 Claude Code；backend 填 codex 或 claude，claude-cli 仅兼容旧配置。配置有效不代表已经登录或调用成功。")
    item("benchmarks", "对标账号", False,
         lambda v: isinstance(v, list) and any(_filled(x) for x in v),
         "一行一个主页链接；同步后先看新作品，由你选择是否下载和拆解")
    item("vault.path", "Obsidian 库路径", True,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_dir(),
         "库的根目录，得是一个存在的文件夹")
    item("vault.folders.my_writing", "「我写的东西」文件夹", True, folder_exists("vault.path"),
         "相对库根目录；这一栏不看时间，写过没拍的，选题 →「我的选题」里「从我的笔记里选」就能找到")
    item("vault.folders.clippings", "剪藏文件夹", False, folder_exists("vault.path"), "网页剪藏放哪")
    item("vault.folders.saved", "收藏文件夹", False, folder_exists("vault.path"), "收藏的别人的内容放哪")
    item("vault.dailies", "每日日报", False,
         lambda v: isinstance(v, list) and any(isinstance(d, dict) and _filled(d.get("folder")) for d in v),
         "每天早上要读的日报，每份一个文件夹")
    item("video_projects_root", "口播视频项目目录", False,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_dir(),
         "剪辑进度从这里读；没有就不显示剪辑进度")
    item("anna.role", "Anna 的角色文件", False,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_file(),
         "不填就用仓库自带的通用版主编；填你自己的 Markdown 才是你的 Anna")
    item("wendy.role", "Wendy 的角色文件", False,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_file(),
         "「今天」页最上面盯你执行的那个人；不填就用仓库自带的通用版")
    item("anna.workflows", "提纲框架文件夹", False,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_dir() and (
             (Path(str(v)).expanduser() / "一勾式骨架.md").is_file() or writing_rules.skill_dir() is not None),
         "里面放系列框架；写作框架装了 park-writing 就用它，没装要有 一勾式骨架.md；不填用仓库自带的通用版")
    item("secrets_file", "密钥文件", False,
         lambda v: _filled(v) and Path(str(v)).expanduser().is_file(),
         "公众号、X 的密钥放这里，权限 600；不填这些平台就是手动发")
    return out


def summary(checks: list[Check]) -> dict[str, Any]:
    missing_required = [c for c in checks if c.required and not c.ok]
    missing_optional = [c for c in checks if not c.required and not c.ok]
    return {
        "ok": not missing_required,
        "missing_required": [{"key": c.key, "label": c.label, "hint": c.hint} for c in missing_required],
        "missing_optional": [{"key": c.key, "label": c.label, "hint": c.hint} for c in missing_optional],
        "path": None,
    }


def render_checklist(checks: list[Check], path: Path | None) -> str:
    """终端里的那张清单。"""
    lines = []
    if path is None:
        lines.append("还没有 profile.yaml。")
        lines.append(f"  复制模板：cp {EXAMPLE_PATH.name} profile.yaml   然后按里面的 [必填] / [可选] 填。")
        lines.append("")
    else:
        lines.append(f"读的是：{path}")
        lines.append("")
    req = [c for c in checks if c.required]
    opt = [c for c in checks if not c.required]
    lines.append("必填")
    for c in req:
        lines.append(f"  {'✅' if c.ok else '❌'} {c.label:<14} {c.key}" + ("" if c.ok else f"\n       → {c.hint}"))
    lines.append("")
    lines.append("可选")
    for c in opt:
        lines.append(f"  {'✅' if c.ok else '○ '} {c.label:<14} {c.key}" + ("" if c.ok else f"\n       → {c.hint}"))
    lines.append("")
    bad = [c for c in req if not c.ok]
    lines.append("✅ 必填都齐了，可以 python3 -m content_studio serve" if not bad else f"❌ 还有 {len(bad)} 项必填没过，起来了也用不了")
    return "\n".join(lines)
