"""正文配图：文章写好后，用 ian-xiaohei-illustrations 配 4–8 张 16:9 白底手绘图，插到对应段落后面。

作者 9/27：公众号、研习室、X、小红书的文字版都要过一遍插图。这个 skill 靠 Codex 自带的
image_gen 出图（Claude 不出图），所以这里起一个 `codex exec`：它读文章、选几个认知锚点、
一张一张画，存进文章目录的 illustrations/，再写一份 plan.json 说每张放在哪一段后面。
插图本身由这里插回文章（`![说明](illustrations/01-xxx.png)`），codex 不碰文章。
各平台发的时候把这些本地图各自传上去（X 本来就会；公众号、研习室、小红书各自处理）。

10/7 作者：「小黑的逻辑非常好……只是把小黑换成我的形象」。个人形象文件夹里有角色（persona.py）时，
skill 照用（选锚点、发明隐喻、风格、QA），只把 xiaohei-ip.md 那个角色换成 spec.md 里的人；
每一轮配出来的图另存一份进形象库，重新配图也不丢。没有角色就和以前一样画小黑。

10/9 作者（流程板）：插图只画证据单里定了「插图」的论点（讲概念、打比方的）；定了截图、外面证据的论点不画，
那里放真东西。一个「插图」论点都没有就不画，也不算失败。没有证据单的老选题照旧整篇配。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

from .extras.positioning import persona

FOLDER = "illustrations"
PLAN = "plan.json"
SKILL = "ian-xiaohei-illustrations"
IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\(" + FOLDER + r"/[^)\s]+\)\s*$")
TIMEOUT_SECONDS = 45 * 60

Runner = Callable[[str, Path], None]


class IllustrateError(RuntimeError):
    """Shown to 作者 as-is."""


def codex_bin() -> str:
    for cand in ("/opt/homebrew/bin/codex", shutil.which("codex") or ""):
        if cand and Path(cand).is_file():
            return cand
    raise IllustrateError("这台机器上找不到 codex，配不了图")


def codex_exec(text: str) -> list[str]:
    """出图都走这一条命令：模型写死在 profile 的 codex.model（默认 gpt-6.1-sol），不吃本机 Codex 的默认值。
    10/1：本机默认被改成了一个 ChatGPT 账号用不了的模型，出封面、配插图全挂了。"""
    from . import conf

    return [codex_bin(), "exec", "-m", conf.value("codex.model"), "--skip-git-repo-check", "-s", "workspace-write", text]


# 角色怎么画进小黑那种白纸草图里：10/7 线稿和手办两种都试过，作者 选了手办（B）
DRAW_AS = ("{name} 本人保持 fullbody.png 那种手办质感（哑光手绘厚涂 3D、柔和体积光），像一个手办被放进白纸草图里；"
           "他手里和身边的道具、背景、批注仍然是 skill 的黑色手绘线稿。")


def cast(name: str) -> str:
    """把 skill 里的小黑换成固定角色：skill 的其余部分照用。"""
    ref = persona.STAGE
    return f"""
角色：不要小黑。照用这个 skill 的工作流、style-dna.md、composition-patterns.md、qa-checklist.md 和 prompt-template.md 的其余部分，
但忽略 xiaohei-ip.md 和 prompt-template.md 里描述小黑的那一段，主角换成固定角色 {name}：
- 先读 {ref}/spec.md。它管的是「这个人是谁」：脸、发型、身材、衣服颜色、胸口字样、身上不许出现的配件，这些严格照它。
  参考图 {ref}/reference.png 是主参考，{ref}/sheet.png 看侧面和背面，{ref}/fullbody.png 看本人长相。
- spec.md 里关于背景和「不要文字、标注」的规定只管它自己的设定图，这里不适用：
  除了 {name} 本人，整张图怎么画、背景、颜色、中文手写批注，一律照 skill 的 style-dna（纯白底、手绘线稿、少量红/橙/蓝批注）。
  「不要文字」只是说 {name} 身上除了胸口字样不加别的字。
- {DRAW_AS.format(name=name)}
- 小黑的那条规矩保留：{name} 必须是核心动作的执行者，去掉他隐喻就不成立；冷静、认真地做一件有点荒诞但成立的事，不卖萌。
- QA 时多查一条：每张里的 {name} 是不是同一个人、衣服和字样对不对。
"""


def only(sheet: dict[str, list[str]] | None) -> str:
    """证据单给的范围：只画哪几个论点、哪几个不画。"""
    if not sheet:
        return ""
    draw = "\n".join(f"  - {t}" for t in sheet.get("draw") or [])
    skip = "\n".join(f"  - {t}" for t in sheet.get("skip") or [])
    return (f"- 只给讲下面这几个论点的段落配图（它们是讲概念、打比方，没有真东西能证明）：\n{draw}\n"
            + (f"- 讲下面这几个论点的段落不要配图，那里会放真截图、真证据：\n{skip}\n" if skip else "")
            + "- 张数跟着上面能画的论点走，一个论点最多 2 张。\n")


def prompt(article: Path, character: dict[str, str] | None = None, skill: str | None = None,
           sheet: dict[str, list[str]] | None = None) -> str:
    """skill：这个人自己的配图 skill（<slug>-ip-illustrations），角色写在 skill 里，不用再 cast()。"""
    if skill:
        head = f"""用 ${skill} 给这篇中文文章配图，并直接生成（不用等我确认）。

