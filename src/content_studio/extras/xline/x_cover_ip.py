"""X 长文封面：像抖音封面那样抓眼，人换成他的 作者 形象，红色更多，标题为点击率写（10/10 作者）。

作者：「x 的长文的封面需要改一下，需要变成类似我抖音视频的封面，但是 with 我的 park ip 形象，以及让封面更有记忆点：
我的形象以及更多红色 & title 要提高封面点击率。」（以前是 9/24 定的纯文字横幅，不带人脸。）

- 标题：照 Anna 的「标题.md」（暴论、绝对词、离钱近、不编数字、原文撑得住）给 4–6 个封面短标题，第一条默认用；
  他能在页面上换一条或自己改，再重出。代码查：字数、数字要在原文里、不是问句套问句。
- 图：Codex image_gen，参考图是他的形象定稿（fullbody / avatar / spec）和抖音封面的风格参考（只学视觉语言）；
  朱红 #E2461F 占画面一大块；所有字和脸放在中间 5:2 的带里，出图后裁成 1500×600（X 文章封面的比例）。
- 封面出不来不挡文章：发的时候退回原来的纯文字横幅。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

from ... import writer

COVER = "x-cover.png"
WORK = "cover-work"
WIDTH, HEIGHT = 1500, 600
HEADLINE_MAX = 18          # 封面上的字要大，长了就小；X 时间线里封面也就手机一屏宽
HEADLINE_MIN, HEADLINE_N = 4, 6
LINE = re.compile(r"^\s*\d+\s*[.、)）]\s*(?P<title>.+?)\s*[｜|]\s*(?P<pattern>[^｜|]+?)\s*[｜|]\s*(?:依据\s*[:：])?\s*(?P<basis>.+?)\s*$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
TIMEOUT_SECONDS = 20 * 60
STYLE_REF = "assets/covers/park-bold-orange-v1-4x3.png"
PERSONA_FILES = ("fullbody.png", "avatar.png", "spec.md")

Runner = Callable[[str, Path], None]


class CoverError(RuntimeError):
    """Shown to 作者 as-is."""


# -- 标题 ----------------------------------------------------------------------------------------------


def headline_prompt(title: str, article: str, framework: str, error: str | None = None) -> str:
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""给 作者 这篇 X 长文的封面写 {HEADLINE_MIN}–{HEADLINE_N} 个封面标题候选，按点击率从高到低排，第一条最好。
封面在 X 的时间线里只有手机一屏宽，字要大：每条不超过 {HEADLINE_MAX} 个字（中英文都算一个），一口气读完，不要冒号接副标题。
不要用「我觉得」「我认为」开头——封面上要直接下判断。

照下面这份标题标准写（暴论、绝对词、离钱近；原文撑得住；不许编数字——标题里每个数字都必须在原文里出现过）：

{framework.strip()[:4000]}

## 文章标题
{title}

## 文章（节选）
{article.strip()[:6000]}

## 输出
只输出候选，一行一条：`1. 标题｜句式｜依据：「原文里的那一句」`。{retry}"""


def check_headline(text: str, article: str) -> str | None:
    if not text:
        return "是空的"
    if len(text) > HEADLINE_MAX:
        return f"太长（{len(text)} 字）"
    if text.count("？") + text.count("?") > 1:
        return "问句套问句"
    if re.match(r"^我(觉得|认为)", text):
        return "封面别用「我觉得」开头"
    invented = [n for n in NUMBER.findall(text) if n not in article]
    if invented:
        return f"数字原文里没有：{'、'.join(invented)}"
    return None


def headlines(title: str, article: str, *, write_fn: Callable[[str], str], framework: str, attempts: int = 2) -> list[dict[str, str]]:
    """封面标题候选，第一条默认用。不够 HEADLINE_MIN 条能用的就重写一次；再不够有几条给几条，一条都没有就报错。"""
    error, kept = None, []
    for _ in range(attempts):
        raw = str(write_fn(headline_prompt(title, article, framework, error)) or "")
        kept, bad = [], []
        for line in raw.splitlines():
            m = LINE.match(line)
            if not m:
                continue
            t = m.group("title").strip().strip("「」\"'")
            why = check_headline(t, article)
            if why:
                bad.append(f"「{t}」{why}")
                continue
            if t not in [k["title"] for k in kept]:
                kept.append({"title": t, "pattern": m.group("pattern").strip(), "basis": m.group("basis").strip()})
        if len(kept) >= HEADLINE_MIN:
            return kept[:HEADLINE_N]
        error = "；".join(bad[:3]) or "没有按格式输出"
    if kept:
        return kept
    raise CoverError(f"封面标题没写出来：{error}")


# -- 图 ------------------------------------------------------------------------------------------------


