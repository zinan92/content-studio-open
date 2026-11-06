"""Moving handlers must preserve both route coverage and first-match dispatch."""
import json
from pathlib import Path
import re
from starlette.routing import Match
from tests.test_web import client  # noqa: F401


def test_split_preserves_all_route_dispatch(client):
    got = {}
    for route in client.app.routes:
        path = getattr(route, 'path', '')
        if not path.startswith('/api/'):
            continue
        for method in sorted(getattr(route, 'methods', []) or []):
            scope = {'type': 'http', 'path': re.sub(r'\{[^}:]+(:path)?\}', '7', path), 'method': method, 'root_path': ''}
            hit = next((r for r in client.app.routes if r.matches(scope)[0] == Match.FULL), None)
            got[f'{method} {path}'] = hit.endpoint.__name__ if hit else None
    expected = json.loads((Path(__file__).parent / 'fixtures/routes-before-split.json').read_text())
    # 本次新增路由单独列出，旧拆分快照继续逐条守住原来的分派。
    expected.update({
        # 10/13：润色改走批注视图（POST /polish 还叫 start_polish，搬进了 xline）
        'GET /api/topics/{topic_id}/polish': 'get_topic_polish',
        'POST /api/topics/{topic_id}/polish/trk': 'all_topic_polish',
        'POST /api/topics/{topic_id}/polish/trk/budget': 'budget_topic_polish',
        'POST /api/topics/{topic_id}/polish/trk/rescore': 'rescore_topic_polish',
        'POST /api/topics/{topic_id}/polish/trk/undo': 'undo_topic_polish',
        'POST /api/topics/{topic_id}/polish/trk/{cid}': 'status_topic_polish',
        'POST /api/xline/replies/retry-api': 'retry_x_reply_api',
        'POST /api/xline/replies/{tweet_id}/handed': 'hand_x_reply',
        'POST /api/xline/daily/{key}/{post_id}/handed': 'handed_x_quote',
        'POST /api/xline/daily/{key}/{post_id}/qa/rerun': 'rerun_x_qa',
        'POST /api/xline/daily/{key}/{post_id}/trk': 'set_all_x_trk',
        'POST /api/xline/daily/{key}/{post_id}/trk/rescore': 'rescore_x_trk',
        'POST /api/xline/daily/{key}/{post_id}/trk/undo': 'undo_x_trk',
        'POST /api/xline/daily/{key}/{post_id}/trk/summary': 'toggle_x_trk_summary',
        'POST /api/xline/daily/{key}/{post_id}/trk/budget': 'set_x_trk_budget',
        'GET /api/topics/{topic_id}/script': 'get_topic_script',
        'PUT /api/topics/{topic_id}/mode': 'put_topic_mode',
        'POST /api/topics/{topic_id}/script': 'start_topic_script',
        'POST /api/topics/{topic_id}/script/trk': 'all_topic_script',
        'POST /api/topics/{topic_id}/script/trk/budget': 'budget_topic_script',
        'POST /api/topics/{topic_id}/script/trk/rescore': 'rescore_topic_script',
        'POST /api/topics/{topic_id}/script/trk/undo': 'undo_topic_script',
        'POST /api/topics/{topic_id}/script/trk/{cid}': 'status_topic_script',
        'POST /api/xline/daily/{key}/{post_id}/trk/{cid}': 'set_x_trk',
        'GET /api/xline/write/module': 'write_module_info',
        'PUT /api/xline/write/flow': 'set_write_flow',
        'POST /api/xline/quotes/retry-api': 'retry_x_quotes',
        'POST /api/xline/picks/{key}/{pick_id}': 'choose_x_pick',
        'POST /api/xline/daily/{key}/{post_id}/draft': 'draft_x_article',
        'POST /api/xline/value/{key}/own': 'x_value_own',
        'POST /api/xline/value/{key}/{post_id}': 'x_value_action',
        'GET /api/kpi': 'api_kpi',
        'PUT /api/kpi/targets': 'put_kpi_targets',
        # 10/13：排期选题池「+ 口述一条」
        'POST /api/schedule/oral': 'new_oral',
        # 10/13：拍后批注
        'GET /api/topics/{topic_id}/review': 'get_topic_review',
        'POST /api/topics/{topic_id}/review': 'start_topic_review',
        'GET /api/review/latest': 'latest_review',
        # 10/17：素材 Agent（extras/materials）
        'GET /api/material-agent': 'overview',
        'POST /api/material-agent/learn': 'learn',
        'POST /api/material-agent/jobs/{job_id}/retry': 'retry',
        'GET /api/material-agent/sources/{sid}': 'deck',
        'POST /api/material-agent/sources/{sid}/cards/{name}': 'mark',
        'POST /api/material-agent/sources/{sid}/push': 'push',
        'POST /api/material-agent/sources/{sid}/internalize': 'internalize',
        # 10/18：知识树 · 内化（extras/tree）
        'GET /api/tree': 'tree_view',
        'POST /api/tree/internalize': 'tree_internalize',
        'POST /api/tree/jobs/{jid}/retry': 'tree_retry',
        # 10/18：朋友圈 · X 复刻到小号（extras/moments）
        'GET /api/moments': 'moments_view',
        'POST /api/moments/check': 'moments_check',
        'POST /api/moments/add': 'moments_add',
        'POST /api/moments/{pid}/replicate': 'moments_replicate',
        'GET /api/moments/{pid}/pack': 'moments_pack',
        'POST /api/moments/{pid}/wechat': 'moments_wechat',
        'GET /api/moments/{pid}/img/{name}': 'moments_image',
        # 10/18：AI 排动效（extras/motion）
        'GET /api/topics/{topic_id}/motion-plan': 'get_motion_plan',
        'POST /api/topics/{topic_id}/motion-plan': 'make_motion_plan',
        'PUT /api/topics/{topic_id}/motion-plan/beats/{index}': 'swap_motion_beat',
        'GET /api/topics/{topic_id}/motion-plan.json': 'export_motion_plan',
        'POST /api/topics/{topic_id}/motion-plan/hand-off': 'hand_off_motion_plan',
        # 10/18：素材页（extras/materials）
        'GET /api/sucai': 'sucai_list',
        # 10/19：这次怎么剪（blocks/produce/video）
        'GET /api/topics/{topic_id}/video-project/plan': 'get_cut_plan',
        'PUT /api/topics/{topic_id}/video-project/plan': 'put_cut_plan',
        'POST /api/topics/{topic_id}/video-project/plan/start': 'start_cut_plan',
        # 10/19：只剪 Hook 页面上切（blocks/produce/video + hookcut）
        'GET /api/topics/{topic_id}/video-project/hook-clips': 'hook_clips_state',
        'POST /api/topics/{topic_id}/video-project/hook-clips': 'hook_clips_start',
        # 10/19：拿掉排期，选题 →「我的选题」
        'GET /api/my-topics': 'topic_pool',
        # 10/20：抖音连不上时在工作台里重新登录（blocks/setup/settings）
        'POST /api/douyin/login': 'douyin_login_start',
        'GET /api/douyin/login': 'douyin_login_state',
    })
    assert got == expected


