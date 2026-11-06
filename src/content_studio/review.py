"""Weekly review: what worked, what did not, and what to change next week.

Built from 作者's own videos of the last 7 days (numbers computed in code), their
teardown reports, topics finished this week and benchmark breakouts. Every claim must
point at a video that was in the input.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Callable

from .identity import author
from .judge import JudgeError, JudgeLoginError, cli_judge

REVIEW_COMMAND_ENV = "CONTENT_STUDIO_REVIEW_CMD"
DEFAULT_REVIEW_COMMAND = (
    "claude -p --model opus --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)
ReviewFn = Callable[[str], dict]


class ReviewError(RuntimeError):
    """The weekly review could not be produced; the message is shown to 作者."""


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _published(video: dict[str, Any]) -> datetime | None:
    raw = video.get("published_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def gather_inputs(
    *,
    own_videos: list[dict[str, Any]],
    median_likes: float | None,
    creator: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    topics: list[dict[str, Any]],
    breakouts: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    since = now - timedelta(days=7)
    videos = []
    for video in own_videos:
        published = _published(video)
        if video.get("is_image_post") or published is None or published < since:
            continue
        metrics = creator.get(video["video_id"]) or {}
        report = reports.get(video["video_id"])
        videos.append(
            {
                "video_id": video["video_id"],
                "title": (video.get("title") or "")[:60],
                "published_at": published.isoformat(timespec="minutes"),
                "likes": video.get("likes"),
                "multiple": round(video["likes"] / median_likes, 1) if median_likes and video.get("likes") is not None else None,
                "collect_per_like": round((video.get("collects") or 0) / video["likes"], 3) if video.get("likes") else None,
                # 9/29 作者：复盘要看的每条视频的数——播放、平均观看、封面点击率、2 秒跳出、5 秒完播，加上点赞、收藏/赞、涨粉
                "plays": _plays(video, metrics),
                "fans": metrics.get("fan_increment"),
                "avg_watch_seconds": round(metrics["avg_view_second"]) if metrics.get("avg_view_second") else None,
                "bounce_2s": metrics.get("bounce_rate_2s"),
                "completion_5s": metrics.get("completion_rate_5s"),
                "cover_ctr": metrics.get("cover_click_rate"),
                "report": {
                    "thesis": (report.get("thesis") or {}).get("text"),
                    "why_boom": [w.get("text") for w in report.get("why_boom", [])][:4],
                    "why_scatter": [w.get("text") for w in report.get("why_scatter", [])][:4],
                    "drift_share": (report.get("drift") or {}).get("share"),
                } if report else None,
            }
        )
    done_topics = [t["title"] for t in topics if t.get("published_at") and (_published({"published_at": t["published_at"]}) or since) >= since]
    week_breakouts = [
        {"video_id": b["video_id"], "title": (b.get("title") or "")[:60], "account": b.get("account_nickname"), "multiple": b.get("multiple"),
         "why_boom": [w.get("text") for w in (reports.get(b["video_id"]) or {}).get("why_boom", [])][:2]}
        for b in breakouts
        if (_published(b) or since - timedelta(days=1)) >= since
    ][:8]
    return {"week": week_key(now), "since": since.date().isoformat(), "until": now.date().isoformat(), "videos": videos,
            "median_likes": median_likes, "topics_done": done_topics, "breakouts": week_breakouts,
            "baseline": baseline(own_videos, creator, now)}


BASELINE_DAYS = 90  # 抖音后台只保留 90 天的数


def _plays(video: dict[str, Any], metrics: dict[str, Any]) -> int | None:
    """播放量。设成私密的视频后台给 0（9/24 那条有 69 个赞、播放 0）：有赞却 0 播放按没有数算。"""
    n = metrics.get("view_count")
    if n is None:
        n = video.get("views")
    if not n and (video.get("likes") or 0) > 0:
        return None
    return n


def _median(values: list[float]) -> float | None:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def baseline(own_videos: list[dict[str, Any]], creator: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
    """作者自己近 90 天的中位数：复盘里每个数都要和它比（只和自己比），单看一个 43% 说明不了好坏。"""
    since = now - timedelta(days=BASELINE_DAYS)
    rows = [(v, creator.get(v["video_id"]) or {}) for v in own_videos
            if not v.get("is_image_post") and (_published(v) or since) >= since and v.get("video_id") in creator]
    pick = lambda f: _median([f(v, m) for v, m in rows])  # noqa: E731
    return {
        "videos": len(rows), "days": BASELINE_DAYS,
        "plays": pick(lambda v, m: _plays(v, m)),
        "likes": pick(lambda v, m: v.get("likes")),
        "collect_per_like": pick(lambda v, m: (v.get("collects") or 0) / v["likes"] if v.get("likes") else None),
        "fans": pick(lambda v, m: m.get("fan_increment")),
        "avg_watch_seconds": pick(lambda v, m: m.get("avg_view_second")),
        "bounce_2s": pick(lambda v, m: m.get("bounce_rate_2s")),
        "completion_5s": pick(lambda v, m: m.get("completion_rate_5s")),
        "cover_ctr": pick(lambda v, m: m.get("cover_click_rate")),
    }


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _num(x: float | None, digits: int = 0) -> str:
    return "—" if x is None else (f"{x:.{digits}f}" if digits else str(round(x)))


def kpi_block(kpi: dict[str, Any] | None) -> str:
    """9/29 作者：KPI 由 Claude 定，他照做；10/5 起只有出摊没做到算减分。跳过要写理由，复盘把重复的借口摆出来。"""
    if not kpi:
        return ""
    skips = "\n".join(f"- {s['day']}｜跳过 {s['what']}｜理由：{s['reason']}" for s in kpi["skips"]) or "（没有跳过）"
    return f"""
