"""付息稿：一勾式骨架后面的一步（10/2 作者）。

作者：「你可以把它想象成一个 Treasury：用户从我这买了 Treasury……我每 10 秒钟都要给他一些
interest（新判断、原因、案例证明），到了最后的时候，我再给他本金，也就是给他最一开始预期能够听到的东西。」
骨架只给论点和证据；付息稿把它排成一条时间线：开头发债（说清本金）、大约每 10 秒付一次息、最后兑付本金，
再附一本利息账本、删掉了什么、拍之前要对清楚什么。

规则不在代码里，在 Anna 的工作流文件「付息稿.md」（和「一勾式骨架.md」放一起，作者 随时能改）。
这里只核对格式：有本金、有账本、时间线够长、没有哪一行超过 15 秒还不付息。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from . import writing_rules

from .identity import author
from .judge import JudgeLoginError
from .outline import frame_sections, workflows_dir
from .writer import ARTICLE_BLOCK, DEFAULT_DRAFTS_DIR, WriteFn, WriterError, cli_write, topic_sources

COUPON_COMMAND_ENV = "CONTENT_STUDIO_COUPON_CMD"
FRAMEWORK_FILE = "付息稿.md"
LABEL = "密度"
FILENAME = "coupon.md"
DEFAULT_COUPON_COMMAND = (
    "claude -p --model opus --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)
MIN_ROWS = 8          # 少于这么多行的时间线不叫付息稿
MAX_ROW_SECONDS = 15  # 一行超过这么久，就是很久没付息
ROW = re.compile(r"^\|\s*(\d+):(\d{2})\s*[–—-]\s*(\d+):(\d{2})\s*\|", re.MULTILINE)


def load_framework(root: Path | None = None) -> str:
    path = root / FRAMEWORK_FILE if root is not None else writing_rules.current_path(FRAMEWORK_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WriterError(f"找不到密度的框架文件：{path}") from None
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
    if not body:
        raise WriterError(f"框架文件是空的：{path}")
    return body


def build_prompt(topic: dict[str, Any], skeleton: str, sources: list[dict[str, Any]], *, framework: str, error: str | None = None,
                 series_frame: str = "", episode_material: str = "") -> str:
    material = "\n\n".join(f"### 素材 {i + 1}：{s['title']}\n\n{s['body']}" for i, s in enumerate(sources)) or "（没有附带素材，只根据骨架写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    layers = frame_sections(series_frame, episode_material)
    me = author()
    return f"""你在帮 {me.name} 把一条抖音口播视频的骨架排成「付息稿」。{me.channel_phrase}

下面是他和 Anna 定的付息稿框架。**严格照着做**，它比你的写作习惯优先：

---

{framework}

---{layers}

## 选题
{topic['title']}

## 备注
{topic.get('memo') or '（无）'}

## 已经写好的骨架（开头从「开头候选」里挑最有力的一条；论点照骨架的顺序，可以删、可以合并，不要新增素材里没有的论点）
{skeleton}

## 素材（{me.name} 的原始内容，口播尽量用他的原话改写）
{material}

## 输出
按框架的「输出」一节写，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间。
时间写成「0:18–0:28」这样；每一行口播大约 10 秒。不要编造 {me.name} 的经历、数据和收入。{retry}"""


def _seconds(m: re.Match[str]) -> tuple[int, int]:
    return int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))


def extract(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("缺少标题")
    if not re.search(r"\*\*本金\*\*\s*[:：]\s*\S", text):
        raise WriterError("开头没写本金（看完能拿到什么）")
    if not re.search(r"^##\s*利息账本", text, re.MULTILINE):
        raise WriterError("缺少「利息账本」")
    rows = [_seconds(m) for m in ROW.finditer(text)]
    if len(rows) < MIN_ROWS:
        raise WriterError(f"时间线只有 {len(rows)} 行，至少要 {MIN_ROWS} 行")
    long = [f"{a // 60}:{a % 60:02d}" for a, b in rows if b - a > MAX_ROW_SECONDS]
    if long:
        raise WriterError(f"{'、'.join(long[:3])} 开始的那一行超过 {MAX_ROW_SECONDS} 秒，拆开，每 10 秒左右付一次息")
    return text + "\n"


def write_coupon(topic: dict[str, Any], *, skeleton: str, vault_raw: str, drafts_dir: Path = DEFAULT_DRAFTS_DIR,
                 write_fn: WriteFn | None = None, workflows: Path | None = None, attempts: int = 2,
                 now: datetime | None = None, series_frame: str = "", episode_material: str = "") -> dict[str, Any]:
    if not skeleton.strip():
        raise WriterError("先写骨架")
    framework = load_framework(workflows)
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(COUPON_COMMAND_ENV) or DEFAULT_COUPON_COMMAND, timeout=900))
    sources = topic_sources(vault_raw, topic, drafts_dir)
    error: str | None = None
    for _ in range(attempts):
        try:
            text = extract(fn(build_prompt(topic, skeleton, sources, framework=framework, error=error, series_frame=series_frame, episode_material=episode_material)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成：{error}")
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILENAME).write_text(text, encoding="utf-8")
    meta = {"topic_id": topic["id"], "mode_label": LABEL, "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    (folder / "coupon.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(folder / FILENAME), **meta}


def read_coupon(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / FILENAME
    if not path.is_file():
        return None
    meta_path = path.with_name("coupon.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {"markdown": path.read_text(encoding="utf-8"), "path": str(path),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), **meta}
