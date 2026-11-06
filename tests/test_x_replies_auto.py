from datetime import datetime, timedelta
import json

import pytest

from content_studio.extras.xline import x_daily, x_replies

NOW = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)


@pytest.fixture(autouse=True)
def park_lines(monkeypatch):
    """10/12 起回复只用他的原话；这里的老测试测别的（格式、节奏、风控），原话检索和核对用假的放行，专门的测试在 test_x_replies_grounded.py。"""
    monkeypatch.setattr(x_replies, "raw_lines", lambda root: [{"text": "工具需要验证结果才能用", "note": "003_原始输出/a.md"}])
    monkeypatch.setattr(x_replies, "match_lines", lambda text, lines, k=6: list(lines))
    monkeypatch.setattr(x_replies, "grounded", lambda text, chosen: True)
KEY = '2026-10-11'


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(x_replies, 'path', lambda: tmp_path / 'replies.json')


def item(tid):
    return {'url': f'https://x.com/user/status/{tid}', 'author': '作者',
            'text': '工具需要验证' * 20, 'category': 'AI',
            'published_at': (NOW - timedelta(hours=1)).isoformat()}


def model(*args):
    originals = json.loads(args[1].split('原帖：\n')[1])
    return {'text': json.dumps({'replies': [{'id': r['id'], 'text': '先验证失败样本，再判断工具。'} for r in originals]})}


def seed(count=2, state='approved', **extra):
    data = {'days': {KEY: {str(i): {**item(i), 'draft': '先验证失败样本。', 'state': state}
                           for i in range(1, count + 1)}}, **extra}
    x_daily.save(x_replies.path(), data)


def test_auto_draft_approved_and_invalid_not_queued():
    assert x_replies.draft([item(1)], soul='', style='', turn_fn=model, auto=True, now=NOW) == 1
    row = x_replies.view([], now=NOW)['next']
    assert row['state'] == 'approved' and row['auto'] is True
    assert x_replies.draft([item(2)], soul='', style='', auto=True, now=NOW,
                           turn_fn=lambda *a: {'text': '{"replies":[{"id":"2","text":"真的吗？"}]}'}) == 0
    assert x_replies.view([], now=NOW)['queue'] == 1


def test_blocked_api_degrades_persistently_and_retry_resumes():
    seed()
    calls = []
    def blocked(*a, **k):
        calls.append(1)
        raise RuntimeError('403 You are not allowed to reply to this post')
    assert x_replies.tick(post_fn=blocked, now=NOW)['state'] == 'failed'
    data = x_daily.load(x_replies.path())
    assert data['api_blocked']['reason'] == '403 You are not allowed to reply to this post'
    assert data['days'][KEY]['2']['state'] == 'ready'
    assert not data.get('halted')
    assert x_replies.tick(post_fn=blocked, now=NOW + timedelta(days=1)) is None
    assert len(calls) == 1
    x_replies.draft([item(3)], soul='', style='', turn_fn=model, auto=True, now=NOW)
    assert x_replies.view([], now=NOW)['items'][-1]['state'] == 'ready'
    x_replies.retry_api()
    assert x_replies.tick(post_fn=lambda *a, **k: {'id': '123'}, now=NOW + timedelta(minutes=5))['state'] == 'sent'


def test_rate_limit_still_halts_only_day():
    seed()
    x_replies.tick(post_fn=lambda *a, **k: {'status': 429, 'error': 'reply rate exceeded'}, now=NOW)
    data = x_daily.load(x_replies.path())
    assert data['halted'][KEY] and not data.get('api_blocked')


def test_view_manual_handed_and_real_sent():
    seed(state='ready', api_blocked={'at': NOW.isoformat(), 'reason': 'blocked'})
    got = x_replies.view([], now=NOW)
    assert got['mode'] == 'manual' and got['queue'] == 2 and got['next_at'] is None
    assert got['next']['author'] == '作者' and got['next']['draft'] and got['next']['url']
    x_replies.handed('1', now=NOW)
    got = x_replies.view([], now=NOW)
    assert got['queue'] == 1 and got['sent'] == 0
    assert got['done_today'][0]['id'] == '1' and len(got['done_today'][0]['text']) == 40
    with pytest.raises(ValueError):
        x_replies.handed('1', now=NOW)
    x_replies.retry_api()
    x_replies.tick(post_fn=lambda *a, **k: {'id': '100'}, now=NOW + timedelta(minutes=5))
    got = x_replies.view([], now=NOW)
    assert [r['state'] for r in got['done_today']] == ['sent', 'handed']
    assert got['sent'] == 1


def test_view_next_time_matches_tick_gap():
    seed()
    x_replies.tick(post_fn=lambda *a, **k: {'id': '100'}, now=NOW)
    assert x_replies.view([], now=NOW, settings={'reply_gap_minutes': 7})['next_at'] == '10:07'


@pytest.mark.parametrize('hour, expected', [(8, False), (9, True), (22, True), (23, False)])
def test_auto_draft_window(hour, expected):
    assert x_replies.auto_draft_due(settings={}, now=NOW.replace(hour=hour)) is expected


