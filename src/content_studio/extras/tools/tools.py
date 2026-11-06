"""单点功能（10/9 作者：「先做 10 个试试」）：一样东西进、一样东西出，贴进去就出结果。

功能清单里挑了 10 个文字和出图的，先给 作者自己试。
全走本机 Codex，模型用 profile 的 codex.model（gpt-6.1-sol），推理强度 medium（作者 定的）：
- 文字：claude 样式的命令交给 llm.run，--model sonnet 会翻成 Codex 的 medium、不读本机 Codex 配置；
- 出图：和封面、配图同一条 `codex exec`（image_gen 要本机配置里的登录和工具），这里多压一个 medium。

每跑一次是 ~/.config/content-studio/tools/<编号>/ 一个文件夹：输入、结果、图都在里面。
不建选题、不写草稿、不碰 Obsidian——能复用的是各功能的提示词和校验，不是它们写选题的那一层。
出图要几分钟，所以一律进后台队列，一次跑一个；页面轮询。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
from typing import Any, Callable

from ...paths import config_dir

TEXT_COMMAND = ('claude -p --model sonnet --output-format text '
                '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"')
IMAGE_TIMEOUT = 20 * 60
MAX_INPUT = 20000
KEEP = 50  # 页面上留最近 50 次


class ToolError(RuntimeError):
    """说给人听的一句话。"""


TextFn = Callable[[str], str]
ImageFn = Callable[[str, Path], None]


def root() -> Path:
    return config_dir() / "tools"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- 两个出口：测试换成假的 -----------------------------------------------------

def codex_text(prompt: str) -> str:
    from ... import llm

    done = llm.run(shlex.split(TEXT_COMMAND), input=prompt, timeout=600)
    if done.returncode != 0 or not (done.stdout or "").strip():
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-2:]
        raise ToolError(f"{llm.label()} 没回话：" + (" / ".join(tail)[:200] or llm.login_hint()))
    return done.stdout


def image_argv(prompt: str) -> list[str]:
    from ...illustrate import codex_exec

    argv = codex_exec(prompt)
    return [*argv[:-1], "-c", 'model_reasoning_effort="medium"', argv[-1]]


def codex_image(prompt: str, cwd: Path) -> None:
    try:
        # stdin 关掉：codex exec 看到 stdin 开着会一直等输入（封面那边 9/29 卡过）
        done = subprocess.run(image_argv(prompt), cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=IMAGE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"超过 {IMAGE_TIMEOUT // 60} 分钟还没画完，停了") from exc
    (cwd / "codex.log").write_text((done.stdout or "") + (done.stderr or ""), encoding="utf-8")
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise ToolError("出图失败：" + " / ".join(tail)[:240])


TEXT: dict[str, TextFn] = {"fn": codex_text}
IMAGE: dict[str, ImageFn] = {"fn": codex_image}


def ask(prompt: str) -> str:
    return TEXT["fn"](prompt)


def draw(prompt: str, cwd: Path) -> None:
    IMAGE["fn"](prompt, cwd)


# -- 10 个功能 -----------------------------------------------------------------

def _field(name: str, label: str, kind: str = "text", hint: str = "", required: bool = True, options: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "label": label, "kind": kind, "hint": hint, "required": required, "options": options or []}


# 生图风格：先放 6 种，样子都用文字说清楚（不靠别人的参考图）
STYLES: dict[str, str] = {
    "手绘草图": "纯白纸底，黑色手绘线稿，少量红、橙、蓝批注，像在白纸上随手画的解释图，留白多",
    "纽约客极简": "《纽约客》式极简社论插画：大面积留白，细黑线条，只用一个橙色做点睛，一个巧妙的视觉隐喻",
    "材质插画": "柔和的 3D 材质插画：哑光陶土或磨砂塑料质感，柔和体积光，低饱和配色，干净的浅色背景",
    "扁平信息图": "扁平矢量信息图：几何图形、清楚的层级、两三种主色加灰色，像一页讲得很清楚的说明图",
    "复古未来主义": "复古未来主义海报：60 年代太空时代的想象，暖橙、青绿、奶油色，颗粒质感，先想一个隐喻再套风格",
    "瑞士国际主义": "瑞士国际主义平面设计：严格网格、大号无衬线字、几何色块、红黑白为主，信息清楚有秩序",
}

TOOLS: list[dict[str, Any]] = [
    {"key": "review", "name": "文章点评", "kind": "text", "give": "写好的文章或口播稿",
     "get": "开头有没有说出主线、信息密度撑不撑得住、哪里素材薄、最小改法",
     "fields": [_field("text", "文章或口播稿", "long", "整篇贴进来")]},
    {"key": "topic", "name": "选题打分", "kind": "text", "give": "一句选题 + 手上的素材",
     "get": "三点评分（痛点具象、认知反差、交付可行），值不值得拍、最小改法",
     "fields": [_field("title", "选题", hint="一句话"), _field("material", "素材或提纲", "long", "你打算讲的例子、数据、经历")]},
    {"key": "titles", "name": "标题", "kind": "text", "give": "一句主题 + 文字稿",
     "get": "6–10 个标题候选，带用的哪种写法和依据",
     "fields": [_field("topic", "这条讲什么", hint="一句话"), _field("text", "文字稿", "long", "口播转写或文章，越全标题越准", required=False)]},
    {"key": "clean", "name": "口述 → 口播稿", "kind": "text", "give": "一段语音输入的口述",
     "get": "只删口水词的稿子，一个字不改写",
     "fields": [_field("text", "口述原文", "long", "用语音输入法说完，整段贴进来")]},
    {"key": "teardown", "name": "爆款拆解", "kind": "text", "give": "别人一条视频的文字稿 + 点赞数",
     "get": "主线是什么、开头怎么抓人、哪里撑住了、哪里散了、你能借什么",
     "fields": [_field("text", "文字稿", "long", "整条视频的转写"),
                _field("likes", "这条的点赞", "number", "比如 132819 或 13.3万", required=False),
                _field("median", "这个账号平时一条的点赞", "number", "填了才能判断它算不算真爆", required=False)]},
    {"key": "humanize", "name": "去掉 AI 味", "kind": "text", "give": "一段 AI 写的文字",
     "get": "意思不变、读起来像人写的",
     "fields": [_field("text", "原文", "long")]},
    {"key": "cover", "name": "封面", "kind": "image", "give": "一个标题",
     "get": "一张 3:4 竖版文字封面（米白底、橙红斜角、超粗标题）",
     "fields": [_field("title", "标题", hint="逐字上封面，不改字")]},
    {"key": "illustrate", "name": "正文配图", "kind": "image", "give": "一篇文章",
     "get": "3–4 张 16:9 手绘解释图，插回对应段落",
     "fields": [_field("text", "文章", "long", "整篇贴进来")]},
    {"key": "style", "name": "生图风格", "kind": "image", "give": "一句主题 + 挑一个风格",
     "get": "一张这个风格的图",
     "fields": [_field("topic", "画什么", hint="一句话主题"), _field("style", "风格", "select", options=list(STYLES))]},
    {"key": "xhs", "name": "小红书图文", "kind": "image", "give": "一篇文章",
     "get": "3:4 封面 + 正文页，文章一字不改地排进去",
     "fields": [_field("title", "标题"), _field("text", "正文", "long", "段落之间空一行")]},
]
# 邀请码用的价目（美分，10/10）：不是 Codex 的真实成本（走的是订阅），是给每次运行记的「额度」，
# 让一个 5 美元的码大约是 25 次文字或 10 张图——想改直接改这里。失败的那次退回，不收。
PRICE: dict[str, int] = {
    "review": 20, "topic": 10, "titles": 20, "clean": 10, "teardown": 30, "humanize": 10,
    "cover": 50, "illustrate": 120, "style": 50, "xhs": 20,
}
for _t in TOOLS:
    _t["price"] = PRICE[_t["key"]]
BY_KEY = {t["key"]: t for t in TOOLS}


def catalog() -> list[dict[str, Any]]:
    return TOOLS


def clean_input(key: str, raw: dict[str, Any]) -> dict[str, str]:
    tool = BY_KEY.get(key)
    if not tool:
        raise ToolError("没有这个功能")
    out: dict[str, str] = {}
    for f in tool["fields"]:
        value = str(raw.get(f["name"]) or "").strip()
        if f["required"] and not value:
            raise ToolError(f"「{f['label']}」还没填")
        if len(value) > MAX_INPUT:
            raise ToolError(f"「{f['label']}」太长了，最多 {MAX_INPUT} 字")
        if f["kind"] == "number" and value and not re.fullmatch(r"\d+(\.\d+)?[wW万]?", value):
            raise ToolError(f"「{f['label']}」要填数字")
        if f["kind"] == "select" and value not in f["options"] and not (key == "style" and library_style(value)):
            raise ToolError(f"「{f['label']}」从下拉里选一个")
        out[f["name"]] = value
    return out


# -- 文字功能 ------------------------------------------------------------------

YARDSTICK = """看一条内容只看两件事（和爆款拆解同一把尺子）：
1. 开头：观众在前 15 秒（大约开头 60–80 个字）能不能听到这条内容的主线——它到底要说什么、对我有什么用。
2. 密度：主线说出来以后，每一段是不是都在给主线加料（例子、数据、反差、做法），有没有铺垫过长、绕远路、重复、跑题，让人听散。
不要用空泛套话（如「内容优质」「节奏好」），每个判断都落到原文的具体句子上，引用原文时一字不改。
不要把「5 类生态位」或「四步结构」当成判定规则。"""


def review(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    md = ask(f"""你在点评一篇作者自己写好的文章（或口播稿）。{YARDSTICK}