def prompt(headline: str) -> str:
    return f"""用 image_gen 生成一张 X 长文的封面，直接生成，不用等我确认。当前目录里有：

- persona-ref/fullbody.png（定稿正本）、persona-ref/avatar.png（脸部细节）、persona-ref/spec.md（这个人的固定规范）——
  SOLE CHARACTER SOURCE：封面上唯一的人物就是这个 作者 潮玩手办形象：清瘦、约 5–6 头身（不是 Q 版大头）、短黑发头顶尖翘、
  细长单眼皮、朱红 #E2461F 圆领 T 恤胸口米白衬线体「作者」、深炭灰直筒西裤、纯白运动鞋。哑光手绘厚涂 3D 手办质感。
  脸、发型、身材、衣服逐项照定稿，不要换成真人照片、不要换脸、不要加眼镜手表。
- style-ref.png——STYLE REFERENCE ONLY（他抖音封面的样子）：只学视觉语言——超大超粗、向右倾斜的紧凑黑体标题，
  黑字带白色描边感；标题下一道干笔刷下划线；斜角色条。不要用里面的真人、衣服、手势和文字。

要做到：
1. 画面 3:2（1536×1024）。**所有字和人物的脸都放在中间那条 5:2 的横带里**（上下各留约 1/5 只放背景色块），
   因为这张图会被裁成 1500×600。
2. **比抖音封面更多红色、更有记忆点**：朱红 #E2461F 占画面约 40%——比如右侧一大块斜切的朱红底，人物站在红色上；
   左侧暖米白纸张底放标题。一眼就能认出是 作者：红色 + 这个手办形象。
3. 标题逐字使用，不能改字、不能加字、不能加减标点，不加任何英文、小标签、平台名：
   {headline}
   标题压左边约 55% 宽，分 2–3 行，字大到几乎顶满左半边；挑 1–2 个最有冲击的词（数字、反差、结果）用朱红，其余黑色。
4. 作者 手办形象在右侧，胸口以上到半身，放大、脸大而清楚，表情和手势配合标题（比如指向标题、抱臂、皱眉思考、摊手），
   身体可以压住红色和米白的分界，有一点出框的立体感；头顶到 5:2 横带上沿留一点空，头发不要被切掉。

生成后自己检查：标题是否逐字一致；人物是不是定稿里的 作者（脸、发型、T 恤上的 作者 字样）；裁成中间 5:2 以后有没有切到字和脸；
缩到 400 像素宽时标题是否还能一眼读清。不合格就重生成，最多试 3 次。最后只保留最好的一张为 out/cover.png，
另写 out/receipt.json：{{"prompt": 你实际用的完整提示词, "checks": {{"text": ..., "character": ..., "crop": ..., "thumbnail": ...}}}}。
不要改当前目录里的其他文件。
"""


def codex_runner(text: str, cwd: Path) -> None:
    from ...illustrate import IllustrateError, codex_exec

    try:
        done = subprocess.run(codex_exec(text), cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS)
    except IllustrateError as exc:
        raise CoverError(str(exc).replace("配不了图", "出不了封面")) from exc
    except subprocess.TimeoutExpired as exc:
        raise CoverError(f"出封面超过 {TIMEOUT_SECONDS // 60} 分钟还没好，停了") from exc
    (cwd / "codex.log").write_text((done.stdout or "") + (done.stderr or ""), encoding="utf-8")
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise CoverError("出封面失败：" + " / ".join(tail)[:240])


def crop(src: Path, out: Path) -> Path:
    """缩放到正好盖住 1500×600，再取正中间：X 文章封面是 5:2。"""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            scale = max(WIDTH / im.width, HEIGHT / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            left, top = (im.width - WIDTH) // 2, (im.height - HEIGHT) // 2
            im.crop((left, top, left + WIDTH, top + HEIGHT)).save(out, "PNG")
    except (OSError, UnidentifiedImageError) as exc:
        raise CoverError(f"封面裁成 5:2 没成：{exc}") from exc
    return out


def refs() -> tuple[Path, Path]:
    from ... import conf
    from ..positioning import persona

    root = persona.root()
    missing = [n for n in PERSONA_FILES[:2] if not (root / n).is_file()]
    if missing:
        raise CoverError("个人形象还没做好（设置 · 个人形象）：缺 " + "、".join(missing))
    style = conf.path("skills.koubo") / STYLE_REF
    if not style.is_file():
        raise CoverError(f"找不到抖音封面的风格参考图：{style}")
    return root, style


def draw(folder: Path, headline: str, *, runner: Runner = codex_runner) -> Path:
    """在这篇长文的文件夹里出封面：folder/x-cover.png（1500×600）。上一张挪成 x-cover.old.png，这次没成就留着它。"""
    headline = headline.strip()
    if not headline:
        raise CoverError("封面标题是空的")
    root, style = refs()
    work = folder / WORK
    shutil.rmtree(work, ignore_errors=True)
    (work / "out").mkdir(parents=True)
    stage = work / "persona-ref"
    stage.mkdir()
    for name in PERSONA_FILES:
        if (root / name).is_file():
            shutil.copy2(root / name, stage / name)
    shutil.copy2(style, work / "style-ref.png")
    runner(prompt(headline), work)
    made = work / "out" / "cover.png"
    if not made.is_file():
        raise CoverError("封面没画出来（out/cover.png 不在）")
    out = folder / COVER
    if out.exists():
        out.replace(folder / "x-cover.old.png")
    crop(made, out)
    try:
        receipt = json.loads((work / "out" / "receipt.json").read_text(encoding="utf-8"))
        (folder / "x-cover.receipt.json").write_text(json.dumps({"headline": headline, **receipt}, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    except (OSError, ValueError):
        pass
    shutil.rmtree(work, ignore_errors=True)
    return out