文章：{article.name}（就在当前目录）
角色参考图另外复制了一份在当前目录的 {persona.STAGE}/。形象库（gallery）由工作台存，你不用存。
"""
    else:
        head = f"""用 ${SKILL} 给这篇中文文章配图，并直接生成（不用等我确认）。

文章：{article.name}（就在当前目录）
{cast(character["name"]) if character else ""}"""
    return head + f"""
要求：
- 按 skill 的方法选认知锚点，文章长就 5–8 张，短就 3–4 张；每张用 image_gen 单独生成，16:9。
{only(sheet)}- 图里的中文标注要少、要对，不要出现抖音、视频号、小红书、B 站等平台名，也不要「关注」「点赞」之类引流字样。
- 生成的图保存到当前目录的 {FOLDER}/ 下，按顺序命名 01-英文短名.png、02-英文短名.png ……
- 最后写 {FOLDER}/{PLAN}：JSON 数组，每张一项
  {{"file": "01-xxx.png", "after": "这张图放在哪一段后面：那一段开头的原文，一字不差抄 12–20 个字", "caption": "一句话说这张图讲什么"}}
- 不要改 {article.name}，不要改别的文件{"（" + persona.STAGE + "/ 里的参考图只读）" if character else ""}。
"""


def codex_runner(text: str, cwd: Path) -> None:
    try:
        # stdin 关掉：codex exec 看到 stdin 开着会一直等输入（封面那边 9/29 卡过）
        done = subprocess.run(codex_exec(text), cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise IllustrateError(f"配图超过 {TIMEOUT_SECONDS // 60} 分钟还没画完，停了") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise IllustrateError("配图失败：" + " / ".join(tail)[:240])


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`>#\-]+", "", text or "")


def strip_images(markdown: str) -> str:
    """去掉上一轮插进去的配图行（重新配图时先清掉）。"""
    lines = [l for l in markdown.splitlines() if not IMAGE_LINE.match(l.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def insert(markdown: str, plan: list[dict[str, Any]], folder: Path) -> tuple[str, list[dict[str, Any]]]:
    """按 plan 把图插到对应段落后面；对不上的段落不插，报出来。返回新文章和每张的结果。"""
    paras = re.split(r"\n\s*\n", strip_images(markdown).strip())
    after: dict[int, list[str]] = {}
    placed = []
    for item in plan:
        name = Path(str(item.get("file") or "")).name
        if not name or not (folder / name).is_file():
            placed.append({**item, "placed": False, "why": "图没画出来"})
            continue
        anchor = _norm(str(item.get("after") or ""))[:16]
        hit = next((i for i, p in enumerate(paras) if anchor and _norm(p).startswith(anchor)), None)
        if hit is None:
            hit = next((i for i, p in enumerate(paras) if anchor and anchor in _norm(p)), None)
        if hit is None:
            placed.append({**item, "file": name, "placed": False, "why": "找不到它该放的那一段"})
            continue
        caption = str(item.get("caption") or "").replace("]", "）").replace("[", "（").strip()
        after.setdefault(hit, []).append(f"![{caption}]({FOLDER}/{name})")
        placed.append({**item, "file": name, "placed": True})
    out = []
    for i, p in enumerate(paras):
        out.append(p)
        out.extend(after.get(i, []))
    return "\n\n".join(out).rstrip() + "\n", placed


def illustrate(article: Path, *, runner: Runner = codex_runner, sheet: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """sheet：证据单给的范围（draw 要画的论点、skip 不画的）；None 是没有证据单，整篇配。"""
    if not article.is_file():
        raise IllustrateError("还没有文章")
    folder = article.parent / FOLDER
    if sheet is not None and not sheet.get("draw"):
        # 整篇都有真东西：不画，上一轮插进去的 AI 图也拿掉
        article.write_text(strip_images(article.read_text(encoding="utf-8")), encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        return {"images": [], "skipped": [], "none": True}
    if folder.exists():
        old = folder.parent / f"{FOLDER}.old"
        shutil.rmtree(old, ignore_errors=True)
        folder.rename(old)  # 上一轮的图挪开，不和这一轮混
    folder.mkdir(parents=True)
    character = persona.character()
    if character:
        persona.stage(article.parent)
    try:
        runner(prompt(article, character, persona.skill(), sheet), article.parent)
    finally:
        persona.unstage(article.parent)
    try:
        plan = json.loads((folder / PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IllustrateError("图画了，但没写清楚每张放哪（plan.json 缺失或坏了）") from exc
    if not isinstance(plan, list) or not plan:
        raise IllustrateError("一张图都没配出来")
    text, placed = insert(article.read_text(encoding="utf-8"), plan, folder)
    article.write_text(text, encoding="utf-8")
    shutil.rmtree(folder.parent / f"{FOLDER}.old", ignore_errors=True)
    if character:
        persona.archive(article, folder, placed)  # 画出来没插上的也存
    return {"images": [p for p in placed if p.get("placed")], "skipped": [p for p in placed if not p.get("placed")]}


def state(article: Path | None) -> dict[str, Any]:
    if article is None or not article.is_file():
        return {"images": [], "count": 0}
    folder = article.parent / FOLDER
    text = article.read_text(encoding="utf-8")
    used = re.findall(r"!\[([^\]]*)\]\(" + FOLDER + r"/([^)\s]+)\)", text)
    return {"images": [{"file": f, "caption": c} for c, f in used if (folder / f).is_file()], "count": len(used)}