## 原文
{inp['text']}

## 输出（Markdown，只写下面四节，不写别的）
## 主线
一句话写出这篇真正想让人带走的东西；如果读完都说不出来，就直说「主线不清楚」并说为什么。
## 开头
开头 60–80 个字里有没有说出主线：引用那几句原文，判断「说出了 / 没说出」，没说出的话主线第一次出现在哪句。
## 密度
逐段过一遍：哪几段在给主线加料，哪几段可以删或压缩（引用段落开头原文），哪里素材薄（只有观点没有例子或数据）。
## 最小改法
最多 3 条，按收益从大到小排。每条说清楚改哪一句、怎么改；只动结构和取舍，不替作者重写整段。""")
    return {"markdown": md.strip()}


QA_VERDICT = {"go": "能拍", "patch": "补一补再拍", "thin": "素材太薄，先别拍"}


def topic(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import qa
    from ...judge import parse_json_object

    try:
        r = qa.score_topic(inp["title"], "", inp["material"], qa_fn=lambda p: parse_json_object(ask(p)))
    except qa.QAError as exc:
        raise ToolError(str(exc)) from None
    lines = [f"## {QA_VERDICT.get(r['verdict'], r['verdict'])} · {r['total']} / 15"]
    for key, label in qa.POINTS:
        p = r[key]
        lines += [f"### {label} · {p['score']} / 5", p["reason"]]
        if p["evidence"]:
            lines.append(f"> {p['evidence']}")
    lines += ["## 最小改法", r["fix"]]
    if r["caution"]:
        lines += ["## 注意", r["caution"]]
    return {"markdown": "\n\n".join(lines), "data": r}


def titles(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import titles as titles_mod
    from ...writer import WriterError

    try:
        framework = titles_mod.load_framework()
    except WriterError as exc:
        raise ToolError(str(exc)) from None
    topic_row = {"id": 0, "title": inp["topic"], "memo": ""}
    material = "\n".join([inp["topic"], inp.get("text", "")])
    error = None
    for _ in range(2):
        try:
            prompt = titles_mod.build_prompt(topic_row, framework=framework, transcript=inp.get("text", ""), skeleton="", error=error)
            r = titles_mod.parse(ask(prompt), material=material)
            break
        except WriterError as exc:
            error = str(exc)
    else:
        raise ToolError(f"连续两次没出成：{error}")
    lines = [f"{i}. **{c['title']}**{'（超过抖音字数）' if c.get('over') else ''}  \n   {c['pattern']} · {c['basis']}"
             for i, c in enumerate(r["candidates"], 1)]
    md = "## 标题候选\n\n" + "\n".join(lines)
    if r.get("tags"):
        md += "\n\n## 话题\n\n" + "、".join(r["tags"])
    return {"markdown": md, "copy": "\n".join(c["title"] for c in r["candidates"])}


def clean(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import speak

    try:
        r = speak.clean(inp["text"], ask)
    except speak.SpeakError as exc:
        raise ToolError(str(exc)) from None
    return {"markdown": f"删掉了 {r['dropped']} 个口水词，其余一个字没动。\n\n---\n\n{r['text']}", "copy": r["text"],
            "diff": diff(inp["text"], r["text"]), "dropped": r["dropped"]}


def diff(before: str, after: str) -> list[list[str]]:
    """逐字对比：[["keep", 字], ["drop", 删掉的字], ...]。口述只删不改，所以没有「加」。页面拿它把删掉的划掉。"""
    import difflib

    out: list[list[str]] = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(["keep", before[a1:a2]])
        elif a2 > a1:
            out.append(["drop", before[a1:a2]])
    return out


def _num(value: str) -> float | None:
    if not value:
        return None
    n = float(re.sub(r"[wW万]$", "", value))
    return n * 10000 if re.search(r"[wW万]$", value) else n


def teardown(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    likes, median = _num(inp.get("likes", "")), _num(inp.get("median", ""))
    if likes and median:
        facts = f"这条点赞 {likes:.0f}，账号平时一条大约 {median:.0f}，是平时的 {likes / median:.1f} 倍。"
        boom = "倍数在 3 倍以上才算真爆；不到 3 倍就写「做对了什么」，不要硬说爆。"
    elif likes:
        facts = f"这条点赞 {likes:.0f}。没有账号平时的点赞，判断不了它对这个账号来说算不算爆。"
        boom = "不要说它「爆了」，只写它做对了什么。"
    else:
        facts = "没有给数据。"
        boom = "不要说它「爆了」，只写它做对了什么。"
    md = ask(f"""你在拆一条别人的短视频，帮作者看懂它为什么有人看。{YARDSTICK}