## 执行分（作者自己能控制的，这 7 天）
出摊（抖音发出）{kpi['posted']}/7 天；一共减 {kpi['demerits']} 分。10/5 起算分的只有出摊（读日报、回私信、X 互动不算分，别拿来扣他）。
跳过时写的理由：
{skips}
problems 里必须有一条直说执行分：减了几分、哪个借口重复出现了几次（没有重复就说没有）；这一条的 video_ids 给 []。
"""


def build_prompt(inputs: dict[str, Any], error: str | None = None) -> str:
    def fmt_video(v: dict[str, Any]) -> str:
        lines = [f"- id {v['video_id']}｜{v['title']}｜{v['published_at'][:10]}｜播放 {_num(v.get('plays'))}｜点赞 {v['likes']}｜倍数 {v['multiple']}"
                 f"｜收藏/赞 {v['collect_per_like']}｜涨粉 {v['fans']}｜平均观看 {v['avg_watch_seconds']} 秒"
                 f"｜封面点击率 {_pct(v.get('cover_ctr'))}｜2 秒跳出 {_pct(v.get('bounce_2s'))}｜5 秒完播 {_pct(v.get('completion_5s'))}"]
        if v["report"]:
            r = v["report"]
            lines.append(f"  拆解主线：{r['thesis']}；跑题占比 {r['drift_share']}")
            lines.append(f"  为什么爆：{'；'.join(r['why_boom'])}")
            lines.append(f"  为什么散：{'；'.join(r['why_scatter'])}")
        return "\n".join(lines)

    videos = "\n".join(fmt_video(v) for v in inputs["videos"]) or "（这周没有发视频）"
    base = inputs.get("baseline") or baseline([], {}, datetime.now(timezone.utc))
    breakouts = "\n".join(f"- id {b['video_id']}｜{b['account']}｜{b['title']}｜{b['multiple']}×｜{'；'.join(b['why_boom'])}" for b in inputs["breakouts"]) or "（没有）"
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    me = author()
    return f"""你是 {me.name} 的内容复盘教练。{me.channel_phrase}口播视频。账号点赞中位数 {inputs['median_likes']}。
复盘区间：{inputs['since']} 到 {inputs['until']}。

## 这周 {me.name} 发的视频（数字由代码算好，引用时只能用这里的数）
{videos}

