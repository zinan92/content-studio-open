"""读 park-writing 的模块清单（module.yaml）：流程有哪几步、顺序、每步读哪一段、过什么关卡。
流程只在 skill 里定，这里只读，不写死第二份（10/12 作者）。格式见 skill 里的 MODULE.md。

读不懂就拒绝：清单里有工作台不认识的字段或关卡、规则段落找不到，ModuleError 把原因一条条列出来，
这一步不运行。「看起来跑了其实没查」不允许。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any

import yaml

from ... import writing_rules

MANIFEST = "module.yaml"
GROUPS = ("写", "风格", "查")
STATUS = ("split", "whole", "planned")
OUTPUT = ("article", "report", "verdict", "changes")
FIX = ("edit", "comment")
ON_FAIL = ("warn", "swap", "block", "swap-if-ending-unfinished")
CONSTRAINTS = ("max-change-pct", "keep-order", "original-words", "no-new-facts")
STEP_KEYS = {"title", "group", "round", "status", "prompt", "does", "output", "fix", "ask", "only", "may-move", "may-add", "may-delete", "on-fail"}
FORMS = ("长文", "长帖", "短帖")
DEFAULT_CHANGE_PCT = 20       # 10/12 作者：默认 20%，在页面里能改（设置 · 写作流程，或这一篇的批注视图顶上）
MAX_CHANGE_PCT = 50           # 能调到的上限；清单里写的 max-change-pct 只当出厂建议，不再管用
MAY_MOVE = ("first-sentence",)
MAY_ADD = ("bridge-sentence",)


class ModuleError(RuntimeError):
    """清单有问题：message 是给 作者 看的，一条一行。"""


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    group: str
    status: str
    prompt: str | None
    does: str
    output: str
    on_fail: str
    round: int = 1
    fix: str = "edit"
    ask: bool = False
    only: tuple[str, ...] = ()
    may_move: str | None = None
    may_add: str | None = None
    may_delete: bool | None = None   # None = 清单没写：只有「风格」可以删口癖、重复、读者看不到的指代
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def runnable(self) -> bool:
        return self.status != "planned"


@dataclass(frozen=True)
class ReviewItem:
    """评判清单里的一项（10/13 作者 的 9 项）：由 from 里那几步的规则来打分。"""
    id: str
    title: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Module:
    root: Path
    version: int
    flows: dict[str, tuple[str, ...]]
    steps: dict[str, Step]
    constraints: dict[str, Any]
    asked_change_pct: int
    review: tuple[ReviewItem, ...] = ()           # 清单没有 review 的老版本：空，工作台退回原来的六项打分
    post_shoot: dict[str, Any] | None = None      # 拍后批注：{title, prompt, does}；老版本没有就是 None

    def post_shoot_text(self) -> str:
        return section_text(self.root, (self.post_shoot or {}).get("prompt") or "")

    def review_items(self, steps: list[Step] | tuple[Step, ...]) -> list[ReviewItem]:
        """这一次调用里要打分的项：from 里至少有一步在 steps 里（用户关掉的步骤，它那一项就不打）。"""
        ids = {s.id for s in steps}
        return [item for item in self.review if ids & set(item.steps)]

    def step_text(self, step_id: str) -> str:
        return section_text(self.root, self.steps[step_id].prompt or "")

    def step_version(self, step_id: str) -> str:
        """这一步的版本：它读的那段规则文字加清单里这一条，改了任何一个都会变。"""
        step = self.steps[step_id]
        blob = (self.step_text(step_id) if step.prompt else "") + "\n" + yaml.safe_dump(step.raw, allow_unicode=True, sort_keys=True)
        return sha1(blob.encode("utf-8")).hexdigest()[:10]

    def ordered(self) -> list[Step]:
        """清单里的全部步骤，按写 → 风格 → 查、同组按流程 1 的顺序（没在流程 1 里的排最后）。"""
        first = next(iter(self.flows.values()), ())
        rank = {sid: i for i, sid in enumerate(first)}
        return sorted(self.steps.values(), key=lambda s: (GROUPS.index(s.group), rank.get(s.id, 999)))

    def round_steps(self, ids: list[str] | tuple[str, ...], n: int) -> list[Step]:
        """流程里第 n 轮的、能跑的步骤，按清单的固定顺序。"""
        return [s for s in self.flow_steps(ids) if s.round == n and s.runnable]

    def flow_steps(self, ids: list[str] | tuple[str, ...]) -> list[Step]:
        """一个流程里的步骤，按清单的固定顺序（用户只能开关，不能调顺序）。"""
        wanted = set(ids)
        return [s for s in self.ordered() if s.id in wanted]


def section_text(root: Path, ref: str) -> str:
    """`文件#标题开头的字`：取文件里第一个以这几个字开头的标题，到下一个同级或更高级标题之前。没有 # 就是整份文件。"""
    path, _, anchor = ref.partition("#")
    if not path:
        return ""
    text = (root / path).read_text(encoding="utf-8")
    if not anchor:
        return text.strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#") and line.lstrip("#").strip().startswith(anchor):
            level = len(line) - len(line.lstrip("#"))
            end = next((j for j in range(i + 1, len(lines))
                        if lines[j].startswith("#") and len(lines[j]) - len(lines[j].lstrip("#")) <= level), len(lines))
            return "\n".join(lines[i:end]).strip()
    raise FileNotFoundError(f"{path} 里没有以「{anchor}」开头的标题")