## 数据
{facts} {boom} 引用数字只能用这里的。

## 文字稿
{inp['text']}

## 输出（Markdown，只写下面五节）
## 主线
通读全部文字稿后，一句话写出它真正想让观众带走的东西。
## 开头怎么抓人
引用开头那几句原文，说它在前 15 秒做了什么让人留下来、有没有说出主线。
## 哪里撑住了
2–4 条，每条落到原文的具体做法（例子、数据、反差、节奏），引用原文。
## 哪里散了
1–3 条：哪段在铺垫、绕远、重复或跑题（引用段落开头原文）；没有就写「没有明显散的地方」。
## 你能借什么
2–3 条能直接搬到自己内容里的做法，说清楚是结构上的做法，不是抄它的话。""")
    return {"markdown": md.strip()}


def humanize(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    out = ask(f"""把下面这段文字改得像真人写的，去掉 AI 腔。

规矩：
- 意思、事实、数字、专有名词一个都不改，不加原文没有的观点和例子；
- 去掉 AI 常见的毛病：「首先其次最后」式排比、「值得注意的是」「总而言之」「在当今时代」这类套话、每段都总结一句、过多的冒号和破折号、空洞的形容词堆叠；
- 句子长短错开，能用短句就用短句，口气自然；
- 篇幅和原文差不多，不要缩成摘要。