def test_startup_starts_the_same_background_loops_as_before_the_split(tmp_path, monkeypatch):
    """拆分前开机起的后台线程：日结、X 短帖、X 长文、其他三个自动发，外加两个续跑定时器；10/11 新增每日复盘。
    这些现在一部分由能力积木登记；挂错了不会报错，只会悄悄不跑（21:00 不排 X 短帖、B 站不自动发）。"""
    import threading

    from fastapi.testclient import TestClient

    from content_studio import web

    started, timers = [], []

    class FakeThread:
        def __init__(self, *args, target=None, name=None, daemon=None, **kw):
            self.name = name

        def start(self):
            started.append(self.name)

    class FakeTimer:
        def __init__(self, interval, function, *args, **kw):
            self.fn = function

        def start(self):
            timers.append(self.fn.__name__)

    class FakeWorker:
        def start(self):
            pass

        def stop(self):
            pass

        def notify(self):
            pass

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(threading, "Thread", FakeThread)
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    cookie = tmp_path / "c.json"
    cookie.write_text("{}")
    cookie.chmod(0o600)
    app = web.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                         downloads_dir=tmp_path / "dl", drafts_dir=tmp_path / "dr", worker=FakeWorker(), start_worker=True)
    with TestClient(app):
        pass
    assert {"day-close", "x-daily", "x-long", "others-auto", "day-review"} <= set(started), started
    assert not {"x-live", "x-replies-send"} & set(started)  # 10/20 作者：X 的 API 拿掉，不再每小时读、不再自动回复
    assert {"_pack_resume_all", "_schedule_write_resume"} <= set(timers), timers
