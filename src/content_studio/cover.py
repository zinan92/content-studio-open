"""封面：Codex 的 image_gen 按 ask-park-video 的 bold-orange 预设出竖版 3:4 和横版 4:3。

9/29 作者 看了脚本拼出来的封面：「非常不精致……人像只在中间，文字只在左边，太 raw 了。」
他以前那些好封面（「看懂加息」「给每一个业务匹配一个 FDE」）是 Codex 用 image_gen 做的：
本期视频里的一帧当唯一人物来源，上一期封面只当风格参考。skill 的 douyin-cover.md 也写明
「不要运行 Pillow 封面脚本代替图像生成」。所以这里不再排字、抠像、拼 SVG，只做三件事：
  1. 从本期最清楚的那份视频（通常是 4K 粗剪，比成片清楚）里取帧、按人脸质量挑一张；
  2. 把这一帧 + 预设的两张风格参考 + 逐字标题交给 `codex exec`，让它用 image_gen 出两张；
     10/1 起再加上 vault「形象照」里的几张自拍：视频那一帧是普通版，自拍是好看版，合起来出封面上的人；
  3. 核对两张图在、比例对，放进 final/covers/（旧的挪进 _old/），发布台按最新的认。
标题换行由这里定（只在词之间断，见 split_title），橙色关键词让 Codex 从标题里挑。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

from . import conf

FACE_QUALITY = Path(__file__).parent / "native" / "face_quality.swift"
WORD_BREAKS = Path(__file__).parent / "native" / "word_breaks.swift"
STYLE_REFS = {"3x4": "assets/covers/park-bold-orange-v1-3x4.png", "4x3": "assets/covers/park-bold-orange-v1-4x3.png"}
# 出哪几张：竖 3:4（抖音、视频号、小红书）、横 4:3（抖音横封面、公众号垫宽）、宽 16:9（YouTube、B 站，9/29 起）
SHAPES = (("竖", "cover-3x4.png", 3 / 4), ("横", "cover-4x3.png", 4 / 3), ("YouTube", "cover-16x9.png", 16 / 9))
# 10/2 起只有竖、横两张用 image_gen 画；16:9 用 ffmpeg 从横版垫出来（模糊放大的底 + 居中横版），不再多跑一轮出图
DRAWN = SHAPES[:2]
WORK = "analysis/cover-imagegen"
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
# 预览、样片、试做都是小码率的副本，不拿来取帧
NOT_SOURCE = ("预览", "样片", "试做", "excerpt", "preview")
TIMEOUT_SECONDS = 30 * 60

Runner = Callable[[str, Path], None]


class CoverError(RuntimeError):
    """说给人听的一句话。"""


# -- 排字 ---------------------------------------------------------------------

def units(text: str) -> float:
    """一行字的宽度，以字号为 1。汉字和全角标点 1，Arial Black 的拉丁字母约 0.62。"""
    total = 0.0
    for ch in text:
        if ch.isspace():
            total += 0.3
        elif ord(ch) < 0x2E80:
            total += 0.62
        else:
            total += 1.0
    return total


def split_title(title: str, *, per_line: float = 6.2, breaks: set[int] | None = None) -> list[str]:
    """没给换行时自动断：先在标点后断（「看懂加息，/看懂底层逻辑」，不拆成「看懂加息，看/懂底层逻辑」），
    一段太长再在词和词之间断，几行尽量一样长；一行约 6 个汉字宽，拉丁单词不拆开。
    9/29 以前一段太长是按宽度硬切，「99%的自媒体人都在追求流量，」切成「99%的自媒体 / 人都在追求流 / 量，」——
    词被劈开、标点单独一行。现在用本机分词找能断的地方（breaks：字符下标），再挑最匀的断法。"""
    title = title.strip()
    if breaks is None:
        breaks = word_breaks(title)
    lines: list[str] = []
    start = 0
    for ph in [p for p in re.split(r"(?<=[，。！？、：；,!?:;])", title) if p]:
        offset, start = start, start + len(ph)
        if not ph.strip():
            continue
        if lines and units(lines[-1] + ph) <= per_line:
            lines[-1] += ph
        elif units(ph) <= per_line * 1.35:
            lines.append(ph.strip())
        else:
            lines.extend(_balanced(ph, {b - offset for b in breaks if offset < b < offset + len(ph)}, per_line))
    return [l.strip() for l in lines if l.strip()]


def word_breaks(text: str) -> set[int]:
    """能断行的位置（字符下标）：词和词之间。拉丁串、数字串内部永远不算。分不了词就每个字之间都能断。"""
    latin = {i for m in re.finditer(r"[A-Za-z0-9%]+", text) for i in range(m.start() + 1, m.end())}
    every = set(range(1, len(text))) - latin
    if not shutil.which("swift"):
        return every
    try:
        out = _run(["swift", str(WORD_BREAKS), text], "分词", timeout=60)
    except (CoverError, subprocess.TimeoutExpired):
        return every
    found: set[int] = set()
    for line in out.splitlines():
        try:
            a, b = (int(v) for v in line.split("\t"))
        except ValueError:
            continue
        found.update((a, b))
    found = {i for i in found if 0 < i < len(text)} - latin
    return found or every


# 数字和后面的量词、单位不拆开：10/2「我是怎么聊一 / 个年入 200 / 万的老板的」把「一个」「200 万」劈开了
NUMERAL = "0123456789一二三四五六七八九十百千两几半"
MEASURE = "个万千百亿块元岁年月天周小时分秒次条张位倍%"
# 行首禁则：助词不能开头（「3个小时赚 / 了大部分人」）
NO_LINE_START = "了的着过吗呢吧啊么得地"


def _glued(text: str, i: int) -> bool:
    """text[i-1] 和 text[i] 之间不能断：数字（含中文数字）后面紧跟量词或单位，中间的空格也算。"""
    left = text[:i].rstrip()
    right = text[i:].lstrip()
    if not left or not right:
        return False
    return (left[-1] in NUMERAL and right[0] in MEASURE) or right[0] in NO_LINE_START


def _balanced(phrase: str, breaks: set[int], per_line: float) -> list[str]:
    """在允许的断点里挑一种断法：每行不超过上限（放不下的单个词除外），行数最少，各行宽度最接近。
    标点永远跟着前一行。"""
    cuts = sorted(i for i in breaks if 0 < i < len(phrase) and not re.match(r"[，。！？、：；,!?:;）)」”]", phrase[i])
                  and not _glued(phrase, i))
    points = [0, *cuts, len(phrase)]
    n = len(points)
    best: list[tuple[int, float, list[int]] | None] = [None] * n
    best[0] = (0, 0.0, [0])
    for j in range(1, n):
        for i in range(j):
            if best[i] is None:
                continue
            w = units(phrase[points[i]:points[j]].strip())
            if w > per_line * 1.15 and j - i > 1:
                continue
            count, cost, path = best[i]
            cand = (count + 1, cost + (per_line - w) ** 2, path + [j])
            if best[j] is None or cand[:2] < best[j][:2]:
                best[j] = cand
    path = best[-1][2] if best[-1] else list(range(n))
    return [phrase[points[a]:points[b]].strip() for a, b in zip(path, path[1:])]


def _by_width(title: str, per_line: float) -> list[str]:
    return _balanced(title, word_breaks(title), per_line)


def _run(args: list[str], what: str, timeout: int = 120) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise CoverError(f"{what}失败：{(done.stderr or done.stdout).strip()[:200]}")
    return done.stdout


def candidate_frames(video: Path, out_dir: Path, *, count: int = 6) -> list[dict[str, Any]]:
    """从成片里等距取几帧给人挑。跳过开头 hook 的前 10% 和结尾。"""
    duration = float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)], "读时长").strip())
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(count):
        at = round(duration * (0.12 + 0.76 * i / max(1, count - 1)), 1)
        path = out_dir / f"frame-{int(at):04d}.jpg"
        if not path.is_file():
            _run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-q:v", "3", str(path)], "取帧")
        frames.append({"at": at, "path": path})
    return frames


def score_frames(paths: list[Path]) -> dict[Path, float]:
    """每帧的人脸拍摄质量（macOS Vision）。一张脸才算数，没脸或好几张脸记 -1。打不了分就全是 -1。"""
    if not paths or not shutil.which("swift"):
        return {p: -1.0 for p in paths}
    try:
        out = _run(["swift", str(FACE_QUALITY), *map(str, paths)], "给帧打分", timeout=180)
    except (CoverError, subprocess.TimeoutExpired):
        return {p: -1.0 for p in paths}
    scores = {p: -1.0 for p in paths}
    for line in out.splitlines():
        parts = line.rsplit("\t", 2)
        if len(parts) == 3:
            try:
                faces, q = int(parts[1]), float(parts[2])
            except ValueError:
                continue
            scores[Path(parts[0])] = q if faces == 1 else -1.0
    return scores


def pick_frames(video: Path, out_dir: Path, *, keep: int = 6, sample: int = 12) -> list[dict[str, Any]]:
    """9/29 作者：「画面不用我自己选，你帮我选；6 选 1 也行。」多取几帧，按人脸拍摄质量留最好的几张
    （按时间排），分最高的那张标 pick。打不了分就退回等距那几张、选中间。"""
    stat = video.stat() if video.is_file() else None
    key = {"video": str(video), "size": stat.st_size if stat else 0, "mtime": round(stat.st_mtime, 3) if stat else 0, "keep": keep, "sample": sample}
    cache = out_dir / "picks.json"
    try:
        if stat is None:
            raise ValueError("no video to key the cache on")
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("key") == key and all((out_dir / f["file"]).is_file() for f in saved["frames"]):
            # 10/2：打包页每 8 秒问一次进度，每次都重取 12 帧、重打分，页面看起来像卡住
            return [{"at": f["at"], "path": out_dir / f["file"], "score": f["score"], "pick": f["pick"]} for f in saved["frames"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    frames = candidate_frames(video, out_dir, count=sample)
    scores = score_frames([f["path"] for f in frames])
    for f in frames:
        f["score"] = round(scores.get(f["path"], -1.0), 3)
    if all(f["score"] < 0 for f in frames):
        kept = frames[:: max(1, sample // keep)][:keep]
        best = kept[len(kept) // 2]
    else:
        kept = sorted(sorted(frames, key=lambda f: f["score"], reverse=True)[:keep], key=lambda f: f["at"])
        best = max(kept, key=lambda f: f["score"])
    picked = [{**f, "pick": f is best} for f in kept]
    if stat is not None:
        cache.write_text(json.dumps({"key": key, "frames": [{"at": f["at"], "file": f["path"].name, "score": f["score"], "pick": f["pick"]} for f in picked]}), encoding="utf-8")
    return picked



# -- 人物来源 ------------------------------------------------------------------

def _dimensions(video: Path) -> tuple[int, int]:
    try:
        out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                    "-of", "csv=p=0", str(video)], "读尺寸", timeout=30)
        w, h = (int(v) for v in out.strip().split(",")[:2])
        return w, h
    except (CoverError, ValueError, subprocess.TimeoutExpired):
        return 0, 0


def source_video(base: Path, final: Path) -> Path:
    """封面取帧用哪份视频：项目里分辨率最高的那份（4K 粗剪比 1080 成片清楚得多），同分辨率取成片。
    预览、样片、试做不算。9/28 那条：粗剪 2160×3840，成片 1080×1920。"""
    candidates = [final] + [p for p in sorted(base.glob("*")) if p.suffix.lower() in VIDEO_SUFFIXES
                            and p.is_file() and not any(n in p.name for n in NOT_SOURCE) and p != final]
    dims = {p: _dimensions(p) for p in candidates}
    return max(candidates, key=lambda p: (dims[p][0] * dims[p][1], p == final))


# -- 出图 ----------------------------------------------------------------------

def style_refs() -> dict[str, Path]:
    root = conf.path("skills.koubo")
    refs = {k: root / rel for k, rel in STYLE_REFS.items()}
    missing = [str(p) for p in refs.values() if not p.is_file()]
    if missing:
        raise CoverError("找不到封面风格参考图：" + "、".join(missing))
    return refs


# 10/2 作者：不要把视频那一帧和形象照拼在一起——拼出来像另一个人，竖横两张还不一样。只用视频本身那一帧。
PERSON_BLOCK = ("- person.jpg — SOLE PERSON SOURCE：本期视频里的真人截图。封面上的人必须就是他：同一张脸、同样发型、同样的衣服和配饰、同样的手势。"
                "不要换脸、不要美颜成另一个人、不要换衣服。两张封面里是同一个人、同一个状态，只是构图不同。"
                "原图里如果有烧进去的字幕框，封面上必须去掉，一个字都不能留；背景的杂物（灯、椅子、桌子）也不要。\n")


def prompt(title: str, portrait: list[str], landscape: list[str]) -> str:
    return f"""用 image_gen 生成两张视频封面（竖、横），直接生成，不用等我确认。当前目录里有：

