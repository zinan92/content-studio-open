"""对外简介：正本是 Obsidian 里的 `000_我/profile.md`，一个文件、两段：国内版和 X 版。

9/30 作者：先说「我不用在各个平台不一样……他就是我对外的一个 profile」，看了别人的 X 以后又说
「X 的和国内的社媒应该不太一样」。所以不是每个平台一份，也不是全部一份，而是两版：
国内版（抖音、视频号、小红书、公众号、B 站）是一句话讲清楚帮谁做什么；
X 版（X、YouTube）是名片的写法——身份、带数字的证据、关注我能看到什么、怎么找我，用短语不用整句。

- 文件里：开头是国内版（第一行名字，后面是简介）；`## X 版` 下面是 X 版（同样第一行名字）。
  `![[图]]` 这类嵌入行原样留在最后，工作台不动它们。
- 工作台里改 → 写回这个文件；Obsidian 里改 → 工作台下次读就是新的。保存时带上读到时的修改时间：
  文件在这期间被 Obsidian 改过，就不覆盖，让他先刷新。
- 每个平台只记「哪天改成了哪一版」：和它那一版现在的内容一样 = 已同步；不一样 = 要更新。
- X 版按 X 的上限写：名字 50、简介 160 字符。国内版不写死上限，只显示字数。
- 改到平台上是他自己做（9/30：「先不要上传，我自己手动上传」）。X 留着「改到 X 上」的按钮（x_profile.py），
  点两次才改；平时用「复制」+「我贴好了」。
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import quote

FILE = "000_我/profile.md"
X_NAME_MAX, X_BIO_MAX = 50, 160
X_HEADING = "## X 版"
VARIANTS = (("cn", "国内版"), ("x", "X 版"))
LIMITS = {"cn": {}, "x": {"name": X_NAME_MAX, "bio": X_BIO_MAX}}
# (key, 名字, 用哪一版, 编辑页, 去哪改)
PLATFORMS: tuple[tuple[str, str, str, str | None, str], ...] = (
    ("douyin", "抖音", "cn", None, "抖音 App：我 → 编辑资料"),
    ("channels", "视频号", "cn", None, "微信：视频号 → 自己的主页 → 资料"),
    ("xiaohongshu", "小红书", "cn", None, "小红书 App：我 → 编辑资料"),
    ("wechat_mp", "公众号", "cn", "https://mp.weixin.qq.com/", "后台 → 设置与开发 → 公众号设置 → 功能介绍（一年能改的次数有限）"),
    ("bilibili", "B 站", "cn", "https://account.bilibili.com/account/home", "个人中心 → 我的信息 → 我的签名"),
    ("x", "X", "x", "https://x.com/settings/profile", "x.com → 编辑个人资料"),
    ("youtube", "YouTube", "x", "https://studio.youtube.com/", "YouTube Studio → 自定义 → 基本信息"),
)
PUSHABLE = ("x",)


class ProfileError(RuntimeError):
    """说给人听的一句话。"""


def _is_embed(line: str) -> bool:
    return line.strip().startswith("![")


def _block(lines: list[str]) -> dict[str, str]:
    text = list(lines)
    while text and not text[0].strip():
        text.pop(0)
    name = re.sub(r"^#+\s*", "", text[0]).strip() if text else ""
    return {"name": name, "bio": "\n".join(text[1:]).strip()}


def _parse(raw: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    lines = raw.splitlines()
    embeds = [ln for ln in lines if _is_embed(ln)]
    text = [ln for ln in lines if not _is_embed(ln)]
    cut = next((i for i, ln in enumerate(text) if re.match(r"^##\s*X(\s|$)", ln.strip())), None)
    cn, x = (text, []) if cut is None else (text[:cut], text[cut + 1:])
    return {"cn": _block(cn), "x": _block(x)}, embeds


def read(vault: Path) -> dict[str, Any]:
    path = vault / FILE
    if not path.is_file():
        return {"exists": False, "path": str(path), "variants": {"cn": {"name": "", "bio": ""}, "x": {"name": "", "bio": ""}},
                "mtime": None, "obsidian": None, "embeds": 0}
    variants, embeds = _parse(path.read_text(encoding="utf-8"))
    return {"exists": True, "path": str(path), "variants": variants, "mtime": path.stat().st_mtime,
            "obsidian": f"obsidian://open?path={quote(str(path))}", "embeds": len(embeds)}


def write(vault: Path, variant: str, *, name: str, bio: str, mtime: float | None) -> dict[str, Any]:
    if variant not in LIMITS:
        raise ProfileError("没有这一版")
    name, bio = name.strip(), bio.strip()
    if not name:
        raise ProfileError("名字不能空")
    for field, value in (("name", name), ("bio", bio)):
        cap = LIMITS[variant].get(field)
        if cap and len(value) > cap:
            raise ProfileError(f"X 的{'名字' if field == 'name' else '简介'}最多 {cap} 个字，现在 {len(value)} 个")
    path = vault / FILE
    variants: dict[str, dict[str, str]] = {"cn": {"name": "", "bio": ""}, "x": {"name": "", "bio": ""}}
    embeds: list[str] = []
    if path.is_file():
        if mtime is not None and abs(path.stat().st_mtime - mtime) > 1e-3:
            raise ProfileError("这份简介刚在 Obsidian 里改过，先刷新再改，免得把那边的改动盖掉")
        variants, embeds = _parse(path.read_text(encoding="utf-8"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    variants[variant] = {"name": name, "bio": bio}
    out = [variants["cn"]["name"], "", variants["cn"]["bio"]]
    if variants["x"]["name"] or variants["x"]["bio"]:
        out += ["", X_HEADING, "", variants["x"]["name"], "", variants["x"]["bio"]]
    if embeds:
        out += ["", *embeds]
    text = "\n".join(out).rstrip("\n") + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".profile-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return read(vault)


def platforms(profile: dict[str, Any], applied: dict[str, Any], on: dict[str, bool], core: tuple[str, ...]) -> list[dict[str, Any]]:
    """每个开着的平台：synced 平台上就是它那一版 / stale 改过但那一版后来又变了 / never 还没改过。"""
    out = []
    for key, label, variant, edit_url, where in PLATFORMS:
        if not on.get(key):
            continue
        now = profile["variants"][variant]
        rec = applied.get(key) or {}
        if not rec:
            state = "never"
        elif rec.get("name") == now["name"] and rec.get("bio") == now["bio"]:
            state = "synced"
        else:
            state = "stale"
        out.append({"key": key, "label": label, "variant": variant, "edit_url": edit_url, "where": where, "core": key in core,
                    "can_push": key in PUSHABLE, "state": state, "applied_at": rec.get("at"), "empty": not (now["name"] or now["bio"])})
    return out
