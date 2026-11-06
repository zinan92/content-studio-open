"""证据素材：给文章配「真的」图，夜里跑（10/1 作者）。

作者：「内容里虽然有插图，但看起来都是 AI 做的，这降低了真实感。」证据有两种：
  1. 他自己视频里的画面——录口播时屏幕右边开着的备忘录、AI 简报、和 Wendy 的对话。他当时真写的东西。
  2. 名人发过的、和文章观点一样的推文（「要不然文章证据太少了」）；找不到就不放，不硬凑、不编。
只出提案，不动正式稿：
  - evidence/ 里放截好的图，evidence/proposal.json 记每张放在哪一段后面、为什么；
  - article.evidence.md 是插好图的整篇，作者 看过点「用」才换进 article.md（定稿、排版都不在这里动）。
10/2 作者：找了图没人看，等于白找（那天《100 件事 99 件不赚钱》的提案躺在文件夹里，发出去一张没有）。
改成打包页「插图」那一步点按钮才找（「要不要找证据图」由他问），找完在同一处一张张选「要 / 不要」，
放进文章或者整篇不要。没定之前，补发工作台里这篇的 X、公众号先不让发。

流程：每 10 秒取一帧、去重（不看下面字幕那条）→ 拼一张总览图、每帧带前后几句口播
→ claude -p 挑帧、给裁剪框、找推文（只读工具：看图、搜网页）→ 这里逐张核对：
裁剪框夹回画面里、字够清楚、OCR 里没有 AppID / 密钥 / 手机号 / 邮箱；推文用公开的嵌入接口查真有这条、
是这个人发的、原话对得上，再用 X 官方嵌入卡片截图。对不上的一律扔掉。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable
import urllib.request

OCR = Path(__file__).parent / "ocr_text.swift"
WORK = "analysis/evidence"
OUT = "evidence"
PROPOSAL = "proposal.json"
PROPOSED = "article.evidence.md"
EVERY_SECONDS = 10
SUBTITLE_BAND = 0.22   # 画面下面这么高是烧进去的字幕，去重时不看
DIFF_MIN = 6.0         # 两帧（不看字幕）平均差这么多才算换了画面
MIN_CROP = (360, 200)  # 裁出来比这还小，看不清
MIN_CHARS = 20         # OCR 读出来的字少于这么多：糊了，或者根本没字
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
EVIDENCE_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "Read Glob WebSearch WebFetch" '
    '--disallowedTools "Bash Edit Write NotebookEdit"'
)
# 截图里不能出现的东西：微信 AppID、各种密钥、长串十六进制、手机号、邮箱
PRIVATE = [
    re.compile(r"wx[0-9a-f]{16}", re.I),
    re.compile(r"\b[0-9a-f]{12,}\b", re.I),
    re.compile(r"\b(sk|pk|ghp|gho|xox[bp]|AKIA)[-_A-Za-z0-9]{8,}"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"(api[_ ]?key|secret|token|password|密码|密钥)\s*[:：=]", re.I),
]

Runner = Callable[[list[str], str], str]
LLM = Callable[[str], str]
Lookup = Callable[[str], dict[str, Any] | None]
Shot = Callable[[str, Path], None]


class EvidenceError(RuntimeError):
    """说给人听的一句话。"""


BACKUP = "article.before-evidence.md"


def _load(article: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((article.parent / OUT / PROPOSAL).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save(article: Path, data: dict[str, Any]) -> None:
    (article.parent / OUT / PROPOSAL).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def in_article(markdown: str) -> list[str]:
    """文章里已经放着的证据图（文件名）。"""
    return [Path(m.group(1)).name for b in markdown.splitlines() if (m := IMAGE_LINE.match(b.strip())) and m.group(1).startswith(OUT + "/")]


def strip(markdown: str) -> str:
    """去掉证据图那几行。定稿看的是文字：放图、撤图都不算改文章（公众号排版照样要重排）。"""
    lines = [b for b in markdown.splitlines() if not ((m := IMAGE_LINE.match(b.strip())) and m.group(1).startswith(OUT + "/"))]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def status(article: Path) -> dict[str, Any]:
    """这篇的证据图走到哪了：none 还没找 / empty 找了没合适的 / pending 等他挑 / applied 放进文章了 / skipped 他说不要。"""
    data = _load(article)
    text = article.read_text(encoding="utf-8") if article.is_file() else ""
    used = in_article(text)
    if data is None:
        return {"state": "applied" if used else "none", "items": [], "rejected": 0, "used": used}
    items = [i for i in data.get("items") or [] if i.get("placed") and (article.parent / OUT / str(i.get("file") or "")).is_file()]
    decision = data.get("decision") or {}
    state = ("applied" if used else decision.get("state") if decision.get("state") == "skipped"
             else "pending" if items else "empty")
    return {"state": state, "items": items, "rejected": len(data.get("rejected") or []), "used": used,
            "decided_at": decision.get("at"), "can_undo": bool(used and (article.parent / BACKUP).is_file())}


def pending(article: Path) -> bool:
    """找到了图、他还没挑：这篇的文字平台先别发。"""
    return status(article)["state"] == "pending"


def apply(article: Path, files: list[str], *, now: str) -> dict[str, Any]:
    """他挑的那几张放进正式稿（按提案的位置，顶掉指定的 AI 图）；一张都不挑就记「这篇不要」，文章不动。"""
    data = _load(article)
    if data is None:
        raise EvidenceError("这篇还没找过证据图")
    markdown = article.read_text(encoding="utf-8")
    if in_article(markdown):
        raise EvidenceError("文章里已经放了证据图，要重挑先点「撤回」")
    chosen = [i for i in data.get("items") or [] if i.get("placed") and i.get("file") in set(files)]
    if files and not chosen:
        raise EvidenceError("挑的图不在提案里，刷新一下再挑")
    if chosen:
        text, placed = propose(markdown, chosen)
        if not all(p["placed"] for p in placed):
            raise EvidenceError("文章改过了，有的图找不到该放的那一段：重新找一遍证据图")
        (article.parent / BACKUP).write_text(markdown, encoding="utf-8")
        article.write_text(text, encoding="utf-8")
    data["decision"] = {"state": "applied" if chosen else "skipped", "files": [i["file"] for i in chosen], "at": now}
    _save(article, data)
    return status(article)


def undo(article: Path) -> dict[str, Any]:
    """撤回：放进去的证据图拿掉、顶掉的 AI 图回来（回到放图之前那一版）；说过「不要」的回到等他挑。
    放图之后他改过文字，就不能整篇退回去了，免得把他改的字一起退掉。"""
    from ...illustrate import strip_images

    words = lambda md: strip_images(strip(md))  # noqa: E731 - 只比字，图不算
    data = _load(article)
    backup = article.parent / BACKUP
    markdown = article.read_text(encoding="utf-8")
    if in_article(markdown):
        if not backup.is_file():
            raise EvidenceError("找不到放图之前那一版，只能在文章里手动删掉证据图")
        before = backup.read_text(encoding="utf-8")
        if words(before) != words(markdown):
            raise EvidenceError("放图之后文章改过字了，不能整篇退回：在文章里手动删掉证据图那几行")
        article.write_text(before, encoding="utf-8")
        backup.unlink()
    if data is not None:
        data.pop("decision", None)
        _save(article, data)
    return status(article)


def _run(args: list[str], what: str, timeout: int = 600) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError(f"{what}失败：{exc}") from exc
    if done.returncode != 0:
        raise EvidenceError(f"{what}失败：{(done.stderr or done.stdout).strip()[-200:]}")
    return done.stdout


# -- 帧 ------------------------------------------------------------------------

def sample_frames(video: Path, folder: Path, *, every: int = EVERY_SECONDS, run: Runner = _run) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    if not any(folder.glob("f*.jpg")):
        run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{every}", "-q:v", "2", str(folder / "f%04d.jpg")], "取帧", 1800)
    return sorted(folder.glob("f*.jpg"))


def at_seconds(frame: Path, every: int = EVERY_SECONDS) -> int:
    """ffmpeg 的 fps 滤镜：第 n 张大约在 (n-1)*every 秒。"""
    return (int(re.sub(r"\D", "", frame.stem) or 1) - 1) * every


def distinct(frames: list[Path]) -> list[Path]:
    """换了画面的才留（不看下面字幕那条：只是字幕变了不算）。"""
    from PIL import Image, ImageChops, ImageStat

    keep, prev = [], None
    for p in frames:
        im = Image.open(p).convert("L")
        w, h = im.size
        small = im.crop((0, 0, w, int(h * (1 - SUBTITLE_BAND)))).resize((160, 72))
        if prev is None or ImageStat.Stat(ImageChops.difference(small, prev)).mean[0] > DIFF_MIN:
            keep.append(p)
            prev = small
    return keep


def contact_sheet(frames: list[Path], out: Path, *, cols: int = 5, width: int = 480) -> Path:
    from PIL import Image, ImageDraw

    first = Image.open(frames[0])
    height = round(width * first.height / first.width)
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, rows * height), "white")
    for i, p in enumerate(frames):
        im = Image.open(p).convert("RGB").resize((width, height))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 120, 26), fill="black")
        d.text((6, 6), f"{p.stem}  {at_seconds(p)}s", fill="white")
        sheet.paste(im, ((i % cols) * width, (i // cols) * height))
    sheet.save(out, quality=82)
    return out


def spoken_near(segments: list[dict[str, Any]], t: float, window: float = 15.0) -> str:
    return "".join(s.get("text") or "" for s in segments if t - window <= float(s.get("start") or 0) <= t + window)[:160]


# -- 让模型挑 ----------------------------------------------------------------------

def build_prompt(article: str, frames: list[dict[str, Any]], *, sheet: Path | None, size: tuple[int, int], illustrations: list[str],
                 pool: list[dict[str, Any]] | None = None) -> str:
    listing = "\n".join(f"- {f['id']}（{f['at']} 秒，{f['path']}）口播：{f['spoken'] or '（没有）'}" for f in frames)
    picked = "\n".join(f"- {i['file']}（{i.get('kind')}，论点 {i.get('point')}「{i.get('point_title', '')}」）{i.get('caption', '')}"
                       f"{'；证明：' + i['claim'] if i.get('claim') else ''}；来源：{i.get('source', '')} {str(i.get('date') or '')[:10]}"
                       for i in pool or [])
    people = "、".join(sorted({str(i.get("source") or "") for i in pool or [] if i.get("kind") == "tweet"}))
    first = f"""零、他拍之前在骨架页点过「要」的证据（新闻、数据、原推、他自己的截图），都已经核对过、截好了：
{picked}
   文章里讲到同一件事的那一段后面放上它，**这些优先用**；文章里确实没讲到的就不放。写在 JSON 的 pool 里。