@pytest.mark.parametrize('extra, settings, count, expected', [
    ({}, {}, 5, False),
    ({'halted': {KEY: '429'}}, {}, 0, False),
    ({'api_blocked': {'reason': '403'}}, {}, 0, True),
    ({}, {'x_auto_send': {'reply': False}}, 0, False),
    ({}, {'x_kpi': {'replies_max': 0}}, 0, False),
    ({'halted': {'2026-10-10': '429'}}, {}, 0, True),
])
def test_auto_draft_gates(extra, settings, count, expected):
    seed(count=count, **extra)
    calls = []
    def fake(*a):
        calls.append(1)
        return model(*a)
    assert x_replies.auto_draft_due(settings=settings, now=NOW) is expected
    x_replies.auto_draft([item(99)], soul='', style='', turn_fn=fake, settings=settings, now=NOW)
    assert bool(calls) is expected


def test_auto_draft_cooldown_limit_and_blocked_manual_queue():
    seed(count=0, api_blocked={'reason': '403'})
    assert x_replies.auto_draft([item(i) for i in range(1, 25)], soul='', style='', turn_fn=model, settings={}, now=NOW) == 20
    assert x_replies.view([], now=NOW)['queue'] == 20
    data = x_daily.load(x_replies.path())
    assert all(r['state'] == 'ready' for r in data['days'][KEY].values())
    data['days'] = {}
    x_daily.save(x_replies.path(), data)
    assert not x_replies.auto_draft_due(settings={}, now=NOW + timedelta(minutes=29))
    assert x_replies.auto_draft_due(settings={}, now=NOW + timedelta(minutes=30))


from test_x_line import client_factory  # noqa: E402, F401


@pytest.fixture
def route_sources(monkeypatch):
    from content_studio.extras.xline import xhot, xops
    monkeypatch.setattr(xhot.Board, 'rising', lambda self: {'items': [item(99)]})
    monkeypatch.setattr(xhot.Board, 'get', lambda *a, **k: {'items': []})
    monkeypatch.setattr(x_replies, 'load_style', lambda _: '测试风格')
    monkeypatch.setattr(xops, 'soul', lambda: {'text': '测试角色'})
    original_now = x_daily.now_bj
    monkeypatch.setattr(x_daily, 'now_bj', lambda now=None: original_now(now or NOW))


def wait_idle(client):
    import time
    for _ in range(200):
        result = client.get('/api/xline/replies').json()
        if not result['busy']:
            return result
        time.sleep(.01)
    pytest.fail('后台回复线程没有结束')


def test_handed_and_retry_routes(client_factory, route_sources):
    seed(state='ready', api_blocked={'reason': '403'})
    client = client_factory(anna_fn=model)
    got = client.post('/api/xline/replies/1/handed')
    assert got.status_code == 200
    assert got.json()['reply']['state'] == 'handed'
    assert got.json()['reply']['handed_at'].startswith(KEY)
    assert client.post('/api/xline/replies/1/handed').status_code == 400
    assert client.post('/api/xline/replies/999/handed').status_code == 400
    view = client.get('/api/xline/replies').json()
    assert view['mode'] == 'manual' and view['queue'] == 1
    assert view['done_today'][0]['id'] == '1'
    assert client.post('/api/xline/replies/retry-api').json() == {'ok': True}
    view = client.get('/api/xline/replies').json()
    assert view['mode'] == 'api' and view['api_blocked'] is None
    assert view['next']['state'] == 'approved'


def test_auto_draft_route_thread_busy_and_cooldown(client_factory, route_sources):
    import threading
    entered, release = threading.Event(), threading.Event()
    calls = []
    def fake(*args):
        calls.append(threading.current_thread().name)
        entered.set()
        assert release.wait(2)
        return model(*args)
    client = client_factory(anna_fn=fake)
    try:
        assert client.app.state.x_replies_auto_draft(now=NOW)
        assert entered.wait(2)
        assert client.get('/api/xline/replies').json()['busy']
        # Even beyond the persistent cooldown, an active worker prevents reentry.
        assert not client.app.state.x_replies_auto_draft(now=NOW + timedelta(hours=1))
        assert client.post('/api/xline/replies/draft').json() == {'started': False}
    finally:
        release.set()
    got = wait_idle(client)
    assert got['error'] is None and got['next']['state'] == 'approved' and got['next']['auto']
    assert calls == ['x-replies-auto']
    assert not client.app.state.x_replies_auto_draft(now=NOW + timedelta(minutes=29))
    assert client.app.state.x_replies_auto_draft(now=NOW + timedelta(minutes=30))
    wait_idle(client)
    assert calls == ['x-replies-auto']  # Existing drafts are not generated again.


def test_auto_draft_route_failure_clears_busy_and_reports_error(client_factory, route_sources):
    def fail(*args):
        raise RuntimeError('假模型失败')
    client = client_factory(anna_fn=fail)
    assert client.app.state.x_replies_auto_draft(now=NOW)
    got = wait_idle(client)
    assert not got['busy'] and got['error'] == '假模型失败'
    assert not client.app.state.x_replies_auto_draft(now=NOW + timedelta(minutes=29))
    assert client.app.state.x_replies_auto_draft(now=NOW + timedelta(minutes=30))
    assert wait_idle(client)['error'] == '假模型失败'


def test_unknown_403_wording_still_switches_to_manual_cards():
    seed()
    x_replies.approve_all()
    def send(*a, **kw):
        raise RuntimeError('X 返回 403：{"detail":"Forbidden"}')
    assert x_replies.tick(post_fn=send, now=NOW)["state"] == "failed"
    data = x_replies.x_daily.load(x_replies.path())
    assert data["api_blocked"] and not data.get("halted")
