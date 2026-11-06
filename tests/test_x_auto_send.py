"""自动发送仅消费假 QA / API 回执，所有产物写测试目录。"""
from datetime import datetime
import json

import pytest

from content_studio.extras.xline import x_daily, x_qa
from content_studio.store import StudioStore
from test_x_line import client_factory  # noqa: F401

NOW = datetime(2026, 10, 11, 10, tzinfo=x_daily.BJ)
KEY = '2026-10-11'
TEXT = '把简单的事情重复做好，比不停换工具更重要。'


def seed(tmp_path, **fields):
    p = tmp_path / 'daily.json'
    post = dict(id='p', text=TEXT, state='pending', **fields)
    x_daily.save(p, {'days': {KEY: {'posts': [post]}}})
    return p, post


def result(**fields):
    return dict(text=TEXT, changes=[], dropped=[], complete=True, **fields)


@pytest.mark.parametrize('value_ok,expected,reason', [(True, 'approved', None), (False, 'rejected', '没过 QA：没有解法')])
def test_quote_auto_qa(tmp_path, value_ok, expected, reason):
    p, post = seed(tmp_path, long=True, quote_url='https://x.com/a/status/1', prep='ready')
    out = x_daily.apply_qa(p, KEY, 'p', seen=TEXT, result=result(value_ok=value_ok, value_issues=['没有解法']), now=NOW)
    assert out['state'] == expected and out['auto'] is True
    assert out['auto_reason'] == reason and out['decided_at'] == NOW.isoformat(timespec='seconds')


@pytest.mark.parametrize('fields,switch', [({'long': True, 'quote_url': 'u', 'prep': 'ready'}, 'quote'), ({}, 'short')])
def test_switch_off_and_qa_error_stay_pending(tmp_path, fields, switch):
    p, post = seed(tmp_path, **fields)
    assert x_daily.apply_qa(p, KEY, 'p', seen=TEXT, error='模型出错')['state'] == 'pending'
    out = x_daily.apply_qa(p, KEY, 'p', seen=TEXT, result=result(), auto_send={switch: False})
    assert out['state'] == 'pending' and not out.get('auto')
    view = x_daily.view(p, now=NOW, auto_send={switch: False})
    assert view['today']['posts'][0]['state'] == 'pending'
    assert view['today']['posts'][0]['auto'] is False


def test_short_skips_qa_and_goes_out(tmp_path):
    p, post = seed(tmp_path)
    assert x_daily.qa_next(p, NOW) is None  # 10/12 作者：短帖不要 QA
    d = {'posts': [post]}
    assert x_daily.auto_decide(d, now=NOW) and post['state'] == 'approved' and post['auto'] is True
    off = {'id': 'q', 'text': TEXT, 'state': 'pending'}
    assert not x_daily.auto_decide({'posts': [off]}, auto_send={'short': False}, now=NOW) and off['state'] == 'pending'
    prompts = []
    out = x_qa.run(TEXT, kind='短帖', short=True, rules='长文必须有标题', write_fn=lambda prompt: prompts.append(prompt) or json.dumps({
        'changes': [], 'intro': {'text': '我写下了这篇文章供大家参考'}, 'value': {'收藏': {'ok': False}}, 'complete': True}))
    assert out['text'] == TEXT and out['intro'] is None and 'value_ok' not in out
    assert '长文必须有标题' not in prompts[0] and '"value":' not in prompts[0]


@pytest.mark.parametrize('state', ['rejected', 'sent', 'sending'])
def test_manual_rejected_or_sent_untouched(tmp_path, state):
    p, post = seed(tmp_path, qa='ready')
    post['state'] = state
    x_daily.save(p, {'days': {KEY: {'posts': [post]}}})
    assert not x_daily.auto_decide({'posts': [post]})
    assert x_daily.apply_qa(p, KEY, 'p', seen=TEXT, result=result()) == post


def test_long_non_quote_stays_manual(tmp_path):
    p, post = seed(tmp_path, long=True, prep='ready', format='post')
    assert x_daily.apply_qa(p, KEY, 'p', seen=TEXT, result=result())['state'] == 'pending'


def test_ready_migration_tick_and_today_counts(tmp_path):
    p, post = seed(tmp_path, qa='ready', qa_complete=True)
    dropped = {**post, 'id': 'bad', 'quote_url': 'u', 'long': True, 'prep': 'ready', 'qa_complete': False, 'qa_issues': ['不通顺']}
    x_daily.save(p, {'days': {KEY: {'posts': [post, dropped]}}})
    calls = []
    x_daily.tick(p, now=NOW, post_fn=lambda text: calls.append(text) or {'url': 'u'}, record_fn=lambda row: None)
    view = x_daily.view(p, now=NOW)['today']
    assert calls == [TEXT] and view['auto_sent'] == 1 and view['auto_dropped'] == 1
    assert all('auto_reason' in row for row in view['posts'])


def test_settings_partial_defaults_preserve_saved_zero(tmp_path):
    store = StudioStore(tmp_path / 'db.sqlite3')
    assert store.settings()['x_counts']['own_short'] == 100
    store.update_settings({'x_counts': {'own_short': 0}, 'x_auto_send': {'quote': False}})
    assert store.settings()['x_counts']['own_short'] == 0
    assert store.settings()['x_auto_send'] == {'short': True, 'quote': False, 'reply': True}
    with store.tx() as conn:
        conn.execute('UPDATE settings SET value = ? WHERE key = ?', ('{"reply": false}', 'x_auto_send'))
    assert store.settings()['x_auto_send'] == {'short': True, 'quote': True, 'reply': False}


def test_route_short_qa_uses_lightweight_path(client_factory):
    calls = []
    client = client_factory(write_fn=lambda prompt: calls.append(prompt) or '{"changes": [], "complete": true}', x_fetch_fn=lambda url: [])
    key = x_daily.day_key(x_daily.now_bj())
    post = {'id': 's', 'text': TEXT, 'state': 'pending'}
    x_daily.save(x_daily.path(), {'days': {key: {'posts': [post]}}})
    client.app.state.x_long_qa(key, post)
    got = x_daily.load(x_daily.path())['days'][key]['posts'][0]
    assert got['state'] == 'approved' and got['auto']
    assert '没有标题和长文结构要求' in calls[0]


def test_rechecking_auto_approval_error_returns_pending(tmp_path):
    p, post = seed(tmp_path, long=True, quote_url='u', prep='ready')
    x_daily.apply_qa(p, KEY, 'p', seen=TEXT, result=result())
    got = x_daily.apply_qa(p, KEY, 'p', seen=TEXT, error='模型失败')
    assert got['state'] == 'pending' and got['qa'] == 'failed'
    assert x_daily.view(p, now=NOW)['today']['posts'][0]['state'] == 'pending'


def test_saved_ten_shorts_become_fifty_once(tmp_path):
    store = StudioStore(tmp_path / 'db.sqlite3')
    with store.tx() as conn:
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('x_counts', ?)", (json.dumps({'long': 10, 'post_share': 0.5, 'own_short': 10, 'hot': 20}),))
    assert store.settings()['x_counts']['own_short'] == 100  # 10/12 晚统一改成 100
    store.update_settings({'x_counts': {'own_short': 10}})  # 他自己改回 10：不再被改
    assert store.settings()['x_counts']['own_short'] == 10