""" if pool else ""
    video = f"""一、他自己视频里的画面。他录口播时，屏幕上开着自己的备忘录、AI 简报、和 AI 助手的对话。这些是他当时真写、真收到的东西。
   总览图：{sheet}（每格左上角是帧号和秒数）。单帧都在下面列的路径里，用 Read 打开看清楚。画面 {size[0]}×{size[1]}。
   左下或左边常有一个圆角框是他的脸，下面是烧进去的字幕，底部可能有 Dock 栏：裁剪时都避开，只留文字内容那一块。
   左边的备忘录侧栏、聊天列表里常有 AppID、文件名、别人的名字：也避开，宁可裁小一点。
   只挑和文章某一段说的是同一件事的画面（比如文章写「先给你看一个东西」「它回我每天六百到九百篇」，就找那一帧）。
   挑 2–6 张，宁缺毋滥；字太糊、内容和文章对不上的不要。

""" if frames else "一、这篇没有视频画面可用，frames 给空列表。\n\n"
    return f"""你在帮 作者 给他的一篇文章找「真的」证据图。文章里现在的插图都是 AI 画的，读者觉得不真实。

{first}{video}二、名人发过的、和文章某个观点一样的推文（英文中文都行），用 WebSearch / WebFetch 找。
   只要你能给出原帖链接（x.com 或 twitter.com 的 status 链接）、并且原话你确实在网页上看到过的。找不到就一条都不给，绝不编。
   0–3 条，挑最有分量的人、最贴切的原话；一篇里同一个人只用一条，换不同的人{('，已经用过：' + people) if people else ''}。
   前面「零」里已经有的证据说的是同一件事时，就不用再找推文。

