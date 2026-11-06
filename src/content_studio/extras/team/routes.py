"""AI 团队：Anna（常驻主编，右边的对话窗）和 Wendy（今天页的老板卡片，微信那边也是她），以及她们每轮读哪些文件。试用版没有这一块。"""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Any, Literal
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from ... import today as today_plan, vault, video_project
from ...store import StoreError, now_iso
from ...video_project import VideoProjectError
from ...web import AnnaBody, WendyBody, _creator_rows, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = (
    "_local", "anna_fn", "creator_db", "data_dir", "drafts_root", "get_board", "get_kpi", "get_reach", "get_results",
    "get_review", "get_today", "get_today_home", "places", "reports", "shot_days", "store", "wendy_fn",
    "startup", "stop_auto", "feature_on",
)
PROVIDES: tuple[str, ...] = ()


class ReviewProposalBody(BaseModel):
    index: int = Field(ge=0, strict=True)
    decision: Literal["try", "skip"]


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    _local = ctx._local
    anna_fn = ctx.anna_fn
    creator_db = ctx.creator_db
    data_dir = ctx.data_dir
    drafts_root = ctx.drafts_root
    get_board = ctx.get_board
    get_reach = ctx.get_reach
    get_results = ctx.get_results
    get_kpi = ctx.get_kpi
    get_review = ctx.get_review
    get_today = ctx.get_today
    report_file = places.report_file
    reports = ctx.reports
    shot_days = ctx.shot_days
    store = ctx.store
    vault_path = places.vault_path
    video_root = places.video_root
    wendy_fn = ctx.wendy_fn

    @app.get("/api/anna/soul")
    def anna_soul() -> dict[str, Any]:
        """Anna 每轮读的文件：角色、knowledge、原则、定位、三点评分。只读列出来。"""
        home = str(Path.home())
        return {"files": [{"i": i, "name": Path(p).name, "path": p.replace(home, "~")} for i, p in enumerate(anna_mod.load_soul()["sources"])],
                "also": list(anna_mod.ALSO)}

    @app.get("/api/wendy/soul")
    def wendy_soul() -> dict[str, Any]:
        """Wendy 读的文件和每轮还带上的。和她那一轮用的是同一个路径。"""
        from . import wendy

        home = str(Path.home())
        return {"files": [{"i": i, "name": Path(f["path"]).name, "path": f["path"].replace(home, "~"), "when": f["when"],
                           "exists": Path(f["path"]).is_file()} for i, f in enumerate(wendy.sources())],
                "also": list(wendy.ALSO)}

    @app.get("/api/wendy/soul/{index}")
    def wendy_soul_doc(index: int) -> dict[str, Any]:
        from . import wendy

        files = wendy.sources()
        if not 0 <= index < len(files):
            raise ValueError("没有这个文件")
        path = Path(files[index]["path"])
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"name": path.name, "path": str(path).replace(str(Path.home()), "~"), "body": anna_mod._strip_frontmatter(text)[:60000]}

    @app.get("/api/anna/soul/{index}")
    def anna_soul_doc(index: int) -> dict[str, Any]:
        sources = anna_mod.load_soul()["sources"]
        if not 0 <= index < len(sources):
            raise ValueError("没有这个文件")
        path = Path(sources[index])
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"name": path.name, "path": str(path).replace(str(Path.home()), "~"), "body": anna_mod._strip_frontmatter(text)[:60000]}

    # -- Anna: the resident editor (right column) ---------------------------------

    from . import anna as anna_mod

    # One conversation across every page: switching pages changes what Anna sees, not who you talk to.
    ANNA_THREAD = "main"
    store.merge_anna_threads(ANNA_THREAD)
    anna_busy: set[str] = set()
    anna_errors: dict[str, str] = {}
    anna_lock = threading.Lock()

    def _anna_scope(scope: str) -> tuple[str, str, int | None]:
        kind, _, rest = scope.partition(":")
        if kind == "work":
            if not rest.isdigit():
                raise ValueError("这条视频不存在")
            return "work", anna_mod.SCOPE_LABELS["work"], int(rest)
        if kind not in anna_mod.SCOPE_LABELS:
            raise ValueError("未知页面")
        return kind, anna_mod.SCOPE_LABELS[kind], None

    def _report_context(video_id: str) -> str:
        """The teardown 作者 has open. Without it Anna answers 「这条教了什么方法」 from nothing —
        and the rule she then proposes for 记进标准 would be invented."""
        path = report_file(video_id)
        if path is None:
            return "## 作者 正在看的拆解报告\n读不到这份报告"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "## 作者 正在看的拆解报告\n读不到这份报告"
        account = store.account(store.video(video_id)["account_id"]) if store.video(video_id) else None
        whose = "自己的视频" if account and account["is_self"] else "对标"
        facts = data.get("facts") or {}
        head = (f"## 作者 正在看的拆解报告（{whose}）\n标题：{data.get('title')}\n作者：{data.get('author')}\n"
                f"点赞 {facts.get('likes')}（是他自己中位数的 {facts.get('multiple_of_median')} 倍）；播放 {facts.get('views')}；"
                f"收藏 {facts.get('collects')}；评论 {facts.get('comments')}；分享 {facts.get('shares')}\n"
                f"主线：{data.get('thesis')}\n开头：{json.dumps(data.get('opening'), ensure_ascii=False)[:600]}\n"
                f"为什么爆：{data.get('why_boom')}\n哪里散了：{data.get('why_scatter')}")
        budget = 7000
        parts = []
        for seg in data.get("segments") or []:
            block = (f"### {seg.get('index')} {seg.get('label')}（{seg.get('start')}–{seg.get('end')} 秒）"
                     f"{'｜跑题' if seg.get('drift') else ''}\n{seg.get('summary')}｜{seg.get('reason')}\n原话：{(seg.get('text') or '')[:400]}")
            if len(block) > budget:
                break
            budget -= len(block)
            parts.append(block)
        return head + "\n\n## 分段\n" + "\n\n".join(parts)

    def _anna_overview() -> str:
        """The standing index of the whole backend, ~1 screen, every turn.

        The page 作者 happens to be on is a wrapper over the same database; without this Anna
        can only see that one slice and has to guess at everything else. This is deliberately a
        table of contents, not the contents: 83 teardown reports would be tens of thousands of
        characters, and she needs to know they exist far more often than she needs to read one.
        """
        out: list[str] = []
        try:
            data = get_board(None)
            focus = data.get("focus")
            out.append(
                f"- 正在做：{('《' + focus['title'][:30] + '》｜在等：' + focus['next']['text']) if focus else '还没定'}"
                f"\n- 选题池 {len(data.get('pool') or [])} 条；剪辑/待发 {len(data.get('machine') or [])} 条；暂缓 {len(data.get('snoozed') or [])} 条"
            )
        except Exception:  # noqa: BLE001 - the overview must never break a turn
            pass
        try:
            items = vault.inbox(vault_path(), since=vault.window_start(7))
            by_source: dict[str, int] = {}
            for i in items:
                if i.get("source") != "raw" and i.get("triage") in (None, "back") and not i.get("used_by"):
                    by_source[i["source_label"]] = by_source.get(i["source_label"], 0) + 1
            out.append("- 选题近 7 天还没处理：" + ("；".join(f"{k} {v}" for k, v in by_source.items()) or "没有"))
        except Exception:  # noqa: BLE001
            pass
        try:
            r = get_reach(14)
            out.append(f"- 触达：今天 {r['today']}，近 7 天日均 {r['avg7']}")
        except Exception:  # noqa: BLE001
            pass
        try:
            # not `reports = reports()`: that makes the name local and the call raises.
            all_reports = reports()
            recent = "；".join(f"{x['author'] or ''}《{(x['title'] or '')[:20]}》" for x in all_reports[:8])
            out.append(f"- 拆解报告共 {len(all_reports)} 份，最近的：{recent}")
        except Exception:  # noqa: BLE001
            pass
        try:
            accounts = [a["nickname"] or "?" for a in store.followed_accounts()]
            out.append(f"- 关注的账号 {len(accounts)} 个：{'、'.join(accounts)}")
        except Exception:  # noqa: BLE001
            pass
        return "## 工作台全局（这是目录，不是全文）\n" + "\n".join(out) if out else ""

    def _anna_events(limit: int = 12) -> str:
        """最近发生了什么。Without it Anna cannot know a topic just moved out of 进项."""
        rows = store.events(limit)
        if not rows:
            return ""
        def when(iso: str) -> str:
            try:
                dt = datetime.fromisoformat(iso).astimezone()
                return dt.strftime("%m-%d %H:%M")
            except ValueError:
                return iso[:16]
        return "## 最近发生了什么\n" + "\n".join(f"- {when(r['at'])} {r['text']}" for r in rows)

    def _anna_context(kind: str, topic_id: int | None, note_path: str | None, report_id: str | None = None) -> str:
        """What 作者 is looking at right now, plus the backend index and recent history."""
        from ... import board, opening, outline, qa, writer

        lines: list[str] = [x for x in (_anna_overview(), _anna_events()) if x]
        if kind == "input":
            day_value = date.today()
            for item in vault.dailies(vault_path(), day_value):
                if item.get("path"):
                    note = vault.read_note(vault_path(), item["path"])
                    lines.append(f"## 今天的{item['label']}\n{(note.get('body') or '')[:5000]}")
                else:
                    lines.append(f"## 今天的{item['label']}：还没出")
            triage = store.triage()
            used = {p: t for t in store.topics(include_archived=True) for p in (t.get("note_paths") or [])}
            items = vault.inbox(vault_path(), since=vault.window_start(7))[:30]  # vault.inbox compares against naive local mtimes
            rows = []
            for i in items:
                state = "已进加工中" if i["path"] in used else {"topic": "已拿来做", "shot": "拍过了", "ignored": "暂不拍"}.get((triage.get(i["path"]) or {}).get("status"), "还没处理")
                rows.append(f"- [{i['source_label']}] {i['title']}（{state}）{'：' + i['summary'][:80] if i.get('summary') else ''}")
            lines.append("## 近 7 天进来的（Clippings / 我收藏的 / 我写的）\n" + ("\n".join(rows) or "没有新东西"))
            if note_path:
                try:
                    note = vault.read_note(vault_path(), note_path)
                    lines.append(f"## 作者 正在读的这篇：{note['title']}\n{(note.get('body') or '')[:8000]}")
                except (vault.VaultError, OSError):
                    pass
        elif kind == "board":
            data = get_board(None)
            stage_names = dict(board.STAGES)
            lines.append("## 看板\n" + ("\n".join(
                f"- [{stage_names.get(c['stage'], c['stage'])}] {c['title']}｜在等：{c['next']['text']}" + (f"｜三点 {c['qa']['total']}/15（{c['qa']['verdict']}）" if c.get("qa") else "") for c in data["cards"]) or "看板是空的"))
            k = data["streak"]
            lines.append(f"## 拍摄\n连续拍摄 {k.get('days')} 天；今天{'已经拍了' if k.get('today_done') else '还没拍'}；距上次拍 {k.get('days_since_last')} 天")
        elif kind == "work" and topic_id is not None:
            topic = store.topic(topic_id)
            lines.append(f"## 这条视频\n标题：{topic['title']}\n状态：{topic.get('status')}{'（已归档）' if topic.get('archived_at') else ''}\n备注：{topic.get('memo') or '（无）'}")
            draft = outline.read_outline(topic)
            lines.append("## 拍摄提纲\n" + (draft["markdown"] if draft else "还没写"))
            from ... import coupon as coupon_mod

            cp = coupon_mod.read_coupon(drafts_root, topic_id)
            if cp:
                lines.append("## 付息稿（骨架排成的时间线：开头发债、每 10 秒付息、最后兑付本金）\n" + cp["markdown"][:6000])
            q = qa.load(drafts_root, topic_id)
            if q:
                lines.append("## 三点评分\n" + "\n".join(f"- {label} {q[key]['score']}/5：{q[key]['reason']}" for key, label in qa.POINTS) + f"\n- 结论：{q['verdict']}｜最该改：{q['fix']}" + (f"｜不要讲过头：{q['caution']}" if q.get("caution") else ""))
            op = opening.load(drafts_root, topic_id)
            if op:
                lines.append(f"## 开头 15 秒检查\n{'通过' if op.get('passed') else '没通过'}；主线在第 {op.get('stated_at')} 秒说出；前 15 秒字幕：{op.get('first_15s', '')[:400]}\n改法：{'；'.join(op.get('fixes') or [])}")
            if topic.get("video_project"):
                try:
                    info = video_project.inspect(video_root(), topic["video_project"])
                    gate = info.get("gate") or {}
                    lines.append(f"## 剪辑进度\n项目：{info.get('name')}；{info.get('summary')}；第 {info.get('current_step')} 步{'；已交付成片' if info.get('delivered') else ''}{'；等你：' + gate.get('title', '') if gate else ''}")
                except VideoProjectError as exc:
                    lines.append(f"## 剪辑进度\n读不到项目：{exc}")
            if topic.get("published_video_id"):
                v = store.video(topic["published_video_id"])
                if v:
                    me = store.self_account()
                    median = store.account_median(me["id"]) if me else None
                    mult = round(v["likes"] / median, 1) if median and v.get("likes") is not None else None
                    creator = _creator_rows(creator_db).get(v["video_id"]) or {}
                    lines.append(f"## 发出后的数据\n{v.get('published_at', '')[:10]} 发出；点赞 {v.get('likes')}（是自己中位数的 {mult} 倍）；播放 {v.get('views')}；收藏 {v.get('collects')}；评论 {v.get('comments')}；分享 {v.get('shares')}"
                                 + (f"；2 秒跳出 {creator.get('bounce_rate_2s')}；平均观看 {creator.get('avg_view_second')} 秒；涨粉 {creator.get('fan_increment')}" if creator else ""))
            sources = writer.topic_sources(vault_path(), topic, drafts_root)
            if sources:
                budget = 9000
                chunks = []
                for src in sources:
                    body = src["body"][: max(0, budget)]
                    budget -= len(body)
                    chunks.append(f"### {src['title']}\n{body}")
                lines.append("## 关联的素材\n" + "\n\n".join(chunks))
        elif kind == "output":
            me = store.self_account()
            if me is None:
                lines.append("## 已发出\n还没有连接自己的抖音号")
            else:
                median = store.account_median(me["id"])
                creator = _creator_rows(creator_db)
                cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()[:10]
                rows = []
                for v in [x for x in store.videos(me["id"]) if not x["is_image_post"] and (x["published_at"] or "") >= cutoff][:40]:
                    c = creator.get(v["video_id"]) or {}
                    mult = round(v["likes"] / median, 1) if median and v.get("likes") is not None else None
                    extra = f"；2 秒跳出 {round(c['bounce_rate_2s'] * 100)}%；平均观看 {round(c['avg_view_second'])} 秒；涨粉 {c.get('fan_increment')}；主页访问 {c.get('homepage_visit_count')}" if c.get("avg_view_second") is not None else ""
                    rows.append(f"- {(v['published_at'] or '')[:10]}｜{(v['title'] or '').split(chr(10))[0][:40]}｜点赞 {v['likes']}（{mult}×）；收藏 {v.get('collects')}；评论 {v.get('comments')}；分享 {v.get('shares')}{extra}")
                lines.append(f"## 近 90 天发出的视频（点赞中位数 {median}）\n" + ("\n".join(rows) or "没有"))
                rv = get_review()
                if rv.get("data"):
                    lines.append("## 最近一次每周复盘\n" + json.dumps(rv["data"], ensure_ascii=False)[:3000])
                k = today_plan.shooting_streak(date.today(), shot_days())
                lines.append(f"## 拍摄\n连续拍摄 {k.get('days')} 天；距上次拍 {k.get('days_since_last')} 天")
            if report_id:
                lines.append(_report_context(report_id))
        elif kind == "positioning":
            from ..positioning import positioning

            pos = positioning.read()
            lines.append("## 作者 的定位页（他正在看的就是这份文件）\n" + (pos["markdown"][:12000] if pos["exists"] else "还没有定位文件"))
            me = store.self_account()
            if me is not None:
                lines.append(f"## 他的抖音主页\n昵称：{me.get('nickname')}；粉丝 {me.get('follower_count')}\n简介：{me.get('signature') or '（没抓到）'}")
                titles = [(v['title'] or '').split(chr(10))[0][:50] for v in store.videos(me["id"]) if not v["is_image_post"]][:12]
                lines.append("## 他最近的视频标题（做「陌生人自测」用）\n" + ("\n".join(f"- {t}" for t in titles) or "没有"))
        elif kind == "consults":
            from ..consults import consult

            rows = consult.clients(vault.vault_root(vault_path()))
            for row in rows[:12]:
                p = row["profile"]
                lines.append(f"## 客户：{row['name']}\n来源：{p['来源'] or '未填'}；首次咨询收费：{p['首次咨询收费'] or '未填'}；"
                             f"画像：{p['画像'] or '未填'}；后续方案：{p['后续方案'] or '未填'}；报价：{p['报价'] or '未填'}")
                note = next((c.get("note") for c in row["consults"] if c.get("note")), None)
                if note and Path(note).is_file():
                    text = Path(note).read_text(encoding="utf-8").split("## 逐段对照")[0]
                    lines.append("### 最近一场咨询的总结\n" + text[-4000:])
            if not rows:
                lines.append("还没有咨询客户。")
        else:
            lines.append("作者 在设置页。")
        return "\n\n".join(lines)

    def _anna_page_label(scope: str) -> str:
        """「进项」「加工中」「《某条视频》」— shown next to each message so 作者 sees where it was said."""
        try:
            kind, label, topic_id = _anna_scope(scope)
            if kind == "work" and topic_id is not None:
                return f"《{store.topic(topic_id)['title'][:14]}》"
            return label
        except (ValueError, StoreError):
            return ""

    def _anna_vault() -> Path | None:
        try:
            return vault.vault_root(vault_path())
        except Exception:  # noqa: BLE001 - 没配 vault 就只用 <工作台> 块
            return None

    def _anna_dirs() -> dict[str, Path]:
        """vault 之外她能查的：每条视频的拆解报告、下载下来的老师流量视频（文字稿、信息）。"""
        return {"拆解报告：每条视频一个文件夹，report.md 是拆解": data_dir / "reports",
                "老师的流量视频：下载的视频、文字稿和信息": data_dir / "swipe"}

    @app.post("/api/anna/raw")
    def anna_raw(body: dict[str, Any]) -> dict[str, Any]:
        """Anna 整理的一篇，作者 点了按钮：写进 vault 的 003_原始输出。"""
        root = _anna_vault()
        if root is None:
            raise ValueError("还没设 Obsidian 库")
        try:
            path = anna_mod.save_raw(root, str(body.get("target") or ""), str(body.get("body") or ""))
        except anna_mod.AnnaError as exc:
            raise ValueError(str(exc)) from None
        return {"path": str(path), "name": path.name, "folder": path.parent.name}

    def _anna_turn(scope: str, kind: str, label: str, topic_id: int | None, message: str, note_path: str | None, report_id: str | None = None,
                   screen: str = "") -> None:
        try:
            context = _anna_context(kind, topic_id, note_path, report_id)
            chat = store.anna_chat(ANNA_THREAD)
            if topic_id is not None:
                label = f"{label}《{store.topic(topic_id)['title']}》"
            reply = anna_mod.run_turn(scope=scope, scope_label=label, context=context, message=message, session_id=chat["session_id"],
                                      vault=_anna_vault(), extra_dirs=_anna_dirs(), screen=screen, **({"turn_fn": anna_fn} if anna_fn else {}))
            store.append_anna(ANNA_THREAD, {k: reply[k] for k in ("role", "text", "actions", "at", "scope")}, session_id=reply.get("session_id"))
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            logger.warning("anna %s failed: %s", scope, exc)
            with anna_lock:
                anna_errors[ANNA_THREAD] = str(exc)[:300] or type(exc).__name__
        finally:
            with anna_lock:
                anna_busy.discard(ANNA_THREAD)

    @app.get("/api/anna")
    def get_anna(scope: str) -> dict[str, Any]:
        kind, label, topic_id = _anna_scope(scope)
        chat = store.anna_chat(ANNA_THREAD)
        with anna_lock:
            busy = ANNA_THREAD in anna_busy
            error = anna_errors.get(ANNA_THREAD)
        title = store.topic(topic_id)["title"] if kind == "work" and topic_id is not None else None
        pages: dict[str, str] = {}
        messages = []
        for m in chat["messages"]:
            where = m.get("scope") or ""
            if where and where not in pages:
                pages[where] = _anna_page_label(where)
            messages.append({**m, "page": pages.get(where, "")})
        return {"scope": scope, "label": label, "title": title, "messages": messages, "busy": busy, "error": error, "soul": [Path(p).name for p in anna_mod.load_soul()["sources"]]}

    @app.post("/api/anna")
    def post_anna(body: AnnaBody) -> dict[str, Any]:
        kind, label, topic_id = _anna_scope(body.scope)
        message = body.message.strip()
        if not message:
            raise ValueError("先说点什么")
        if len(message) > 4000:
            raise ValueError("一次最多 4000 字")
        if kind == "work" and topic_id is not None:
            store.topic(topic_id)
        with anna_lock:
            if ANNA_THREAD in anna_busy:
                return {"started": False, "message": "Anna 还在想上一条"}
            anna_busy.add(ANNA_THREAD)
            anna_errors.pop(ANNA_THREAD, None)
        store.append_anna(ANNA_THREAD, {"role": "park", "text": message, "at": now_iso(), "scope": body.scope})
        threading.Thread(target=_anna_turn, args=(body.scope, kind, label, topic_id, message, body.note_path, body.report_id, body.screen), name=f"anna-{body.scope}", daemon=True).start()
        return {"started": True}

    @app.delete("/api/anna")
    def delete_anna(scope: str | None = None) -> dict[str, Any]:
        with anna_lock:
            if ANNA_THREAD in anna_busy:
                raise ValueError("Anna 还在想，等她答完再清")
            anna_errors.pop(ANNA_THREAD, None)
        store.clear_anna(ANNA_THREAD)
        return {"ok": True}

    # -- Wendy：「今天」页最上面那张卡片（wendy.py）-------------------------------------
    wendy_state: dict[str, Any] = {"busy": False, "error": None}
    wendy_lock = threading.Lock()

    # 每日复盘只读现成数字；模型只写一段话，页面和微信的账共用这一份。
    from ... import daily_review, kpi_board
    from ...paths import config_dir
    from . import wendy

    verdict_lock = threading.Lock()
    ledger_lock = threading.Lock()
    verdict_writing: set[str] = set()
    bj = timezone(timedelta(hours=8))

    def _review_data() -> dict[str, Any]:
        today = get_today()
        home = ctx.get_today_home()
        if home.get("money") is not None:
            yesterday_key = (date.fromisoformat(today["day"]) - timedelta(days=1)).isoformat()
            home["money"]["yesterday"] = sum(float(r["amount"]) for r in store.revenue(yesterday_key) if r["day"] == yesterday_key)
        me = store.self_account()
        return daily_review.build(studio_db=store.path, creator_db=creator_db, account_id=me["id"] if me else None,
                                  x_daily_path=config_dir() / "x_daily.json", today_payload=today,
                                  reach_payload=get_reach(14), home_payload=home, settings=store.settings())

    @app.get("/api/today/review")
    def get_daily_review() -> dict[str, Any]:
        review = _review_data()
        with verdict_lock:
            cached = daily_review.load_verdict(review["day"])
            # 10/13 作者 问「她真的在写吗」：没开始写就说没开始、几点写，不能一律显示「在写」
            verdict = {"state": "writing"} if review["day"] in verdict_writing else (cached or {"state": "waiting", "from": "09:35"})
        return {**review, "verdict": verdict}

    def _write_verdict(day: str, attempts: int) -> None:
        try:
            role = wendy.load_role()["text"]
            review = _review_data()
            if review["day"] != day:
                raise ValueError("日期已切换，下一轮写今天的复盘")
            system = role + "\n\n你在写今天早上给 作者 的复盘：首页「战况」最上面那一块。X 那部分按当天的 X 主打看，说这套打法有没有用、明天改不改。"
            try:
                board = kpi_board.brief_text(get_kpi())
            except Exception as exc:  # noqa: BLE001 - 战况读不到也照样写复盘
                logger.warning("daily review kpi board failed: %s", exc)
                board = ""
            prompt = daily_review.verdict_prompt(review, role, board)
            if wendy_fn is not None:
                result = wendy_fn(system, prompt, None)
            else:
                result = wendy.cli_turn(system, prompt, None, extra_args=["--tools", ""])
            text = str(result.get("text") or "").strip()
            if not text:
                raise ValueError("Wendy 没有写出复盘，请重写")
            daily_review.save_verdict(day, daily_review.parse_verdict(text) or text)
        except Exception as exc:  # noqa: BLE001 - 失败落盘，下一轮最多重试三次
            logger.warning("daily review %s failed: %s", day, exc)
            daily_review.save_verdict(day, {"error": str(exc)[:300] or type(exc).__name__, "attempts": attempts})
        finally:
            with verdict_lock:
                verdict_writing.discard(day)

    def _start_verdict(*, force: bool = False, now: datetime | None = None) -> bool:
        now = now or datetime.now(bj)
        day = now.astimezone(bj).date().isoformat()
        with verdict_lock:
            if ctx.stop_auto.is_set() or day in verdict_writing:
                return False
            cached = daily_review.load_verdict(day) or {}
            attempts = int(cached.get("attempts") or 0)
            if not force and (cached.get("text") or attempts >= 3):
                return False
            verdict_writing.add(day)
        try:
            threading.Thread(target=_write_verdict, args=(day, attempts + 1), name="day-review-write", daemon=True).start()
        except Exception:
            with verdict_lock:
                verdict_writing.discard(day)
            raise
        return True

    @app.post("/api/today/review/verdict")
    def rewrite_daily_review() -> dict[str, bool]:
        return {"started": _start_verdict(force=True)}

    def _daily_review_tick(now: datetime | None = None) -> bool:
        now = (now or datetime.now(bj)).astimezone(bj)
        if not ctx.feature_on("team") or (now.hour, now.minute) < (9, 35):
            return False
        return _start_verdict(now=now)

    def _daily_review_loop() -> None:
        while not ctx.stop_auto.is_set():
            try:
                _daily_review_tick()
            except Exception as exc:  # noqa: BLE001 - 一次失败不杀掉每天的检查
                logger.warning("daily review tick: %s", exc)
            ctx.stop_auto.wait(600)

    from ... import x_analytics

    ctx.startup.append(lambda: threading.Thread(
        target=x_analytics.daily_loop, args=(config_dir() / "x-analytics", ctx.stop_auto),
        kwargs={"enabled": lambda: ctx.feature_on("xline")}, name="x-analytics", daemon=True,
    ).start())

    ctx.startup.append(lambda: threading.Thread(target=_daily_review_loop, name="day-review", daemon=True).start())
    app.state.daily_review_tick = _daily_review_tick

    @app.post("/api/today/review/proposal")
    def decide_review_proposal(body: ReviewProposalBody) -> dict[str, Any]:
        with ledger_lock:
            path = daily_review.ledger_path()
            try:
                # newline="" 保留账本原有换行，未修改的行逐字不变。
                with path.open(encoding="utf-8", newline="") as f:
                    old = f.read()
                proposals = daily_review.parse_ledger(old)["proposals"]
                updated = daily_review.set_proposal(old, body.index, body.decision, datetime.now(bj).date())
                with path.open("w", encoding="utf-8", newline="") as f:
                    f.write(updated)
            except (OSError, IndexError) as exc:
                raise ValueError(f"实验账本没改成：{exc}") from exc
            if updated != old:
                try:
                    check = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
                    if check.returncode == 0:
                        label = "试" if body.decision == "try" else "不试"
                        message = f"docs: 实验账本：{proposals[body.index]['idea'][:20]} → {label}"
                        subprocess.run(["git", "-C", str(path.parent), "add", "--", path.name], capture_output=True, text=True, check=True, timeout=10)
                        # 仅提交这份账本，不把用户已暂存的其他文件带进去。
                        subprocess.run(["git", "-C", str(path.parent), "commit", "-m", message, "--only", "--", path.name],
                                       capture_output=True, text=True, check=True, timeout=30)
                except Exception as exc:  # noqa: BLE001 - 文件已经写回，git 失败只记日志
                    logger.warning("daily review ledger commit failed: %s", exc)
        return get_daily_review()

    def _wendy_brief() -> tuple[dict[str, Any], str]:
        from ... import driver
        from . import wendy

        today = get_today()
        try:
            results = get_results()
        except Exception:  # noqa: BLE001 - 粉丝和本月触达读不到，账照样给
            results = None
        from ... import kpi_board

        try:
            board = "\n\n" + kpi_board.brief_text(get_kpi())
        except Exception:  # noqa: BLE001 - 战况读不到，账照样给
            board = ""
        return today, wendy.brief(today, get_reach(14), driver.now_item(today), results) + board + "\n\n" + daily_review.brief_text(get_daily_review())

    def _wendy_said() -> list[dict[str, Any]]:
        """她说过的话：微信那边定时发的（从 Hermes 的输出里读）和卡片里的对话，按时间排。"""
        from . import wendy

        desk = [{"who": m["who"], "source": m["source"], "label": "", "text": m["text"],
                 "at": _local(m["at"]).astimezone().isoformat(timespec="seconds")} for m in store.wendy_thread(40)]
        return sorted([*wendy.hermes_messages(), *desk], key=lambda m: m["at"])

    def _nudges(day: str) -> list[dict[str, Any]]:
        return [r for r in store.driver_log(day, "nudge") if r["day"] == day]

    @app.get("/api/wendy")
    def get_wendy() -> dict[str, Any]:
        from ... import driver

        today = get_today()
        said = _wendy_said()
        with wendy_lock:
            state = dict(wendy_state)
        return {"now": driver.now_item(today), "messages": said[-12:], "busy": state["busy"], "error": state["error"],
                "nudges": [{"at": r["at"]} for r in _nudges(today["day"])]}

    def _wendy_turn(message: str, page: str = "today", screen: str = "") -> None:
        from ..positioning import positioning
        from . import wendy

        try:
            _, brief_text = _wendy_brief()
            north = ""
            if page == "positioning":
                try:
                    north = positioning.read().get("markdown") or ""
                except Exception:  # noqa: BLE001 - 读不到定位就只按今天的账聊
                    north = ""
            text = wendy.run_turn(brief_text, _wendy_said()[:-1] if message else _wendy_said(), message, turn_fn=wendy_fn, north=north, screen=screen)
            store.add_wendy("wendy", text)
        except Exception as exc:  # noqa: BLE001 - 卡片里显示
            logger.warning("wendy turn failed: %s", exc)
            with wendy_lock:
                wendy_state["error"] = str(exc)[:300] or type(exc).__name__
        finally:
            with wendy_lock:
                wendy_state["busy"] = False

    @app.post("/api/wendy")
    def post_wendy(body: WendyBody) -> dict[str, Any]:
        """他在卡片里回她（空着发 = 让她看一眼现在）。工作台自己跑一轮，模型所有工具都关着。"""
        message = body.message.strip()
        if len(message) > 2000:
            raise ValueError("一次最多 2000 字")
        with wendy_lock:
            if wendy_state["busy"]:
                return {"started": False, "message": "Wendy 还在想上一条"}
            wendy_state.update(busy=True, error=None)
        if message:
            store.add_wendy("park", message)
        threading.Thread(target=_wendy_turn, args=(message, body.page, body.screen), name="wendy", daemon=True).start()
        return {"started": True}

    @app.get("/api/wendy/brief")
    def wendy_brief(review: bool = False) -> dict[str, Any]:
        """此刻的账，一段文字。卡片里的她和微信那边的她读的是同一段，两边说的数对得上。"""
        from . import wendy

        _, text = _wendy_brief()
        parts = [text, wendy.thread_brief(_wendy_said()[-12:])]
        if review:
            parts.append(wendy.review_brief(get_review()))
        return {"text": "\n\n".join(parts)}

    @app.get("/api/wendy/nudge")
    def wendy_nudge(wechat_at: str | None = None) -> dict[str, Any]:
        """要不要去微信催他。微信那边每半小时来问一次；wechat_at 是他最后一次在微信里说话的时间（那边才知道）。"""
        from . import wendy

        today = get_today()
        cell = today["days"][-1]
        pending = [name for key, name in wendy.KPI if cell.get(key) == "pending"]
        nudges = _nudges(today["day"])
        activity = [t for t in (_local(store.last_touch(today["day"])), _local(wechat_at)) if t]
        said = [m for m in _wendy_said() if m["who"] == "wendy"]
        contact = [t for t in (_local(said[-1]["at"]) if said else None, _local(nudges[-1]["at"]) if nudges else None) if t]
        verdict = wendy.nudge_due(datetime.now(), pending=pending, last_activity=max(activity) if activity else None,
                                  last_contact=max(contact) if contact else None, nudges_today=len(nudges))
        return {**verdict, "pending": pending, "nudges_today": len(nudges)}

    @app.post("/api/wendy/nudge")
    def wendy_nudged() -> dict[str, Any]:
        """微信那边真去催了：记一笔（一天的次数和两次之间的间隔都靠它）。这是她自己的记录，不是 作者 的数据。"""
        now = datetime.now()
        store.driver_mark(now.date().isoformat(), f"nudge:{now:%H:%M}", "nudge")
        return {"ok": True, "nudges_today": len(_nudges(now.date().isoformat()))}
