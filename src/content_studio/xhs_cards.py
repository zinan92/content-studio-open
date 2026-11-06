"""小红书图文：研习室那篇文章一字不改，排成 3:4 的封面 + 正文页。

9/24 作者 看了第一版（改写成 8 张要点卡）：「不够详细，尽量不要缩减……把内容原封不动地搬到
图文上就好了，字甚至都不用改。就把格式做好了。」第二版就是这里：
- 封面：文章标题原样，按逗号断行（「下半场」这种词不劈开）；
- 正文：一段一段往页里放，放不下就在句号处切开，句子不跨页；单独成段的短句加粗当节奏点；
- 排完把每页的字抽回来和原文比，必须一字不差；小红书一篇最多 18 张，超了就说清楚。
和抖音封面一个样式：米白底、左上橙色斜角。文章改过（哈希变了）旧图作废。
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any

FOLDER = "xhs"
META = "meta.json"
HANDLE = "我的账号"
MAX_IMAGES = 18
ORANGE = "#ef3711"


class XhsError(RuntimeError):
    """说给人听的一句话。"""


def digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def parse(markdown: str) -> tuple[str, list[dict[str, str]]]:
    """标题 + 段落块（p / lead / h / q / li）。块里的字就是原文，只多一个排版类型。"""
    match = re.search(r"^#\s+(.+)$", markdown, re.M)
    if not match:
        raise XhsError("文章第一行要是「# 标题」")
    title = match.group(1).strip()
    body = markdown[match.end():]
    blocks: list[dict[str, str]] = []
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p or re.fullmatch(r"[-*_]{3,}", p):
            continue
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", p)
        if image:
            # 配图：整张放进卡片，放不下就去下一页（不参与「一字不改」的核对）
            blocks.append({"kind": "img", "text": "", "src": image.group(2), "alt": image.group(1)})
        elif p.startswith("#"):
            blocks.append({"kind": "h", "text": re.sub(r"^#+\s*", "", p)})
        elif p.startswith(">"):
            blocks.append({"kind": "q", "text": re.sub(r"^>\s?", "", p, flags=re.M)})
        elif re.match(r"^([-*+]|\d+[.)、])\s", p):
            blocks.append({"kind": "li", "text": p})
        else:
            plain = re.sub(r"\*\*", "", p)
            blocks.append({"kind": "lead" if len(plain) <= 22 and "\n" not in p else "p", "text": p})
    if not blocks:
        raise XhsError("文章只有标题，没有正文")
    return title, blocks


def title_lines(title: str, width: int = 8) -> list[str]:
    """按逗号断行；一段太长优先在「场了的是」这类字后面断，都没有才硬切。字不变。"""
    out: list[str] = []
    for seg in (x for x in re.split(r"(?<=[，,：:！!？?])", title) if x):
        while len(seg) > width + 1:
            ends = [i + 1 for i, ch in enumerate(seg[:-2]) if ch in "场了的是就才和与" and 3 <= i + 1 <= width + 1]
            mid = min(len(seg) // 2, width)
            cut = min(ends, key=lambda i: abs(i - mid)) if ends else mid
            out.append(seg[:cut])
            seg = seg[cut:]
        out.append(seg)
    return out


CSS = f"""
*{{box-sizing:border-box;margin:0}}
body{{width:1080px;height:1440px;overflow:hidden;background:linear-gradient(160deg,#fffdf7,#f7f1e3);font-family:'Hiragino Sans GB','PingFang SC',sans-serif;color:#1c1b19;position:relative}}
.corner{{position:absolute;left:0;top:0;width:150px;height:120px;background:{ORANGE};clip-path:polygon(0 0,100% 0,0 100%)}}
.top{{position:absolute;left:84px;right:84px;top:62px;display:flex;justify-content:flex-end;font-size:26px;color:#9a9486;letter-spacing:1px}}
.content{{position:absolute;left:76px;right:76px;top:140px;bottom:100px;overflow:hidden;font-size:36px;line-height:1.72;color:#2a2824}}
.content p{{margin:0 0 22px;text-align:justify}}
.content p.lead{{font-weight:900;color:#141414;font-size:38px}}
.content p.h{{font-weight:900;font-size:52px;color:#141414;border-left:10px solid {ORANGE};padding-left:22px}}
.content img.fig{{display:block;width:100%;border-radius:12px;margin:6px 0 22px;border:1px solid #eee}}
.content p.q{{background:#fff;border:2px solid #e6dfcf;border-radius:14px;padding:22px 26px;font-weight:700}}
.em{{font-weight:900;color:#141414;background:linear-gradient(transparent 62%,rgba(239,55,17,.28) 62%)}}
.foot{{position:absolute;left:84px;right:84px;bottom:48px;display:flex;justify-content:space-between;font-size:26px;color:#9a9486}}
"""

def page_html(handle: str = HANDLE) -> str:
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="corner"></div><div class="top"><span id="no"></span></div>
<div class="content" id="c"></div><div class="foot"><span>{html.escape(handle)}</span><span id="more"></span></div></body></html>"""


PAGE = page_html()


def cover_html(title: str, pages: int, handle: str = HANDLE) -> str:
    lines = "<br>".join(html.escape(line) for line in title_lines(title))
    return f"""<html><head><meta charset="utf-8"><style>{CSS}
.c-corner{{position:absolute;left:0;top:0;width:260px;height:210px;background:{ORANGE};clip-path:polygon(0 0,100% 0,0 100%)}}
.c-tail{{position:absolute;right:0;bottom:0;width:180px;height:190px;background:{ORANGE};clip-path:polygon(100% 0,100% 100%,0 100%)}}
.t{{position:absolute;left:110px;right:60px;top:300px;font-size:100px;font-weight:900;line-height:1.28;letter-spacing:-2px;transform:skewX(-6deg)}}
.u{{height:12px;width:760px;background:{ORANGE};border-radius:8px;margin-top:26px;transform:rotate(-1deg)}}
</style></head><body><div class="c-corner"></div><div class="t">{lines}<div class="u"></div></div><div class="c-tail"></div>
<div class="foot" style="right:230px"><span>{html.escape(handle)}</span><span>全文 {pages} 页 →</span></div></body></html>"""


# 在浏览器里排：一段一段往页里放，放不下就在句号处切开，剩下的去下一页
LAYOUT_JS = r"""
(blocks) => {
  const c = document.getElementById('c');
  const pages = [];
  const fits = () => c.scrollHeight <= c.clientHeight + 1;
  const esc = (s) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\*\*(.+?)\*\*/g, '<b class="em">$1</b>').replace(/\n/g, '<br>');
  const make = (b, t) => { const p = document.createElement('p'); p.className = b.kind; p.innerHTML = esc(t); return p; };
  const flush = () => { pages.push(c.innerHTML); c.innerHTML = ''; };
  for (const b of blocks) {
    if (b.kind === 'img') {
      const img = document.createElement('img'); img.src = b.data; img.className = 'fig'; img.alt = b.alt || '';
      c.appendChild(img);
      if (!fits() && c.children.length > 1) { c.removeChild(img); flush(); c.appendChild(img); }
      continue;
    }
    let rest = b.text;
    while (rest) {
      const el = make(b, rest); c.appendChild(el);
      if (fits()) { rest = ''; break; }
      c.removeChild(el);
      const parts = rest.match(/[^。！？；]*[。！？；”」]*|.+$/g).filter(Boolean);
      let lo = 0, hi = parts.length - 1, best = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1; const probe = make(b, parts.slice(0, mid + 1).join('')); c.appendChild(probe);
        const ok = fits(); c.removeChild(probe);
        if (ok) { best = mid; lo = mid + 1; } else hi = mid - 1;
      }
      if (best < 0) {
        if (!c.children.length) { c.appendChild(make(b, rest)); rest = ''; }  // 一句话比一页还长：只能整句放
        flush(); continue;
      }
      c.appendChild(make(b, parts.slice(0, best + 1).join('')));
      rest = parts.slice(best + 1).join('');
      flush();
    }
  }
  if (c.innerHTML) flush();
  return pages;
}
"""


def _norm(text: str) -> str:
    return re.sub(r"\s", "", text)


def page_text(inner: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", inner))


# 小红书一篇最多 18 张：排不下就把正文字号一档一档缩小再排（最小到原来的 76%，正文约 27px）
SCALES = (1.0, 0.94, 0.88, 0.82, 0.76)


def scale_css(scale: float) -> str:
    if scale >= 1:
        return ""
    return (f".content{{font-size:{36 * scale:.1f}px}}.content p.lead{{font-size:{38 * scale:.1f}px}}"
            f".content p.h{{font-size:{52 * scale:.1f}px}}")


async def _render(title: str, blocks: list[dict[str, str]], out: Path, handle: str = HANDLE) -> tuple[list[str], float]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1080, "height": 1440})
            for scale in SCALES:
                await page.set_content(page_html(handle))
                if scale_css(scale):
                    await page.add_style_tag(content=scale_css(scale))
                pages = await page.evaluate(LAYOUT_JS, blocks)
                if len(pages) + 1 <= MAX_IMAGES:
                    break
            total = len(pages) + 1
            await page.set_content(cover_html(title, len(pages), handle))
            await page.wait_for_timeout(80)
            await page.screenshot(path=str(out / "01.png"))
            for i, inner in enumerate(pages, 2):
                await page.set_content(page_html(handle))
                if scale_css(scale):
                    await page.add_style_tag(content=scale_css(scale))
                await page.evaluate("([h, no, more]) => { document.getElementById('c').innerHTML = h; document.getElementById('no').textContent = no; document.getElementById('more').textContent = more; }",
                                    [inner, f"{i} / {total}", "" if i == total else "接下页 →"])
                await page.screenshot(path=str(out / f"{i:02d}.png"))
        finally:
            await browser.close()
    return pages, scale


def make_cards(article: Path, *, now: datetime | None = None, handle: str = HANDLE) -> dict[str, Any]:
    markdown = article.read_text(encoding="utf-8")
    title, blocks = parse(markdown)
    for b in blocks:
        if b["kind"] == "img":
            path = (article.parent / b["src"]).resolve()
            if not path.is_file():
                raise XhsError(f"文章里的图找不到：{b['src']}")
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            b["data"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    out = article.parent / FOLDER
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    try:
        pages, scale = asyncio.run(_render(title, blocks, out, handle=handle))
    except ImportError:
        raise XhsError("这台机器上没有 playwright，出不了图") from None
    got = _norm("".join(page_text(p) for p in pages))
    want = _norm("".join(re.sub(r"\*\*", "", b["text"]) for b in blocks if b["kind"] != "img"))
    if got != want:
        raise XhsError("排完的字和原文对不上，没有出图")  # 不该发生；发生了就别让它发出去
    count = len(pages) + 1
    meta = {"source_sha256": digest(markdown), "images": count, "chars": len(want),
            "over_limit": count > MAX_IMAGES, "font_scale": scale,
            "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    (out / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def state(article: Path | None) -> dict[str, Any]:
    """已经出的图；文章改过就 stale（旧图作废）。"""
    if article is None or not article.is_file():
        return {"images": [], "stale": False}
    out = article.parent / FOLDER
    images = sorted(p.name for p in out.glob("*.png")) if out.is_dir() else []
    try:
        meta = json.loads((out / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    stale = bool(images) and meta.get("source_sha256") != digest(article.read_text(encoding="utf-8"))
    return {"images": images, "stale": stale, "max": MAX_IMAGES,
            **{k: meta.get(k) for k in ("chars", "over_limit", "generated_at", "font_scale")}}
