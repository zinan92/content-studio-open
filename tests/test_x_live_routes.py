"""X 页集成只使用临时数据库和注入函数。"""
from datetime import datetime
import json

import pytest

from content_studio.extras.xline import x_daily, x_replies, xhot
from content_studio.store import StudioStore
from test_x_line import client_factory  # noqa: F401


def test_live_route_settings_and_sampler(client_factory, tmp_path, monkeypatch):
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    client = client_factory()
    out = client.put('/api/settings', json={'x_kpi': {'posts': 19}, 'reply_gap_minutes': 5,
                                          'park_writing_skill': str(tmp_path/'skill.md')})
    assert out.status_code == 200
    calls = []
    def get(url, query):
        calls.append(url)
        return {'data': {'id': 'u', 'public_metrics': {'followers_count': 100}}} if url.endswith('/me') else {
            'data': [{'id': '1', 'created_at': now.isoformat(), 'public_metrics': {'impression_count': 120}}]}
    assert client.app.state.x_live_tick(now=now, get=get)
    assert not client.app.state.x_live_tick(now=now, get=lambda *a: pytest.fail('duplicate paid read'))
    assert len(calls) == 3  # me、今天的帖子、最近 72 小时原创
    data = client.get('/api/xline/live').json()
    assert data['kpi'][0]['target'] == 19
    assert 'impressions_basis' in data and 'followers_hourly' in data
    assert client.put('/api/settings', json={'x_kpi': {'replies_min': 201, 'replies_max': 200}}).status_code == 400
    assert client.put('/api/settings', json={'reply_gap_minutes': 0}).status_code == 400


def test_replies_halt_reaches_page_and_wendy(client_factory, tmp_path, monkeypatch):
    from content_studio import daily_review
    now = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
    original_now = x_daily.now_bj
    monkeypatch.setattr(x_daily, 'now_bj', lambda value=None: original_now(value or now))
    monkeypatch.setattr(xhot.Board, 'rising', lambda self: {'items': []})
    monkeypatch.setattr(xhot.Board, 'get', lambda *args: {'items': []})
    monkeypatch.setattr(x_replies, 'path', lambda: tmp_path/'replies.json')
    (tmp_path/'replies.json').write_text(json.dumps({'days': {'2026-10-11': {'1': {
        'draft': '先用失败样本验证结果。', 'state': 'draft', 'text': 'AI工具'}}}}))
    sent = []
    def post(text, **kwargs):
        sent.append((text, kwargs))
        return {'status': 403, 'detail': 'automated action restricted'}
    client = client_factory(x_post_fn=post)
    assert client.post('/api/xline/replies/approve-all', json={'edits': {'1': '先用失败样本验证，再谈规模。'}}).json()['approved'] == 1
    assert client.app.state.x_replies_tick(now=now)['state'] == 'failed'
    assert client.app.state.x_replies_tick(now=now) is None
    assert len(sent) == 1 and sent[0][1] == {'in_reply_to_tweet_id': '1'}
    stopped = client.get('/api/xline/replies').json()['halted_message']
    assert stopped.startswith('X 拦了回复：') and stopped.endswith('，今天停了')
    assert client.get('/api/xline/live').json()['halted_message'] == stopped
    review = daily_review.x_yesterday(tmp_path/'s.sqlite3', tmp_path/'queue.json', today=now.date(), analytics_root=tmp_path/'analytics')
    assert stopped in '\n'.join(daily_review.x_brief(review))
    assert '昨天 KPI' in '\n'.join(daily_review.x_brief(review))