可以顶掉的 AI 插图（同一段已经有更真的图时）：{', '.join(illustrations) or '（没有）'}

各帧：
{listing}

文章：
<article>
{article}
</article>

只回一个 JSON 代码块，不要别的话：
```json
{{"pool": [{{"file": "零里的文件名", "after": "放在哪一段后面：那一段开头的原文，一字不差抄 12–20 个字", "replaces": "可以顶掉的 AI 插图文件名，没有就空字符串"}}],
  "frames": [{{"id": "f0008", "crop": [左, 上, 右, 下], "after": "放在哪一段后面：那一段开头的原文，一字不差抄 12–20 个字", "caption": "一句话说这张图是什么，第一人称，带上「真实截图」或「我的备忘录」这类字", "replaces": "可以顶掉的 AI 插图文件名，没有就空字符串"}}],
  "tweets": [{{"url": "https://x.com/<账号>/status/<数字>", "screen_name": "账号", "quote": "推文里的一句原话（逐字，至少 6 个词）", "after": "同上", "caption": "谁、哪年说的，一句话"}}]}}
```
"""


def parse(output: str) -> dict[str, Any]:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", output, re.S) or re.search(r"(\{.*\})", output, re.S)
    if not m:
        raise EvidenceError("模型没按格式回 JSON")
    try:
        data = json.loads(m.group(1))
    except ValueError as exc:
        raise EvidenceError("模型回的 JSON 坏了") from exc
    return {"frames": [f for f in data.get("frames") or [] if isinstance(f, dict)],
            "tweets": [t for t in data.get("tweets") or [] if isinstance(t, dict)],
            "pool": [x for x in data.get("pool") or [] if isinstance(x, dict)]}


# -- 核对 ------------------------------------------------------------------------------

def clamp(box: Any, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    try:
        l, t, r, b = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    w, h = size
    l, t, r, b = max(0, l), max(0, t), min(w, r), min(h, b)
    if r - l < MIN_CROP[0] or b - t < MIN_CROP[1]:
        return None
    return l, t, r, b


def ocr(paths: list[Path], *, run: Runner = _run) -> dict[Path, str]:
    if not paths or not shutil.which("swift"):
        return {}
    out = run(["swift", str(OCR), *map(str, paths)], "读字", 600)
    texts: dict[Path, list[str]] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("### "):
            cur = Path(line[4:])
            texts[cur] = []
        elif cur is not None:
            texts[cur].append(line)
    return {p: "\n".join(v) for p, v in texts.items()}


def private_hit(text: str) -> str | None:
    for rx in PRIVATE:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


TWEET_ID = re.compile(r"(?:x|twitter)\.com/(\w+)/status/(\d+)")


def lookup_tweet(tweet_id: str) -> dict[str, Any] | None:
    """X 官方嵌入用的公开接口：不用登录、不用密钥。查不到返回 None。"""
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token=4"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            data = json.loads(r.read().decode() or "{}")
    except (OSError, ValueError):
        return None
    return data if data.get("text") else None


def _words(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def verify_tweet(item: dict[str, Any], lookup: Lookup = lookup_tweet) -> dict[str, Any] | None:
    m = TWEET_ID.search(str(item.get("url") or ""))
    if not m:
        return None
    data = lookup(m.group(2))
    if not data:
        return None
    name = str(((data.get("user") or {}).get("screen_name")) or "")
    want = str(item.get("screen_name") or m.group(1)).lstrip("@")
    quote = _words(str(item.get("quote") or ""))
    if name.lower() != want.lower() or len(quote.split()) < 3 or quote not in _words(data["text"]):
        return None
    return {"id": m.group(2), "screen_name": name, "text": data["text"], "created_at": data.get("created_at"), "url": f"https://x.com/{name}/status/{m.group(2)}"}


def shoot_tweet(tweet_id: str, out: Path) -> None:
    """X 官方嵌入卡片截图（无头 Chrome），去掉下面的空白。"""
    from PIL import Image

    _run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=560,420",
          "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000", f"--screenshot={out}",
          f"https://platform.twitter.com/embed/Tweet.html?id={tweet_id}&theme=light&lang=zh-cn&hideThread=true"], "截推文", 120)
    im = Image.open(out).convert("RGB")
    px, (w, h) = im.load(), im.size
    last = max((y for y in range(h) if any(sum(px[x, y]) < 740 for x in range(0, w, 4))), default=h - 1)
    im.crop((0, 0, w, min(h, last + 4))).save(out)


# -- 插进文章（只出提案） ----------------------------------------------------------------

IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\(([^)\s]+)\)\s*$")


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`>#\-，。、,.!！?？：:；;“”\"'（）()]+", "", text or "")


def propose(markdown: str, items: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """按 after 把图插到那一段后面；replaces 指名的 AI 插图那一行换掉。原有的图都留着。对不上的报出来。"""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    placed, after = [], {}
    drop = set()
    for item in items:
        anchor = _norm(str(item.get("after") or ""))[:16]
        hit = None
        if anchor:
            hit = next((i for i, b in enumerate(blocks) if not IMAGE_LINE.match(b.strip()) and _norm(b).startswith(anchor)), None)
            if hit is None:
                hit = next((i for i, b in enumerate(blocks) if not IMAGE_LINE.match(b.strip()) and anchor in _norm(b)), None)
        if hit is None:
            placed.append({**item, "placed": False, "why": "找不到它该放的那一段"})
            continue
        caption = str(item.get("caption") or "").replace("[", "（").replace("]", "）").strip()
        after.setdefault(hit, []).append(f"![{caption}]({OUT}/{item['file']})")
        rep = Path(str(item.get("replaces") or "")).name
        if rep:
            drop.update(i for i, b in enumerate(blocks) if (m := IMAGE_LINE.match(b.strip())) and Path(m.group(1)).name == rep)
        placed.append({**item, "placed": True})
    out = []
    for i, b in enumerate(blocks):
        if i not in drop:
            out.append(b)
        out.extend(after.get(i, []))
    return "\n\n".join(out).rstrip() + "\n", placed


def run_topic(article: Path, video: Path | None, *, segments: list[dict[str, Any]] | None = None, llm: LLM | None = None,
              run: Runner = _run, lookup: Lookup = lookup_tweet, shot: Shot = shoot_tweet,
              pool: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """一篇文章跑一遍：结果放在文章旁边的 evidence/ 和 article.evidence.md，不碰 article.md。
    pool 是他拍之前在骨架页点过「要」的证据（proof.chosen，10/5）：优先放这些；没有视频时只用它们和推文。"""
    from PIL import Image

    from ...writer import cli_write

    base = article.parent
    work = base / WORK
    out = base / OUT
    if in_article(article.read_text(encoding="utf-8")):
        raise EvidenceError("文章里已经放着证据图了：要重新找，先点「撤回」把它们拿出来")
    pool = [i for i in pool or [] if Path(str(i.get("path") or "")).is_file()]
    if video is None and not pool:
        raise EvidenceError("没有视频，骨架页也没点过「要」的证据")
    frames = distinct(sample_frames(video, work / "frames", run=run)) if video is not None else []
    if video is not None and not frames:
        raise EvidenceError("视频里取不到帧")
    work.mkdir(parents=True, exist_ok=True)
    size = Image.open(frames[0]).size if frames else (0, 0)
    sheet = contact_sheet(frames, work / "sheet.jpg") if frames else None
    info = [{"id": p.stem, "at": at_seconds(p), "path": str(p), "spoken": spoken_near(segments or [], at_seconds(p))} for p in frames]
    markdown = article.read_text(encoding="utf-8")
    ills = [Path(m.group(1)).name for b in markdown.splitlines() if (m := IMAGE_LINE.match(b.strip())) and not m.group(1).startswith(OUT + "/")]
    prompt = build_prompt(markdown, info, sheet=sheet, size=size, illustrations=ills, pool=pool)
    (work / "prompt.md").write_text(prompt, encoding="utf-8")
    # 帧放在文章旁边的 analysis/ 里：命令行的 claude 默认只能读当前目录，给它加上这个目录
    raw = (llm or (lambda p: cli_write(p, command=f'{EVIDENCE_COMMAND} --add-dir "{work}"', timeout=1800)))(prompt)
    (work / "answer.txt").write_text(raw, encoding="utf-8")
    plan = parse(raw)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    by_id = {p.stem: p for p in frames}
    items, rejected, crops = [], [], []
    for n, f in enumerate(plan["frames"], 1):
        src = by_id.get(str(f.get("id") or ""))
        box = clamp(f.get("crop"), size) if src else None
        if src is None or box is None:
            rejected.append({**f, "why": "没有这一帧，或者裁剪框太小"})
            continue
        dest = out / f"{n:02d}-{src.stem}.jpg"
        Image.open(src).convert("RGB").crop(box).save(dest, quality=92)
        crops.append((dest, f))
    texts = ocr([d for d, _ in crops], run=run)
    for dest, f in crops:
        text = texts.get(dest)
        if text is not None:
            hit = private_hit(text)
            if hit:
                dest.unlink()
                rejected.append({**f, "why": f"截图里有隐私（{hit[:4]}…），不用"})
                continue
            if len(re.sub(r"\s", "", text)) < MIN_CHARS:
                dest.unlink()
                rejected.append({**f, "why": "字太糊，或者没什么字"})
                continue
        items.append({"kind": "frame", "file": dest.name, "at": at_seconds(by_id[f["id"]]), **{k: f.get(k, "") for k in ("after", "caption", "replaces")}})
    by_file = {i["file"]: i for i in pool}
    for x in plan["pool"]:
        src = by_file.pop(str(x.get("file") or ""), None)
        if src is None:
            continue  # 不在他点过的里面（或者重复给了）：不认
        dest = out / f"pool-{src['file']}"
        shutil.copyfile(src["path"], dest)
        items.append({"kind": src.get("kind") or "news", "file": dest.name, "url": src.get("url") or "", "source": src.get("source") or "",
                      "date": src.get("date") or "", "caption": src.get("caption") or "", "after": x.get("after", ""),
                      "replaces": x.get("replaces", ""), "from": "skeleton"})
    people = {str(i.get("source") or "").lower() for i in pool if i.get("kind") == "tweet"}
    for n, t in enumerate(plan["tweets"], 1):
        ok = verify_tweet(t, lookup)
        if not ok:
            rejected.append({**t, "why": "查不到这条推文，或者不是这个人发的、原话对不上"})
            continue
        if ok["screen_name"].lower() in people or "@" + ok["screen_name"].lower() in people:
            rejected.append({**t, "why": "这个人这篇已经用过一条了"})
            continue
        people.add(ok["screen_name"].lower())
        dest = out / f"tweet-{n:02d}-{ok['screen_name']}.png"
        try:
            shot(ok["id"], dest)
        except EvidenceError as exc:
            rejected.append({**t, "why": str(exc)})
            continue
        items.append({"kind": "tweet", "file": dest.name, "url": ok["url"], "text": ok["text"], "created_at": ok["created_at"],
                      **{k: t.get(k, "") for k in ("after", "caption")}, "replaces": ""})
    text, placed = propose(markdown, items)
    (base / PROPOSED).write_text(text, encoding="utf-8")
    result = {"video": str(video) if video else None, "frames_seen": len(frames), "items": placed, "rejected": rejected}
    (out / PROPOSAL).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