## 原文
{inp['text']}

只输出改好的全文，不写说明。""").strip()
    return {"markdown": out, "copy": out}


# -- 出图功能 ------------------------------------------------------------------

def _images(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("*.png")) if folder.is_dir() else []


def _ratio(path: Path) -> float | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.width / im.height
    except Exception:  # noqa: BLE001 — 量不出来就不量
        return None


def _need_ratio(paths: list[Path], want: float, label: str) -> None:
    bad = [p.name for p in paths if (r := _ratio(p)) is not None and abs(r - want) > 0.06]
    if bad:
        raise ToolError(f"出的图不是 {label}：{'、'.join(bad)}")


# 对外（邀请码）跑的任务没有 shell：图只用 Codex 自带的 image_gen 画，落在它的 generated_images 里，
# 由 public.py 在沙盒外取走（PAINT）；不靠「让它把图存进某个文件」。本机自己用走原来的 draw。
PUBLIC: dict[str, bool] = {"on": False}
PaintFn = Callable[[str, Path], tuple[list[Path], str]]


def _no_paint(prompt: str, cwd: Path) -> tuple[list[Path], str]:
    raise ToolError("这里没有接对外的出图")


PAINT: dict[str, PaintFn] = {"fn": _no_paint}

NO_SHELL = "只用 image_gen，不要运行任何命令，也不要保存、移动或检查文件。"


def _one_image(run_dir: Path, rel: str, private: str, public: str, label: str) -> Path:
    out = run_dir / rel
    out.parent.mkdir(exist_ok=True)
    if PUBLIC["on"]:
        shots, _ = PAINT["fn"](public, run_dir)
        if shots:
            shutil.copy(shots[-1], out)  # 字不对会重画，以最后一张为准
    else:
        draw(private, run_dir)
    if not out.is_file():
        raise ToolError(f"Codex 跑完了，但没有画出{label}")
    return out


def cover(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import cover as cover_mod

    lines = cover_mod.split_title(inp["title"])
    try:
        ref = cover_mod.style_refs()["3x4"]
        shutil.copy(ref, run_dir / "style-3x4.png")
        ref_line = "当前目录的 style-3x4.png 是 STYLE REFERENCE ONLY：只学视觉语言，不要用里面的人、衣服、手势或文字。\n"
    except Exception:  # noqa: BLE001 — 没有参考图就只靠文字描述
        ref_line = ""
    body = f"""用 image_gen 生成一张竖版 3:4（1086×1448）的纯文字封面，直接生成，不用等我确认。
{ref_line}
视觉语言：暖米白纸张底色，带克制的纹理和一点斜向光影；左上、右下橙红色斜角条；标题用超大、超粗、向右倾斜的紧凑黑体；标题下面一道干笔刷橙红下划线。不要人物、不要照片。