{PERSON_BLOCK}- style-3x4.png（竖版）和 style-4x3.png（横版）— STYLE REFERENCE ONLY：只学视觉语言，不要用里面的人、衣服、手势或文字。

视觉语言（照参考图做到同样精致）：暖米白纸张底色，带克制的纹理和一点斜向光影；左上、右下橙红色斜角条；标题用超大、超粗、向右倾斜的紧凑黑体，黑字带一点白色描边感；标题下面一道干笔刷橙红下划线；人物是高清抠图，边缘干净，没有照片卡片、没有圆角框。

标题逐字使用，不能改字、不能加字、不能加减标点，也不要加任何英文、小标签、平台名：
{title}
从标题里挑 1–2 个最有冲击的短语（数字、反差、结果）用橙红色，其余黑色。

1) 竖版 3:4（1086×1448）：标题占上面约 40%，分 {len(portrait)} 行「{' / '.join(portrait)}」，字大到几乎顶满宽度；人物在下半部分，胸口以上，放大到占满整个下半屏宽度，头顶贴近笔刷下划线——人像是主角，不是缩在中间的小人。保存为 out/cover-3x4.png。

2) 横版 4:3（1448×1086）：标题压左边约 55% 宽，分 {len(landscape)} 行「{' / '.join(landscape)}」；人物压右边，胸口以上，占满右侧高度，脸大而清楚。单独构图，不要把竖版裁成横版。保存为 out/cover-4x3.png。