## {me.name} 自己的平时水平（近 {base['days']} 天 {base['videos']} 条视频的中位数）
播放 {_num(base['plays'])}｜点赞 {_num(base['likes'])}｜收藏/赞 {_num(base['collect_per_like'], 3)}｜涨粉 {_num(base['fans'])}｜平均观看 {_num(base['avg_watch_seconds'])} 秒｜封面点击率 {_pct(base['cover_ctr'])}｜2 秒跳出 {_pct(base['bounce_2s'])}｜5 秒完播 {_pct(base['completion_5s'])}
判断好坏只和这一行比，不和别人比、不看绝对数。2 秒跳出越低越好，其余越高越好。封面点击率管「人愿不愿意点进来」，2 秒跳出和 5 秒完播管「开头留不留得住」，平均观看管「整条留不留得住」，收藏/赞和涨粉管「来的人对不对」。

## 这周完成的选题
{chr(10).join('- ' + t for t in inputs['topics_done']) or '（没有）'}

## 同期对标账号的爆款
{breakouts}
{kpi_block(inputs.get("kpi"))}

## 要求
只输出一个 JSON 对象，不要其他文字；字符串里需要引号时用「」。
- summary：这一周一句话。
- wins：做对的 1–3 条，每条 {{"text": "", "video_ids": ["..."]}}，text 里要有数字。
- problems：问题 1–3 条，同样结构，落到具体做法（开头、跑题、选题、标题），不要空话。
- next_week：下周只改一件事，恰好 1 条（字符串），要具体可执行，并说明用哪个数看有没有改好。
video_ids 只能用上面出现过的 id。不要编造没有给出的数据。{retry}

## 输出格式
{{"summary": "", "wins": [], "problems": [], "next_week": [""]}}"""


def validate(raw: dict[str, Any], inputs: dict[str, Any]) -> list[str]:
    ids = {v["video_id"] for v in inputs["videos"]} | {b["video_id"] for b in inputs["breakouts"]}
    problems: list[str] = []
    if not str(raw.get("summary") or "").strip():
        problems.append("summary 缺失")
    for key, low, high in (("wins", 0, 3), ("problems", 0, 3)):
        items = raw.get(key)
        if not isinstance(items, list) or not low <= len(items) <= high:
            problems.append(f"{key} 需要 {low}–{high} 条")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                problems.append(f"{key}[{i}].text 缺失")
            elif (not item.get("video_ids") and not (key == "problems" and inputs.get("kpi"))) or any(vid not in ids for vid in item.get("video_ids") or []):
                problems.append(f"{key}[{i}].video_ids 必须是输入里的视频 id")
    if not isinstance(raw.get("next_week"), list) or len(raw["next_week"]) != 1 or not str(raw["next_week"][0] or "").strip():
        problems.append("next_week 需要恰好 1 条")
    return problems


def generate_review(inputs: dict[str, Any], *, review_fn: ReviewFn | None = None, attempts: int = 3, now: datetime | None = None) -> dict[str, Any]:
    if not inputs["videos"]:
        raise ReviewError("这 7 天没有发视频，没有可复盘的数据；先同步我的数据再试")
    fn = review_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(REVIEW_COMMAND_ENV) or DEFAULT_REVIEW_COMMAND, timeout=900))
    error: str | None = None
    for _ in range(attempts):
        try:
            raw = fn(build_prompt(inputs, error))
        except JudgeLoginError:
            raise
        except JudgeError as exc:
            error = str(exc)
            continue
        problems = validate(raw, inputs)
        if not problems:
            titles = {v["video_id"]: v["title"] for v in inputs["videos"]} | {b["video_id"]: b["title"] for b in inputs["breakouts"]}
            for key in ("wins", "problems"):
                for item in raw[key]:
                    item["videos"] = [{"video_id": vid, "title": titles[vid]} for vid in item["video_ids"]]
            raw.pop("patterns", None)
            raw.pop("experiment", None)
            return {**raw, "week": inputs["week"], "since": inputs["since"], "until": inputs["until"],
                    "videos": inputs["videos"], "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
        error = "；".join(problems[:6])
    raise ReviewError(f"复盘连续 {attempts} 次没通过校验，可点重新生成：{error}")