标题逐字使用，不能改字、不能加字、不能加减标点，也不要加任何英文、小标签、平台名：
{inp['title']}
分 {len(lines)} 行「{' / '.join(lines)}」，字大到几乎顶满宽度，占画面上方约 60%。从标题里挑 1–2 个最有冲击的短语（数字、反差、结果）用橙红色，其余黑色。
"""
    got = _one_image(
        run_dir, "out/cover-3x4.png",
        body + """
生成后自己看一遍：字是否逐字一致、缩到 360 像素宽时标题是否还能一眼读清。不合格就重生成，最多试 3 次。
最后只保留最好的一张，保存为 out/cover-3x4.png。不要改当前目录里的其他文件。""",
        body + f"""
生成后自己看一遍：字是否逐字一致。不合格就重新生成，最多 3 次，以最后一次生成的为准。{NO_SHELL}最后只回复「好了」。""",
        "封面")
    _need_ratio([got], 3 / 4, "3:4")
    return {"images": ["out/cover-3x4.png"]}


def _style_dna() -> str:
    """小黑配图 skill 里写画风的那一份：对外的任务没有 shell，读不了 skill，由这里读进提示词。"""
    for root in (Path.home() / ".codex/skills", Path.home() / ".claude/skills", Path.home() / ".agents/skills"):
        path = root / "ian-xiaohei-illustrations/references/style-dna.md"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text[:2500]
    return "纯白底、黑色手绘线稿，少量红、橙、蓝批注；简洁清爽，用一个有点荒诞但成立的比喻把观点讲明白。"


def _json_array(text: str) -> list[dict[str, Any]]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _public_plan(text: str, run_dir: Path, folder: Path) -> list[dict[str, Any]]:
    prompt = f"""给下面这篇中文文章配插图：最多 3 张（短文 2 张），每张用 image_gen 单独生成，横版 16:9，直接生成，不用等我确认。

画风：
{_style_dna()}

要求：
- 先选文章里最值得配图的认知锚点（概念、流程、对比、隐喻），一张图讲一个点；
- 图里的中文标注要少、要对；不要出现抖音、视频号、小红书、B 站等平台名，也不要「关注」「点赞」之类引流字样；
- {NO_SHELL}
全部画完后，最后一条回复只输出一个 JSON 数组，按图的先后顺序，每张一项：
{{"after": "这张图放在哪一段后面：那一段开头的原文，一字不差抄 12–20 个字", "caption": "一句话说这张图讲什么"}}

