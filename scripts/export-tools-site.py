#!/usr/bin/env python3
"""把「单点功能」页导成一个纯静态文件夹，放到 park-ai-intel 站点的 public/tools/（10/10 作者：部署到那个站上，别人也能看）。

用法：python3 scripts/export-tools-site.py /绝对路径/public/tools [--api https://tools-api.example.com]

不带 --api：只放样例，「用我的内容试」指向一对一咨询。
带 --api：页面里输入邀请码就能用自己的内容真跑（接口在你 Mac 上，见 extras/tools/public.py）。

公开站没有后端，也不替陌生人跑你的 Codex：只放真跑出来的样例，「用我的内容试」改成指向一对一咨询。
文件布局和工作台里的网址一模一样（/tools/page.css、/tools/examples/…），所以 page.js 两边是同一份：
  index.html  styles.css  page.css  page.js  catalog.json  usecases.json  vendor/{marked,purify}.min.js  examples/
  styles/index.html（风格画廊）  styles/<id>.webp  styles.json  gallery.css  gallery.js
  videos.json  videos/<id>.mp4  videos/<id>.webp（视频样片；本机没有成片时 videos.json 写成空的，页面不显示这一节）
画廊只放他在打磨台点了「通过」、有样图的风格（10/11）；样图缩到 720 宽，提示词不公开。
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_studio.extras.tools import gallery, tools, videos  # noqa: E402

PKG = ROOT / "src/content_studio/extras/tools"
STATIC = ROOT / "src/content_studio/static"
SITE = "https://example.com/tools/"

# (工作台页面里的写法, 公开站里的写法)：每一条都必须命中，改了页面忘了这里就直接报错
SWAPS = (
    ('<link rel="icon" href="/static/brand/app-icon.svg">', '<link rel="icon" href="/favicon.svg">'),
    ('<link rel="stylesheet" href="/static/styles.css">', '<link rel="stylesheet" href="/tools/styles.css">'),
    ('<script src="/static/vendor/marked.min.js"></script>', '<script src="/tools/vendor/marked.min.js"></script>'),
    ('<script src="/static/vendor/purify.min.js"></script>', '<script src="/tools/vendor/purify.min.js"></script>'),
    ('<script src="/tools/page.js"></script>', '<script>window.CS_STATIC = true;</script>\n<script src="/tools/page.js"></script>'),
    ('<title>单点功能</title>', '<title>单点功能 · 先看结果 </title>\n'
     '<meta name="description" content="10 个一进一出的 AI 功能，每一个都附一份真跑出来的结果：文章点评、选题打分、标题、爆款拆解、封面、配图、小红书图文……">\n'
     f'<meta property="og:title" content="单点功能 · 先看结果">\n<meta property="og:url" content="{SITE}">\n'
     '<meta property="og:image" content="https://example.com/tools/examples/cover-1-01.webp">'),
    ('<a class="sf-brand" href="/" title="回工作台">', '<a class="sf-brand" href="/" title="回首页">'),
    ('<p class="sf-lede">先看它真做出来的样子，再用你自己的内容试。下面每一份都是真跑出来的结果，没有修过。</p>',
     '<p class="sf-lede">先看它真做出来的样子。下面每一份结果都是 Codex 真跑出来的，没有修过。</p>'),
    ('<p>全部跑在这台 Mac 上的 Codex · <span id="model">gpt-6.1-sol · medium</span> · 一次跑一个</p>',
     '<p>文字和图片样例由 Codex（<span id="model">gpt-6.1-sol · medium</span>）真实生成，未做修改。</p>'),
)

GALLERY_SWAPS = (
    ('<link rel="icon" href="/static/brand/app-icon.svg">', '<link rel="icon" href="/favicon.svg">'),
    ('<link rel="stylesheet" href="/static/styles.css">', '<link rel="stylesheet" href="/tools/styles.css">'),
    ('<script src="/tools/gallery.js"></script>', '<script>window.CS_STATIC = true;</script>\n<script src="/tools/gallery.js"></script>'),
    ('<title>风格画廊</title>', '<title>风格画廊 · 先挑画风 </title>\n'
     '<meta name="description" content="几百种画风，每种都用同一个主题真画了一张。挑一个，填一句主题，就画你要的。">\n'
     f'<meta property="og:title" content="风格画廊 · 先挑画风">\n<meta property="og:url" content="{SITE}styles">'),
)
SAMPLE_WIDTH = 720


def export_gallery(out: Path) -> int:
    from PIL import Image

    html = (PKG / "gallery.html").read_text(encoding="utf-8")
    for old, new in GALLERY_SWAPS:
        if old not in html:
            raise SystemExit(f"画廊页面里找不到这一段，导出规则要跟着改：{old[:60]}")
        html = html.replace(old, new, 1)
    if "/static/" in html or "/api/" in html:
        raise SystemExit("导出的画廊还指着工作台的 /static/ 或 /api/")
    data = gallery.catalog(approved_only=True)
    for row in data["styles"]:
        row["prompt"] = ""
    shutil.rmtree(out / "styles", ignore_errors=True)
    (out / "styles").mkdir(parents=True)
    for row in data["styles"]:
        with Image.open(gallery.sample_path(row["id"])) as im:
            if im.width > SAMPLE_WIDTH:
                im = im.resize((SAMPLE_WIDTH, round(im.height * SAMPLE_WIDTH / im.width)), Image.LANCZOS)
            im.save(out / "styles" / f"{row['id']}.webp", "WEBP", quality=80, method=6)
    (out / "styles" / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(PKG / "gallery.css", out / "gallery.css")
    shutil.copy(PKG / "gallery.js", out / "gallery.js")
    (out / "styles.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(data["styles"])


def export_videos(out: Path) -> int:
    """视频样片：成片在本机 tool-videos/。一个都没有就导出空清单（页面不显示这一节）；只缺几个就报错，别半套上线。"""
    shutil.rmtree(out / "videos", ignore_errors=True)
    lost = videos.missing()
    if len(lost) == len(videos.files()):
        (out / "videos.json").write_text(json.dumps({"groups": []}) + "\n", encoding="utf-8")
        return 0
    if lost:
        raise SystemExit(f"视频样片缺文件（{videos.videos_dir()}）：{'、'.join(lost)}")
    (out / "videos").mkdir(parents=True)
    for name in videos.files():
        shutil.copy(videos.videos_dir() / name, out / "videos" / name)
    shutil.copy(PKG / "videos.json", out / "videos.json")
    return sum(len(g["items"]) for g in videos.manifest()["groups"])


def main(out: Path, api: str = "") -> None:
    if not out.is_absolute():
        raise SystemExit("输出目录要写绝对路径")
    html = (PKG / "page.html").read_text(encoding="utf-8")
    if api:
        if not (api.startswith("https://") or api.startswith("http://127.0.0.1")):
            raise SystemExit("--api 要写 https:// 开头的完整地址（本机测试可以写 http://127.0.0.1:端口）")
        html = html.replace("<script src=\"/tools/page.js\"></script>", f"<script>window.CS_API = {json.dumps(api.rstrip('/'))};</script>\n<script src=\"/tools/page.js\"></script>", 1)
    for old, new in SWAPS:
        if old not in html:
            raise SystemExit(f"页面里找不到这一段，导出规则要跟着改：{old[:60]}")
        html = html.replace(old, new, 1)
    if "/static/" in html or "/api/" in html:
        raise SystemExit("导出的页面还指着工作台的 /static/ 或 /api/")
    if not (PKG / "examples/manifest.json").is_file():
        raise SystemExit("还没有样例：先跑 scripts/tools-examples.py")
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "examples", ignore_errors=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(PKG / "page.css", out / "page.css")
    shutil.copy(PKG / "page.js", out / "page.js")
    shutil.copy(PKG / "usecases.json", out / "usecases.json")
    shutil.copy(STATIC / "styles.css", out / "styles.css")
    (out / "vendor").mkdir(exist_ok=True)
    for name in ("marked.min.js", "purify.min.js"):
        shutil.copy(STATIC / "vendor" / name, out / "vendor" / name)
    shutil.copytree(PKG / "examples", out / "examples")
    (out / "catalog.json").write_text(
        json.dumps({"tools": tools.catalog(), "styles": tools.STYLES}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = export_gallery(out)
    print(f"风格画廊：{n} 种（只放通过的）")
    print(f"视频样片：{export_videos(out)} 条")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"导出到 {out}：{sum(1 for p in out.rglob('*') if p.is_file())} 个文件，{size / 1e6:.1f} MB")


if __name__ == "__main__":
    args = sys.argv[1:]
    api = ""
    if "--api" in args:
        i = args.index("--api")
        api = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 1:
        raise SystemExit(__doc__)
    main(Path(args[0]), api)
