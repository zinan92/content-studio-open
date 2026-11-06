"""口播 Step 3–4：把成片变成一张能标 Hook 的工作台。

这两步以前要开终端：跑 whisper 出字幕，跑 build_worktable.py 出 HTML，在浏览器里标完
导出 JSON 落进下载文件夹，再手动拷回项目的 analysis/worktable.json。

这里把这三段接起来。工作台不重做那张 HTML——`ask-park-video` 的模板已经在用了，
重做一张只会和后面 14 步的格式对不上。它只负责：找到成片、跑转写、生成那张表、
把表开在页面里、把结果直接写回项目目录。
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .writer import cli_write

EXPORTS_ENV = "CONTENT_STUDIO_JIANYING_EXPORTS"
EXPORTS_DIRNAME = "剪映导出"
SKILL_ENV = "CONTENT_STUDIO_KOUBO_SKILL"
DEFAULT_SKILL = Path("~/.claude/skills/park-video-v2")  # 10/21 起：标 Hook 的表、切 Hook、封面参考都在这里
WHISPER_MODEL_ENV = "CONTENT_STUDIO_WHISPER_MODEL"
DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# whisper 转中文默认不给标点，而 build_worktable 是靠标点断句的——没标点整篇 12 分钟
# 会变成「一个句子」，那张表就成了一整坨。
#
# 试过给 initial_prompt 让它自己断：标点是出来了，但转写质量塌了——706 条字幕变成 34 条，
# 还出了乱码。所以改走 skill 本来就留好的那条路：转写不加 prompt（时间轴准），标点用本机
# 模型单独补一遍，再用 `map --srt ... --text ...` 把两边对齐。map 自带漂移守卫，
# 补标点时顺手改了字它会拒绝出活。
PUNCTUATE_COMMAND_ENV = "CONTENT_STUDIO_PUNCTUATE_CMD"
DEFAULT_PUNCTUATE_COMMAND = (
    "claude -p --model sonnet --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)
# 一句话平均超过这么多秒，基本可以断定标点没出来。
MAX_SECONDS_PER_SENTENCE = 25
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
# 成片和它的只读备份放一起时，优先挑大的：粗剪通常比备份长、比备份大。
SKIP_DIRS = {"part-a-hook", "part-b-body", "final", "renders", "tmp", "node_modules", "subtitles"}


class KouboError(RuntimeError):
    """说给 作者 看的一句话，不是堆栈。"""


def skill_dir() -> Path:
    return Path(os.environ.get(SKILL_ENV) or DEFAULT_SKILL).expanduser()


def find_video(base: Path) -> Path | None:
    """项目根目录下最大的那个视频文件。中间产物目录不看。"""
    found = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES]
    for sub in base.iterdir():
        if sub.is_dir() and sub.name not in SKIP_DIRS and not sub.name.startswith("."):
            found += [p for p in sub.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES]
    return max(found, key=lambda p: p.stat().st_size) if found else None


def find_srt(base: Path) -> Path | None:
    """先看约定位置，再看根目录——剪映导出的 SRT 通常和视频并排放着。"""
    fixed = base / "subtitles" / "source.srt"
    if fixed.is_file():
        return fixed
    loose = sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".srt")
    final = base / "final"
    if not loose and final.is_dir():
        # 剪映导出成片时勾上「字幕 SRT」，它就和成片一起落在 final/ 里
        loose = sorted(p for p in final.iterdir() if p.is_file() and p.suffix.lower() == ".srt")
    return loose[0] if loose else None


def state(base: Path) -> dict[str, Any]:
    """这个项目现在有什么、缺什么。前端拿它决定显示哪颗按钮。"""
    video = find_video(base)
    srt = find_srt(base)
    sentences = base / "subtitles" / "transcript.sentences.json"
    worktable = base / "analysis" / "worktable.html"
    exported = base / "analysis" / "worktable.json"
    return {
        "video": {"name": video.name, "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
        "srt": {"name": srt.name, "at_fixed_path": srt == base / "subtitles" / "source.srt"} if srt else None,
        "sentences": sentences.is_file(),
        "worktable": worktable.is_file(),
        "exported": exported.is_file(),
    }


def transcribe(video: Path, base: Path, *, model: str | None = None) -> Path:
    """本机跑一遍，出 subtitles/source.srt。

    没有字幕时才跑，而且要 作者 先点确认——15 分钟的片子要跑两三分钟，
    不该在他不知情的时候占住机器。
    """
    from . import icloud

    try:
        icloud.ensure_local(video)
    except icloud.NotLocalError as exc:
        raise KouboError(str(exc)) from None
    try:
        import mlx_whisper
        from mlx_whisper.writers import get_writer
    except ImportError as exc:
        raise KouboError("这台机器上没有 mlx-whisper，装一下或者自己导一份 SRT 放进项目目录") from exc
    out = base / "subtitles"
    out.mkdir(parents=True, exist_ok=True)
    # word_timestamps 是为了镜头对点：没有它，转写只有「这一整段 505.96–570.38 秒」，
    # 想把画面卡在段中间某句话上只能按字数插值猜——真发生过，猜偏了 12 秒。
    result = mlx_whisper.transcribe(
        str(video), path_or_hf_repo=model or os.environ.get(WHISPER_MODEL_ENV) or DEFAULT_WHISPER_MODEL,
        language="zh", verbose=None, word_timestamps=True,
    )
    # writer 的第二个参数是**文件名**，不是路径：它做的是 Path(output_dir) / output_name。
    # 传绝对路径的话绝对路径会直接盖掉 output_dir，字幕就落到视频旁边去了。
    get_writer("srt", str(out))(result, "source", {"max_line_width": None, "max_line_count": None, "highlight_words": False})
    target = out / "source.srt"
    if not target.is_file():
        raise KouboError(f"转写跑完了但没找到字幕文件：{target}")
    write_words(result, out / "words.json")
    return target


def write_words(result: dict[str, Any], path: Path) -> int:
    """每个词一行真实时间。镜头要卡在哪句话上，查这张表，不要插值。"""
    import json

    words = [
        {"w": (w.get("word") or "").strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
        for seg in (result.get("segments") or [])
        for w in (seg.get("words") or [])
        if (w.get("word") or "").strip() and w.get("start") is not None and w.get("end") is not None
    ]
    path.write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    return len(words)


def find_quote(words: list[dict[str, Any]], quote: str) -> dict[str, float] | None:
    """这句话真正是第几秒说的。按去标点后的字符流匹配，返回首末词的真实时间。"""
    clean = re.sub(r"[^\w]", "", quote)
    if not clean:
        return None
    flat, index = [], []
    for i, w in enumerate(words):
        for ch in re.sub(r"[^\w]", "", w["w"]):
            flat.append(ch)
            index.append(i)
    at = "".join(flat).find(clean)
    if at < 0:
        return None
    first, last = words[index[at]], words[index[min(at + len(clean) - 1, len(index) - 1)]]
    return {"start": first["start"], "end": last["end"]}


def srt_text(srt: Path) -> str:
    """把 SRT 拆成纯文本，一条一行。给补标点用。"""
    lines = []
    for block in re.split(r"\n\s*\n", srt.read_text(encoding="utf-8").strip()):
        rows = [r for r in block.splitlines() if r.strip()]
        body = [r for r in rows if not r.strip().isdigit() and "-->" not in r]
        if body:
            lines.append("".join(body).strip())
    return "\n".join(lines)


def punctuate(text: str, *, write_fn: Any = None) -> str:
    """只加标点，一个字都不许改——map 的漂移守卫会核对，改了就出不了活。"""
    prompt = (
        "下面是一段中文口播的转写，whisper 没给标点。请只做一件事：加上标点符号和分段。\n\n"
        "**一个字都不许改**：不要改错别字，不要删语气词和口误，不要合并或拆开句子的内容，"
        "不要加任何原文没有的字。只在字与字之间插入 。，？！、 和换行。\n"
        "直接输出加好标点的正文，不要任何说明。\n\n---\n\n" + text
    )
    fn = write_fn or (lambda p: cli_write(p, command=os.environ.get(PUNCTUATE_COMMAND_ENV) or DEFAULT_PUNCTUATE_COMMAND, timeout=900))
    out = (fn(prompt) or "").strip()
    if not out:
        raise KouboError("补标点没有返回内容")
    return out


def build_worktable(base: Path, *, srt: Path, skill: Path | None = None, python: str | None = None, write_fn: Any = None) -> Path:
    """跑 park-video-v2 的 build_worktable.py（10/21 从 ask-park-video 搬过去）。工作台不重写这张表。"""
    script = (skill or skill_dir()) / "scripts" / "build_worktable.py"
    if not script.is_file():
        raise KouboError(f"找不到 park-video-v2 的 build_worktable.py：{script}")
    from . import icloud

    try:
        icloud.ensure_local(srt)
    except icloud.NotLocalError as exc:
        raise KouboError(str(exc)) from None
    exe = python or shutil.which("python3") or "python3"
    sentences = base / "subtitles" / "transcript.sentences.json"
    out = base / "analysis" / "worktable.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    corrected = base / "subtitles" / "transcript.corrected.txt"
    if not corrected.is_file():
        corrected.write_text(punctuate(srt_text(srt), write_fn=write_fn) + "\n", encoding="utf-8")
    mapped = [exe, str(script), "map", "--srt", str(srt), "--text", str(corrected), "-o", str(sentences)]
    _run(mapped)
    # 先验断句，再出 HTML——反过来的话守卫拦下了，一张没法用的表还是留在了盘上。
    _guard_sentences(sentences)
    _run([exe, str(script), "html", str(sentences), "-o", str(out)])
    return out


def _run(args: list[str]) -> None:
    done = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if done.returncode != 0:
        raise KouboError(f"生成工作台失败：{(done.stderr or done.stdout).strip()[:300]}")


def _guard_sentences(path: Path) -> None:
    """断句失败要当场说出来，不能交一张一整坨的表出去。

    这是真发生过的：whisper 不给标点，12 分钟切成 1 个句子，表看起来生成成功了，
    打开才发现没法标。
    """
    import json

    try:
        rows = (json.loads(path.read_text(encoding="utf-8")).get("transcript")) or []
    except (OSError, ValueError):
        return
    if not rows:
        raise KouboError("断句结果是空的，字幕可能有问题")
    span = max((r.get("end_hint") or 0) for r in rows)
    if span and span / len(rows) > MAX_SECONDS_PER_SENTENCE:
        raise KouboError(
            f"断句失败：{span / 60:.0f} 分钟只切出 {len(rows)} 句，字幕多半没有标点。"
            "删掉 subtitles/source.srt 重新转写，或者自己放一份带标点的 SRT 进去。"
        )


# 把「保存到项目」挂到那张表上。只依赖模板里的全局 payload()——它变了就退回原来的
# 导出按钮，不会把整张表搞坏。
SAVE_SCRIPT = """
<script>
(function () {
  if (typeof payload !== 'function') return;
  var bar = document.getElementById('btnExport');
  if (!bar || !bar.parentNode) return;
  var b = document.createElement('button');
  b.textContent = '保存到项目';
  b.id = 'btnSaveToProject';
  b.style.cssText = 'margin-left:8px';
  b.onclick = async function () {
    b.disabled = true;
    b.textContent = '保存中…';
    try {
      var r = await fetch(%(url)s, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Content-Studio': '1' },
        body: JSON.stringify({ text: JSON.stringify(payload(), null, 2), filename: 'worktable.json', overwrite: true }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      b.textContent = '已存进 analysis/worktable.json';
    } catch (e) {
      b.textContent = '保存失败：' + e.message;
      b.disabled = false;
    }
  };
  bar.parentNode.insertBefore(b, bar.nextSibling);
})();
</script>
"""


def worktable_html(base: Path, *, save_url: str) -> str:
    path = base / "analysis" / "worktable.html"
    if not path.is_file():
        raise KouboError("还没有生成工作台")
    import json

    return path.read_text(encoding="utf-8") + SAVE_SCRIPT % {"url": json.dumps(save_url)}


# -- 剪映导出 ---------------------------------------------------------------
# 剪映不往项目目录里导，它导到自己那个文件夹，而且文件名全是日期（「9月22日.mp4」、
# 「9月17日(2).mp4」）。所以不能靠名字认，得把时长和大小摆出来让人挑。
# 带字幕导出时它会建一个同名文件夹，mp4 和 srt 放在里面。


def exports_root(video_root: Path) -> Path:
    """默认是项目目录的兄弟：视频/exports 旁边的 视频/剪映导出。"""
    raw = os.environ.get(EXPORTS_ENV)
    return Path(raw).expanduser() if raw else video_root.parent / EXPORTS_DIRNAME


def _duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        done = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        return round(float(done.stdout.strip()), 1) if done.returncode == 0 and done.stdout.strip() else None
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def latest_export(root: Path) -> dict[str, Any] | None:
    """剪映导出里最新的那一条。

    作者：「就拿最新的就好了，命名用来校对。」——文件名全是日期（9月22日.mp4），
    认不出内容，所以名字和时长是给他核对用的，不是给他挑的。
    """
    rows = recent_exports(root, limit=1)
    return rows[0] if rows else None


def recent_exports(root: Path, *, limit: int = 8, durations: bool = True) -> list[dict[str, Any]]:
    """剪映导出里最近的几条，新的在前。带字幕的会标出来。

    剪映记着上次导到哪，所以新的一条常常落在上一条的文件夹里面（10/7 那条在「10月5日/10月7日 (1)/」），
    只看一层就看不见。往下翻几层，每个视频单算一条，按修改时间排。
    """
    if not root.is_dir():
        return []
    found = [(video, srt_for(video, root)) for video in _videos_under(root, depth=EXPORT_DEPTH)]
    found.sort(key=lambda pair: pair[0].stat().st_mtime, reverse=True)
    rows = []
    for video, srt in found[:limit]:
        stat = video.stat()
        rows.append({
            "path": str(video),
            "name": video.name,
            "folder": video.parent.name if video.parent != root else None,
            "mb": round(stat.st_size / 1_048_576, 1),
            "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="minutes"),
            "seconds": _duration(video) if durations else None,
            "srt": srt.name if srt else None,
        })
    return rows


EXPORT_DEPTH = 4


def _files_under(root: Path, depth: int) -> list[Path]:
    """root 往下 depth 层里的文件。点开头的、App 包（xx.photoslibrary 这种带后缀的目录）不进。"""
    out: list[Path] = []
    try:
        items = list(root.iterdir())
    except OSError:
        return out
    for item in items:
        if item.name.startswith("."):
            continue
        if item.is_file():
            out.append(item)
        elif item.is_dir() and depth > 0 and not item.suffix:
            out += _files_under(item, depth - 1)
    return out


def _videos_under(root: Path, *, depth: int) -> list[Path]:
    return [p for p in _files_under(root, depth) if p.suffix.lower() in VIDEO_SUFFIXES]


def srt_for(video: Path, root: Path | None = None) -> Path | None:
    """和视频配对的字幕：同名的 .srt；剪映单独建的文件夹里只有这一个视频、一份 .srt 时就是它。"""
    same = video.with_suffix(".srt")
    if same.is_file():
        return same
    if root is not None and video.parent == root:
        return None
    files = [p for p in video.parent.iterdir() if p.is_file() and not p.name.startswith(".")]
    srts = [p for p in files if p.suffix.lower() == ".srt"]
    alone = sum(p.suffix.lower() in VIDEO_SUFFIXES for p in files) == 1
    return srts[0] if alone and len(srts) == 1 else None


def locate(roots: list[tuple[Path, int]], name: str, size: int) -> Path | None:
    """浏览器拖进来的文件只有名字和大小、没有路径，按这两样在这几个目录里找回原文件。

    同名同大小还撞上好几个时拿最新的那个。找不到就是 None，不去猜。
    """
    hits = [p for root, depth in roots if root.is_dir()
            for p in _files_under(root, depth) if p.name == name and p.stat().st_size == size]
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def adopt(video: Path, base: Path, *, srt: Path | None = None) -> dict[str, Any]:
    """把选中的导出拷进项目目录。

    同一块 APFS 盘上 `cp -c` 是 clone，秒级、不占额外空间。保留日期后缀，
    否则项目里躺着一个叫「粗剪.mp4」的东西，回头对不上是哪一次导的。
    """
    if not video.is_file():
        raise KouboError(f"找不到这个文件：{video}")
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"粗剪-{video.stem}{video.suffix}"
    _clone(video, target)
    out: dict[str, Any] = {"video": target.name}
    if srt and srt.is_file():
        (base / "subtitles").mkdir(exist_ok=True)
        _clone(srt, base / "subtitles" / "source.srt")
        out["srt"] = "subtitles/source.srt"
    return out


def _clone(src: Path, dst: Path) -> None:
    done = subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True, text=True, timeout=600)
    if done.returncode != 0:
        # 不同卷、或者不是 APFS：clone 不成就老老实实拷。
        shutil.copy2(src, dst)


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}


def _contract(base: Path) -> tuple[Path, dict[str, Any]]:
    import json

    path = base / "project.json"
    if not path.is_file():
        raise KouboError("还没初始化，先写 project.json")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _save_contract(path: Path, data: dict[str, Any]) -> None:
    import json

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _take_video(source: Path | None, target: Path) -> None:
    if source is None:
        return
    from . import icloud

    source = source.expanduser()
    if not source.is_file() or source.suffix.lower() not in VIDEO_SUFFIXES:
        raise KouboError(f"不是视频文件：{source}")
    icloud.ensure_local(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    _clone(source, target)


def mark_external(base: Path, what: str, *, source: Path | None = None) -> dict[str, Any]:
    """记下「这部分在外面做完了」：Hook（5/7/8/9）或整条（1–14）。

    9/22 那条 Hook 是 Codex 剪的、成片也在 Codex 目录里，工作台却一直停在 Step 2。
    步骤标 external（不是 pass），看得出不是这里的机器做的。
    """
    from . import release

    if what == "all" and not (base / "project.json").is_file():
        # 新建的目录没有 project.json（不走 14 步）：剪映粗剪就是成片，拷进 final/ 就能去打包。
        if source is not None:
            _take_video(source, base / "final" / source.expanduser().name)
        elif not release.find_video(base):
            rough = find_video(base)
            if rough is None:
                raise KouboError("项目里还没有粗剪：先把剪映导出放进项目")
            _take_video(rough, base / "final" / rough.name)
        if not release.find_video(base):
            raise KouboError("final/ 里还没有成片：先告诉我成片在哪")
        return {"steps": []}
    path, data = _contract(base)
    status = data.setdefault("step_status", {})
    approvals = data.setdefault("approvals", {})
    if what == "hook":
        target = base / "part-a-hook" / "video.mp4"
        _take_video(source, target)
        if not target.is_file():
            raise KouboError("先告诉我剪好的 Hook 在哪（一个视频文件）")
        steps = list(HOOK_STEPS)
        approvals["hook"] = "external"
    elif what == "all":
        if source is not None:
            _take_video(source, base / "final" / source.expanduser().name)
        if not release.find_video(base):
            raise KouboError("final/ 里还没有成片：先告诉我成片在哪")
        steps = list(range(1, 15))
        approvals.setdefault("final", "external")
    else:
        raise KouboError("只能记 Hook 或整条")
    for n in steps:
        if str(status.get(str(n)) or "").lower() not in ("pass", "approved"):
            status[str(n)] = "external"
    _save_contract(path, data)
    return {"steps": steps}


def set_visual_target(base: Path, percent: float, maximum: float | None = None) -> float:
    """动效占正文的比例。作者 给一个数或一个范围（9/29：「30 到 40，可以变」），挑哪几处机器定。
    visual_coverage_target 存下限（老项目只有这一个数），visual_coverage_max 存上限；只给一个数时删掉上限。"""
    if not 0 <= percent <= 100 or (maximum is not None and not percent <= maximum <= 100):
        raise KouboError("比例要在 0 到 100 之间，范围要从小到大")
    path, data = _contract(base)
    data["visual_coverage_target"] = round(percent / 100, 3)
    if maximum is None or maximum == percent:
        data.pop("visual_coverage_max", None)
    else:
        data["visual_coverage_max"] = round(maximum / 100, 3)
    _save_contract(path, data)
    return data["visual_coverage_target"]


# -- Step 1：project.json ---------------------------------------------------
# 没有它，工作台按「旧版目录」识别：14 步进度算不出来，「开始跑」也会被拒，
# 于是标完 Hook 之后没有任何一条路通向动效。四个 preset 的 id 从 skill 目录里读，
# 不写死——skill 换了默认值，这里跟着变。

PRESET_KINDS = (("media", "media"), ("audio", "audio"), ("caption_style", "captions"), ("caption_layout", "captions"))


def _is_override(path: Path) -> bool:
    """spec 选中才用的覆盖预设（竖屏、剪映已烧字幕…）不能被当成默认值。"""
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") == "override"
    except (OSError, ValueError):
        return False


def default_presets(skill: Path | None = None) -> dict[str, str]:
    root = (skill or skill_dir()) / "presets"
    out: dict[str, str] = {}
    for key, folder in PRESET_KINDS:
        files = [f for f in sorted((root / folder).glob("*.json")) if not _is_override(f)] if (root / folder).is_dir() else []
        # caption_style 和 caption_layout 同在 captions/ 下，靠名字里的 layout 区分。
        wanted = [f for f in files if ("layout" in f.stem) == (key == "caption_layout")] if folder == "captions" else files
        if not wanted:
            raise KouboError(f"skill 的 presets/{folder} 里没有可用的 {key} preset")
        out[key] = wanted[0].stem
    return out


def init_project(base: Path, *, skill: Path | None = None) -> dict[str, Any]:
    """写一份 project.json，让这个目录能按 14 步跑。已经有了就不动它。"""
    import json

    path = base / "project.json"
    if path.is_file():
        raise KouboError("project.json 已经有了，不覆盖")
    data = {
        "schema_version": "ask-park-video/project/v1",
        "workflow": "ask-park-video/v1",
        "current_step": 1,
        "current_gate": None,
        "presets": default_presets(skill),
        "step_status": {},
        "approvals": {"hook": None, "visual_spec": None, "final": None},
        "evidence": {},
        "blocked_reason": None,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


HOOK_STEPS = (5, 7, 8, 9)

# -- 剪辑规格：作者 从剪映导出后手动选，工作流照做、不再判断（skill 的 作者's manual spec）--
SPEC_OPTIONS: dict[str, tuple[str, ...]] = {
    "hook": ("yes", "no"),
    "captions": ("generate", "burned_in"),
    "layout": ("split-4x3", "vertical-full-overlay"),
    "bgm": ("none", "light"),
    "sfx": ("none", "low", "mid", "high"),  # 音效：不加 / 低 / 中 / 高（作者 9/29）
}
SPEC_PRESETS = {
    ("captions", "burned_in"): ("caption_style", "park-caption-burned-in-v1"),
    ("layout", "vertical-full-overlay"): ("media", "park-talking-head-9x16-full-v1"),
}


def set_spec(base: Path, changes: dict[str, Any], *, skill: Path | None = None) -> dict[str, Any]:
    """记下 作者 选的规格，并把对应的 preset 换好。没选的项保持原样。"""
    bad = {k: v for k, v in changes.items() if k not in SPEC_OPTIONS or v not in SPEC_OPTIONS[k]}
    if bad:
        raise KouboError(f"不认识的规格：{bad}")
    path, data = _contract(base)
    spec = data.setdefault("spec", {})
    presets = data.setdefault("presets", {})
    defaults = default_presets(skill)
    for key, value in changes.items():
        spec[key] = value
        for (k, v), (preset_key, preset_id) in SPEC_PRESETS.items():
            if k == key:
                presets[preset_key] = preset_id if value == v else defaults[preset_key]
        if key == "hook":
            status = data.setdefault("step_status", {})
            approvals = data.setdefault("approvals", {})
            if value == "no":
                for n in HOOK_STEPS:
                    status[str(n)] = "skipped"
                approvals["hook"] = "skipped"
            else:
                for n in HOOK_STEPS:
                    if status.get(str(n)) == "skipped":
                        status.pop(str(n))
                if approvals.get("hook") == "skipped":
                    approvals["hook"] = None
    _save_contract(path, data)
    return spec


def skip_hook(base: Path) -> list[int]:
    """把 Hook 那四步记成 skipped。

    Hook 存在的唯一理由是补救一个不够抓人的开头。骨架已经给了暴论候选，录的时候
    第一句就说它，这四步就不必做——但合同里得写下来，否则进度永远停在 Step 5。
    """
    import json

    path = base / "project.json"
    if not path.is_file():
        raise KouboError("还没初始化，先写 project.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    status = data.setdefault("step_status", {})
    for n in HOOK_STEPS:
        status[str(n)] = "skipped"
    data.setdefault("approvals", {})["hook"] = "skipped"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return list(HOOK_STEPS)