文章：
{text}
"""
    shots, answer = PAINT["fn"](prompt, run_dir)
    plan = _json_array(answer)
    if not shots:
        raise ToolError("一张图都没配出来")
    if not plan:
        raise ToolError("图画了，但没写清楚每张放哪")
    out = []
    for i, (shot, item) in enumerate(zip(shots, plan), 1):
        name = f"{i:02d}-fig.png"
        shutil.copy(shot, folder / name)
        out.append({"file": name, "after": str(item.get("after") or ""), "caption": str(item.get("caption") or "")})
    return out


def illustrate(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import illustrate as ill

    article = run_dir / "article.md"
    article.write_text(inp["text"].strip() + "\n", encoding="utf-8")
    folder = run_dir / ill.FOLDER
    folder.mkdir(exist_ok=True)
    if PUBLIC["on"]:
        plan = _public_plan(inp["text"].strip(), run_dir, folder)
    else:
        prompt = ill.prompt(article).replace("文章长就 5–8 张，短就 3–4 张", "最多 4 张，短文 3 张")
        draw(prompt, run_dir)
        try:
            plan = json.loads((folder / ill.PLAN).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ToolError("图画了，但没写清楚每张放哪") from None
    if not isinstance(plan, list) or not plan:
        raise ToolError("一张图都没配出来")
    text, placed = ill.insert(article.read_text(encoding="utf-8"), plan, folder)
    images = [f"{ill.FOLDER}/{name}" for name in _images(folder)]
    _need_ratio([run_dir / p for p in images], 16 / 9, "16:9")
    missed = [p for p in placed if not p.get("placed")]
    note = f"\n\n> 有 {len(missed)} 张没找到该放的段落，放在最下面。" if missed else ""
    return {"markdown": text + note, "images": images}


def library_style(style_id: str) -> dict[str, Any] | None:
    """风格画廊里他点了「通过」的生图风格（10/11 作者：已生成的全部通过，放上网站能用）。没通过的不认。"""
    from . import gallery, styles

    s = styles.get(style_id) if re.fullmatch(r"[a-z0-9-]+", style_id or "") else None
    if not s or s["function"] != "image" or not s.get("listed") or "{topic}" not in (s.get("prompt") or ""):
        return None
    mark = gallery.reviews().get(style_id)
    return s if mark and mark.get("verdict") == "approve" else None


def style(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    lib = None if inp["style"] in STYLES else library_style(inp["style"])
    if lib:
        # 和画廊样图同一份提示词，只把主题换成他的；比例跟着风格走，不卡 3:4
        body = lib["prompt"].replace("{topic}", inp["topic"]) + "\n\n直接生成，不用等我确认。不要出现平台名、logo、水印。"
        _one_image(run_dir, "out/image.png", body + "\n用 image_gen 生成一张，保存为 out/image.png，不要改当前目录里的其他文件。",
                   body + f"\n用 image_gen 生成一张。{NO_SHELL}只生成这一张，最后只回复「好了」。", "图")
        return {"images": ["out/image.png"]}
    body = f"""用 image_gen 生成一张竖版 3:4 的图，直接生成，不用等我确认。

画什么：{inp['topic']}
风格（{inp['style']}）：{STYLES[inp['style']]}