def available() -> bool:
    """这台机器有没有装带清单的 park-writing。没装 skill 或老版没有清单：走老的整理，不报错。"""
    root = writing_rules.skill_dir()
    return root is not None and (root / MANIFEST).is_file()


def clamp_pct(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CHANGE_PCT
    return max(1, min(n, MAX_CHANGE_PCT))


def load(root: Path | None = None, *, max_change_pct: Any = None) -> Module:
    """max_change_pct：他在页面上定的改动预算（设置里的默认，或这一篇自己改的）；不给就是 20。"""
    root = root or writing_rules.skill_dir()
    if root is None or not (root / MANIFEST).is_file():
        raise ModuleError("这台机器没有带 module.yaml 的 park-writing")
    try:
        data = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ModuleError(f"module.yaml 读不懂：{exc}") from exc
    errors: list[str] = []
    raw_steps = data.get("steps") or {}
    flows = {str(k): tuple(map(str, v or ())) for k, v in (data.get("flows") or {}).items()}
    if not raw_steps:
        errors.append("清单里没有 steps")
    if not flows:
        errors.append("清单里没有 flows")
    constraints = dict(data.get("constraints") or {})
    for name in constraints:
        if name not in CONSTRAINTS:
            errors.append(f"关卡「{name}」工作台不认识（只认 {'、'.join(CONSTRAINTS)}），这份清单不能跑")
    asked = constraints.get("max-change-pct", DEFAULT_CHANGE_PCT)
    if not isinstance(asked, (int, float)) or asked <= 0:
        errors.append("max-change-pct 要写一个大于 0 的数")
        asked = DEFAULT_CHANGE_PCT
    effective = {"max-change-pct": clamp_pct(max_change_pct if max_change_pct is not None else DEFAULT_CHANGE_PCT),
                 "keep-order": True, "original-words": True, "no-new-facts": True}
    steps: dict[str, Step] = {}
    for sid, s in raw_steps.items():
        s = s or {}
        bad = sorted(set(s) - STEP_KEYS)
        if bad:
            errors.append(f"步骤 {sid} 里有工作台不认识的字段：{'、'.join(bad)}")
        for key, allowed in (("group", GROUPS), ("status", STATUS), ("output", OUTPUT), ("on-fail", ON_FAIL)):
            if s.get(key) not in allowed:
                errors.append(f"步骤 {sid} 的 {key} 写的是「{s.get(key)}」，只能是 {'、'.join(allowed)}")
        if s.get("round") not in (1, 2):
            errors.append(f"步骤 {sid} 的 round 只能是 1 或 2")
        if s.get("fix", "edit") not in FIX:
            errors.append(f"步骤 {sid} 的 fix 只能是 {'、'.join(FIX)}")
        for key in ("title", "does"):
            if not s.get(key):
                errors.append(f"步骤 {sid} 缺 {key}")
        if s.get("may-move") not in (None, *MAY_MOVE):
            errors.append(f"步骤 {sid} 的 may-move 只认 {'、'.join(MAY_MOVE)}")
        if s.get("may-add") not in (None, *MAY_ADD):
            errors.append(f"步骤 {sid} 的 may-add 只认 {'、'.join(MAY_ADD)}")
        if s.get("may-delete") not in (None, True, False):
            errors.append(f"步骤 {sid} 的 may-delete 只能写 true 或 false")
        only = tuple(s.get("only") or ())
        if set(only) - set(FORMS):
            errors.append(f"步骤 {sid} 的 only 只能是 {'、'.join(FORMS)}")
        if s.get("status") == "planned":
            if s.get("prompt") is not None:
                errors.append(f"步骤 {sid} 还没写（planned），prompt 要写 null")
        elif s.get("prompt"):
            try:
                section_text(root, s["prompt"])
            except (OSError, FileNotFoundError) as exc:
                errors.append(f"步骤 {sid} 的规则找不到：{exc}")
        else:
            errors.append(f"步骤 {sid} 没写 prompt")
        steps[sid] = Step(id=sid, title=str(s.get("title") or sid), group=str(s.get("group")), status=str(s.get("status")),
                          prompt=s.get("prompt"), does=str(s.get("does") or ""), output=str(s.get("output")),
                          on_fail=str(s.get("on-fail")), round=int(s.get("round") or 1), fix=str(s.get("fix") or "edit"),
                          ask=bool(s.get("ask")), only=only,
                          may_move=s.get("may-move"), may_add=s.get("may-add"), may_delete=s.get("may-delete"), raw=dict(s))
    review: list[ReviewItem] = []
    for raw in data.get("review") or []:
        raw = raw or {}
        rid, title, source = str(raw.get("id") or ""), str(raw.get("title") or ""), tuple(map(str, raw.get("from") or ()))
        if not rid or not title or not source:
            errors.append("评判清单里每一项都要有 id、title、from")
            continue
        if any(r.id == rid or r.title == title for r in review):
            errors.append(f"评判清单里「{title}」重复了")
        for sid in source:
            if sid not in steps:
                errors.append(f"评判清单「{title}」的 from 里的 {sid} 不在 steps 里")
        review.append(ReviewItem(rid, title, source))
    post_shoot = data.get("post-shoot")
    if post_shoot is not None:
        post_shoot = dict(post_shoot or {})
        if not post_shoot.get("prompt"):
            errors.append("post-shoot 没写 prompt")
        else:
            try:
                section_text(root, post_shoot["prompt"])
            except (OSError, FileNotFoundError) as exc:
                errors.append(f"post-shoot 的规则找不到：{exc}")
    for name, ids in flows.items():
        if len(ids) != len(set(ids)):
            errors.append(f"流程「{name}」里有重复的步骤")
        for sid in ids:
            if sid not in steps:
                errors.append(f"流程「{name}」里的 {sid} 不在 steps 里")
    if errors:
        raise ModuleError("\n".join(errors))
    return Module(root=root, version=int(data.get("version") or 1), flows=flows, steps=steps, constraints=effective,
                  asked_change_pct=int(asked), review=tuple(review), post_shoot=post_shoot)


def with_pct(module: "Module", pct: Any) -> "Module":
    """同一份清单换一个改动预算（这一篇自己改过的）。"""
    from dataclasses import replace

    return replace(module, constraints={**module.constraints, "max-change-pct": clamp_pct(pct)})
