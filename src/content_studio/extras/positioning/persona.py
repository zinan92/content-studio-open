"""个人形象：一个文件夹放定稿形象，配图时让角色上场，每张配图都存一份。

作者 10/7：「小黑的逻辑非常好……只是把小黑换成我的形象」「每次文章插图生成的形象都要保存下来」。
文件夹默认在 作者 的 Obsidian 里（profile 的 paths.persona 可改），里面的文件名是固定的：

  avatar.png     头像
  fullbody.png   全身像（画法和质感的正本）
  sheet.png      四视图：正面、左侧、背面、右侧
  reference.png  动作主参考：正面全身、纯色底
  watermark.png  水印：圆头像 + 账号名，透明底（watermark-light.png 是深色底上用的）
  spec.md        角色设定：长什么样、穿什么、最容易画走样的地方
  gallery/       每次配图存一份：<日期>-<文章目录>/01-xxx.png，index.jsonl 一行一张

spec.md 和 reference.png 都在，才算有角色；缺一个就退回原版小黑（客户装机时没有形象就是这样）。
10/7 起形象文件夹放在这个人自己的配图 skill 里（<slug>-ip-illustrations/persona，ip-studio 生成）：
上一级有 SKILL.md 时，配图直接调那个 skill（skill()），不再临时把小黑换角。
gallery 只加不删：重新配图会把文章里的上一轮图换掉，但这里留着。
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from ... import conf
from ...paths import config_dir

BASE = (("avatar.png", "头像"), ("fullbody.png", "全身像"), ("sheet.png", "四视图"), ("reference.png", "动作参考"), ("watermark.png", "水印 · 浅色底"), ("watermark-light.png", "水印 · 深色底"),
        ("banner/x-1500x500.png", "Banner · X"), ("banner/douyin-1125x633.png", "Banner · 抖音"),
        ("banner/xiaohongshu-1250x1000.png", "Banner · 小红书"))
SPEC = "spec.md"
GALLERY = "gallery"
INDEX = "index.jsonl"
STAGE = "persona-ref"  # 配图时把参考图复制进文章目录的这个子文件夹，Codex 只在自己的工作目录里读
IMAGE = re.compile(r"\.(png|jpe?g|webp)$", re.IGNORECASE)
# 页面上一格最宽约 300px，两倍屏 640 够清楚。原图 1–2 MB 一张、22 张近 30 MB，从外网打开要等十来秒（10/7 作者）
THUMB_WIDTH = 640


def root() -> Path:
    return conf.path("paths.persona")


def character() -> dict[str, str] | None:
    """有角色就返回 {name, spec}；spec.md 或 reference.png 缺一个都算没有。"""
    base = root()
    spec = base / SPEC
    if not spec.is_file() or not (base / "reference.png").is_file():
        return None
    text = spec.read_text(encoding="utf-8")
    m = re.search(r"角色名称?为\s*[「“]?([^\s。，「」“”]+)", text) or re.match(r"#\s*(\S+?)\s*角色", text)
    return {"name": m.group(1) if m else "固定角色", "spec": text}


def skill() -> str | None:
    """形象文件夹的上一级是一个配图 skill（有 SKILL.md）就返回它的 name；没有角色时不算。"""
    md = root().parent / "SKILL.md"
    if character() is None or not md.is_file():
        return None
    m = re.search(r"^name:\s*(\S+)\s*$", md.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def stage(workdir: Path) -> Path:
    """把 spec 和参考图复制到 workdir/persona-ref/，返回这个文件夹。"""
    dest = workdir / STAGE
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for name in (SPEC, *(n for n, _ in BASE)):
        src = root() / name
        if src.is_file():
            # Banner 在 banner/ 子文件夹里（10/7 加的），不先建好就 Errno 2，整个配图失败
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / name)
    return dest


def unstage(workdir: Path) -> None:
    shutil.rmtree(workdir / STAGE, ignore_errors=True)


def _title(article: Path) -> str:
    for line in article.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return article.parent.name


def archive(article: Path, folder: Path, placed: list[dict[str, Any]], *, now: datetime | None = None) -> Path | None:
    """这一轮配出来的图复制进 gallery/<日期>-<文章目录>/（同名加 -v2、-v3，不覆盖），每张在 index.jsonl 记一行。"""
    files = [p for p in placed if (folder / str(p.get("file") or "")).is_file()]
    if not files:
        return None
    now = now or datetime.now()
    gallery = root() / GALLERY
    stem = f"{now:%Y-%m-%d}-{article.parent.name}"
    dest = gallery / stem
    n = 1
    while dest.exists():
        n += 1
        dest = gallery / f"{stem}-v{n}"
    dest.mkdir(parents=True)
    title = _title(article)
    lines = []
    for p in files:
        name = Path(str(p["file"])).name
        shutil.copy2(folder / name, dest / name)
        lines.append(json.dumps({"at": now.isoformat(timespec="seconds"), "article": str(article), "title": title,
                                 "file": f"{dest.name}/{name}", "caption": str(p.get("caption") or "")}, ensure_ascii=False))
    with (gallery / INDEX).open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return dest


def gallery() -> list[dict[str, Any]]:
    """配图里的形象，新的在前；index 里记了但文件被人删了的不列。"""
    base = root() / GALLERY
    try:
        rows = (base / INDEX).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for row in rows:
        try:
            item = json.loads(row)
        except ValueError:
            continue
        if isinstance(item, dict) and (base / str(item.get("file") or "")).is_file():
            out.append(item)
    return out[::-1]


def state() -> dict[str, Any]:
    base = root()
    ch = character()
    return {
        "dir": str(base),
        "ready": ch is not None,
        "name": ch["name"] if ch else "",
        "skill": skill() or "",
        "spec": ch["spec"] if ch else "",
        "base": [{"file": n, "label": label, "v": _version(base / n)} for n, label in BASE if (base / n).is_file()],
        "gallery": [{**g, "file": f"{GALLERY}/{g['file']}", "v": _version(base / GALLERY / g["file"])} for g in gallery()],
    }


def file(relative: str) -> Path | None:
    """只给形象文件夹里的图片；../ 之类跳出去的、不是图片的、不存在的都返回 None。"""
    base = root().resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file() or not IMAGE.search(path.name):
        return None
    return path


def _version(path: Path) -> str:
    """图一换（同名重画）这个就变：页面拿它拼进地址，浏览器可以放心长期缓存。"""
    st = path.stat()
    return f"{st.st_mtime_ns:x}{st.st_size:x}"


def thumb(relative: str) -> Path | None:
    """页面上看的小图：最宽 THUMB_WIDTH 的 webp（透明底保留），按原图版本缓存在配置目录，不往形象文件夹里写。"""
    from PIL import Image

    src = file(relative)
    if src is None:
        return None
    key = hashlib.sha1(f"{src}|{_version(src)}|{THUMB_WIDTH}".encode()).hexdigest()[:24]
    out = config_dir() / "cache" / "persona-thumbs" / f"{key}.webp"
    if out.is_file():
        return out
    partial = out.with_name(out.name + ".part")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 4))
            im.convert("RGBA").save(partial, "WEBP", quality=80, method=4)
        partial.replace(out)
    except OSError:  # 打不开、写不了缓存：给原图，页面照样有图，只是慢
        partial.unlink(missing_ok=True)
        return src
    return out