先想清楚用什么画面把这句话讲明白，再套风格。图里尽量不放字；非放不可的中文要少、要对。
不要出现平台名、logo、水印。"""
    got = _one_image(run_dir, "out/image.png",
                     body + "保存为 out/image.png，不要改当前目录里的其他文件。",
                     body + f"{NO_SHELL}只生成这一张，最后只回复「好了」。", "图")
    _need_ratio([got], 3 / 4, "3:4")
    return {"images": ["out/image.png"]}


def xhs(inp: dict[str, str], run_dir: Path) -> dict[str, Any]:
    from ... import xhs_cards

    article = run_dir / "article.md"
    # 贴进来的文字带不过来图：「![](./assets/x.png)」这种整行拿掉，只排字（10/10 样例就卡在这）
    body = re.sub(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$", "", inp["text"].strip(), flags=re.M)
    article.write_text(f"# {inp['title']}\n\n{body.strip()}\n", encoding="utf-8")
    try:
        meta = xhs_cards.make_cards(article)
    except xhs_cards.XhsError as exc:
        raise ToolError(str(exc)) from None
    images = [f"{xhs_cards.FOLDER}/{n}" for n in _images(run_dir / xhs_cards.FOLDER)]
    note = f"一共 {meta['images']} 张" + ("，超过小红书一篇 18 张的上限，要删减" if meta["over_limit"] else "")
    return {"markdown": note, "images": images}


RUNS: dict[str, Callable[[dict[str, str], Path], dict[str, Any]]] = {
    "review": review, "topic": topic, "titles": titles, "clean": clean, "teardown": teardown, "humanize": humanize,
    "cover": cover, "illustrate": illustrate, "style": style, "xhs": xhs,
}


# -- 队列：一次跑一个 ------------------------------------------------------------

def order(run_id: str) -> tuple[str, int]:
    """编号是「时间-第几个」：同一秒交了 10 个以上，按字面排 -10 会排到 -2 前面。"""
    stamp, _, n = run_id.rpartition("-")
    return (stamp, int(n) if n.isdigit() else 0)


class Queue:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.on_finish: Callable[[dict[str, Any]], None] | None = None  # 邀请码那边：失败的一次退钱

    def dir(self) -> Path:
        return self.base or root()

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"\d{8}-\d{6}-\d+", run_id):
            raise ToolError("没有这一次")
        return self.dir() / run_id

    def read(self, run_id: str) -> dict[str, Any]:
        try:
            return json.loads((self._path(run_id) / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ToolError("没有这一次") from None

    def _write(self, run: dict[str, Any]) -> None:
        folder = self._path(run["id"])
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "run.json.tmp"
        tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(folder / "run.json")

    def runs(self, owner: str | None = None) -> list[dict[str, Any]]:
        """owner：邀请码那边每个码只看自己的；本机自己用不传。"""
        out = []
        for f in sorted(self.dir().glob("*/run.json"), key=lambda f: order(f.parent.name), reverse=True):
            try:
                run = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if owner is not None and run.get("owner") != owner:
                continue
            out.append(run)
            if len(out) >= KEEP:
                break
        return out

    def submit(self, key: str, raw: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        inp = clean_input(key, raw)
        with self.lock:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            n = 1
            while (self.dir() / f"{stamp}-{n}").exists():
                n += 1
            run = {"id": f"{stamp}-{n}", "tool": key, "name": BY_KEY[key]["name"], "kind": BY_KEY[key]["kind"],
                   "input": inp, "state": "waiting", "created": now(), "result": None, "error": None, **(extra or {})}
            self._write(run)
        self.start()
        return run

    def start(self) -> None:
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, name="tools", daemon=True)
                self.thread.start()
        self.wake.set()

    def recover(self) -> None:
        """服务重启时还在「跑」的那次已经断了：标成失败，别让页面一直转。"""
        for run in self.runs():
            if run["state"] == "running":
                run.update(state="failed", error="服务重启，这一次断了，再点一次", finished=now())
                self._write(run)
        if any(r["state"] == "waiting" for r in self.runs()):
            self.start()

    def next_waiting(self) -> dict[str, Any] | None:
        waiting = [r for r in self.runs() if r["state"] == "waiting"]
        return min(waiting, key=lambda r: order(r["id"])) if waiting else None

    def run_one(self, run: dict[str, Any]) -> dict[str, Any]:
        run.update(state="running", started=now())
        self._write(run)
        try:
            result = RUNS[run["tool"]](run["input"], self._path(run["id"]))
            run.update(state="done", result=result)
        except ToolError as exc:
            run.update(state="failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 一次失败不能把队列带死
            run.update(state="failed", error=f"出错了：{exc}"[:300])
        run["finished"] = now()
        self._write(run)
        if self.on_finish:
            try:
                self.on_finish(run)
            except Exception:  # noqa: BLE001 — 退款出错不能把队列带死
                pass
        return run

    def drain(self) -> None:
        while (run := self.next_waiting()) is not None:
            self.run_one(run)

    def _loop(self) -> None:
        while True:
            self.wake.clear()
            self.drain()
            if not self.wake.wait(timeout=60):
                # 闲了一分钟就收工；和 submit 抢同一把锁，免得刚交的那次没人跑
                with self.lock:
                    if self.next_waiting() is None:
                        self.thread = None
                        return

    def file(self, run_id: str, rel: str) -> Path:
        folder = self._path(run_id).resolve()
        path = (folder / rel).resolve()
        if folder not in path.parents or not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ToolError("没有这张图")
        return path