生成后自己看一遍：字是否逐字一致、有没有残留字幕、人是不是 person.jpg 里那个人、两张里的人是否一样、缩到 360 像素宽时标题是否还能一眼读清。不合格就重生成，最多各试 3 次。最后只保留最好的两张在 out/ 里，另写 out/receipt.json：{{"prompt": 你实际用的完整提示词, "checks": {{"text": ..., "person": ..., "no_caption": ..., "thumbnail": ...}}}}。不要改当前目录里的其他文件。
"""


def widen(landscape: Path, out: Path) -> Path:
    """4:3 横版垫成 16:9（1920×1080）：同一张图放大、模糊、压暗一点当底，原图居中不裁。"""
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(landscape), "-filter_complex",
          "[0]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=30:3,eq=brightness=-0.06[bg];"
          "[0]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0", "-frames:v", "1", str(out)], "垫 16:9", timeout=60)
    return out


def progress(base: Path) -> dict[str, int]:
    """正在出的那一轮出好了几张（看 out/ 里落地的文件，不估时间）。"""
    out = base / WORK / "out"
    return {"done": sum((out / name).is_file() for _, name, _ in DRAWN), "total": len(DRAWN)}


def progress_note(pr: dict[str, int]) -> str:
    """两张都画完后，出图程序还要收尾、再拼 16:9 换上新封面，约 1 分钟——这段时间不能说「好了 2/2」还在转。"""
    if pr["done"] >= pr["total"]:
        return "竖版、横版画好了，在收尾，1 分钟左右换上新封面"
    return f"出图中 · 竖版、横版好了 {pr['done']}/{pr['total']}"


def codex_runner(text: str, cwd: Path) -> None:
    from .illustrate import IllustrateError, codex_exec

    try:
        # stdin 必须关掉：codex exec 看到 stdin 开着会一直等输入（9/29 在终端里卡了 10 分钟）
        done = subprocess.run(codex_exec(text), cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except IllustrateError as exc:
        raise CoverError(str(exc).replace("配不了图", "出不了封面")) from exc
    except subprocess.TimeoutExpired as exc:
        raise CoverError(f"出封面超过 {TIMEOUT_SECONDS // 60} 分钟还没好，停了") from exc
    (cwd / "codex.log").write_text((done.stdout or "") + (done.stderr or ""), encoding="utf-8")
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise CoverError("出封面失败：" + " / ".join(tail)[:240])


def _ratio_ok(path: Path, want: float) -> bool:
    try:
        out = _run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], "读图", timeout=30)
        w, h = (int(v) for v in re.findall(r"pixel(?:Width|Height): (\d+)", out))
        return abs(w / h - want) < 0.03
    except (CoverError, ValueError, ZeroDivisionError, subprocess.TimeoutExpired):
        return False


def generate(base: Path, source: Path, *, at: float, title: str, runner: Runner = codex_runner) -> dict[str, str]:
    """出竖版、横版两张，放进 final/covers/，返回相对项目目录的路径。旧封面挪进 final/covers/_old/。"""
    title = title.strip()
    if not title:
        raise CoverError("先写标题：封面上的字就是标题")
    refs = style_refs()
    work = base / WORK
    if work.exists():
        shutil.rmtree(work)
    (work / "out").mkdir(parents=True)
    _run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(source), "-frames:v", "1", "-q:v", "2", str(work / "person.jpg")], "取帧")
    for key, ref in refs.items():
        shutil.copyfile(ref, work / f"style-{key}.png")
    text = prompt(title, split_title(title), split_title(title, per_line=5.5))
    (work / "prompt.md").write_text(text, encoding="utf-8")
    runner(text, work)
    made = {label: work / "out" / name for label, name, _ in DRAWN}
    for label, path in made.items():
        if not path.is_file():
            raise CoverError(f"{label}版封面没出来")
    if not all(_ratio_ok(made[label], want) for label, _, want in DRAWN):
        raise CoverError("出来的封面比例不对（要竖 3:4、横 4:3），再出一次")
    wide = work / "out" / SHAPES[2][1]
    widen(made["横"], wide)
    made[SHAPES[2][0]] = wide
    covers = base / "final" / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    old = covers / "_old"
    for f in covers.iterdir():
        if f.is_file():
            old.mkdir(exist_ok=True)
            f.rename(old / f.name)
    stem = re.sub(r'[\\/:*?"<>|]', "", title)[:40]
    result = {}
    for label, path in made.items():
        dest = covers / f"{stem}-{label}封面.png"
        shutil.copyfile(path, dest)
        result[label] = str(dest.relative_to(base))
    return result
