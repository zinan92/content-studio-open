from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from content_studio import rawtidy, vault


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('CONTENT_STUDIO_HOME', str(tmp_path / 'config'))
    root = tmp_path / 'vault'
    raw = root / '003_原始输出'
    raw.mkdir(parents=True)
    git(root, 'init')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'commit.gpgsign', 'false')
    def note(name, text=None, date='2026-01-02'):
        p = raw / name
        p.parent.mkdir(parents=True, exist_ok=True)
        # 每段独立四字组，缺一段就会真正降低覆盖率。
        body = text if text is not None else '\n\n'.join(''.join(chr(0x4e00 + j * 400 + k) for k in range(300)) for j in range(3))
        p.write_text(f'---\ndate: {date}\n---\n{body}', encoding='utf-8')
        return p.relative_to(root).as_posix()
    return SimpleNamespace(root=root, raw=raw, note=note, records=tmp_path / 'config/rawtidy.json')


def merge(notes, title='主线', bridge=None):
    parts = [{'note': n, 'paragraph': p} for n, src in enumerate(notes, 1) for p in range(1, len(rawtidy.paragraphs(src['body'])) + 1)]
    if bridge is not None:
        parts.insert(3, {'bridge': bridge})
    return {'type': 'merge', 'sources': [n['path'] for n in notes], 'mainline': '把经历连起来',
            'outputs': [{'title': title, 'parts': parts}]}


def setup_merge(env):
    env.note('主题/甲.md')
    env.note('主题/乙.md', date='2025-02-03')
    git(env.root, 'add', '.')
    git(env.root, 'commit', '-m', 'initial')
    notes = rawtidy.select_notes(env.root, env.raw)
    return notes, merge(notes, bridge='接着回到实际经历看看这些判断如何慢慢形成了')


def model_for(*plans):
    replies = iter([
        [{k: p[k] for k in ('type', 'sources', 'mainline') if k in p} for p in plans],
        *[{'outputs': p['outputs']} for p in plans],
    ])
    return lambda _: json.dumps(next(replies), ensure_ascii=False)


def test_selection(env):
    allowed = env.note('保留.md')
    env.note('系列甲/篇.md')
    env.note('主题/系列乙/篇.md')
    env.note('_整理前/篇.md')
    env.note('短.md', '太短')
    env.note('客户.md')
    env.note('标题过滤.md', '# 咨询记录\n' + '长内容' * 100)
    topic = env.note('选题.md')
    daily = env.note('每日.md')
    used = env.note('已用.md')
    skipped = env.note('放一边.md')
    rows = rawtidy.select_notes(env.root, env.raw, topics=[{'note_paths': [topic]}],
        daily={'days': {'old': {'posts': [{'state': 'sent', 'source_id': 'obsidian:' + daily}]}}},
        x_state={'posts': [{'source_id': 'obsidian:' + used}], 'skipped': ['obsidian:' + skipped]})
    assert {r['path'] for r in rows} == {allowed, used, skipped}


@pytest.mark.parametrize('offset', [-30, -1, 0, 1, 2])
@pytest.mark.parametrize('state', ['sent', 'sending', 'unsure', 'pending', 'approved',
                                    'expired', 'rejected', 'swapped', 'moved', 'failed'])
def test_used_paths_only_active_references(monkeypatch, offset, state):
    from content_studio.extras.xline import x_daily
    # UTC 仍是前一天，按北京时间的今天判断。
    now = datetime(2026, 10, 10, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(x_daily, 'now_bj', lambda: now.astimezone(x_daily.BJ))
    day = (now.astimezone(x_daily.BJ).date() + timedelta(days=offset)).isoformat()
    daily = {'days': {day: {'posts': [{'state': state, 'source_id': 'obsidian:素材.md'},
                                    {'state': state, 'source_id': 'github:repo'}]}}}
    used = rawtidy.used_paths([{'note_paths': ['选题.md']}], daily,
                             {'skipped': ['obsidian:放一边.md'],
                              'posts': [{'source_id': 'obsidian:候选.md'}]})
    expected = {'选题.md'}
    if state in {'sent', 'sending', 'unsure'} or (offset in (0, 1) and state in {'pending', 'approved'}):
        expected.add('素材.md')
    assert used == expected


def test_merge_commit_and_undo(env):
    notes, plan = setup_merge(env)
    (env.root / 'unrelated.md').write_text('unrelated')
    git(env.root, 'add', 'unrelated.md')
    calls = []
    reply = model_for(plan)
    def model(prompt):
        calls.append(prompt)
        return reply(prompt)
    group = rawtidy.propose(notes, write_fn=model)[0]
    assert len(calls) == 2 and group['status'] == 'ready'
    row = rawtidy.apply(group, records_path=env.records)
    new = env.root / row['new_files'][0]
    meta, body = vault.parse_frontmatter(new.read_text())
    assert body.rstrip() == group['outputs'][0]['body']
    assert meta['date'] == '2025-02-03' and meta['tidied_by'] == 'claude'
    assert meta['type'] == '合并' and meta['title'] == '主线'
    assert row['change_ratio'] <= .05 and row['coverage'] >= .9
    assert len(row['outputs'][0]['preview']) == 200
    assert all(not (env.root / n['path']).exists() for n in notes)
    assert all((env.root / p).is_file() for p in row['backups'])
    changed = set(git(env.root, '-c', 'core.quotepath=false', 'show', '--format=', '--name-only', '--no-renames', 'HEAD').splitlines())
    assert changed == set(row['sources'] + row['new_files'] + row['backups'])
    assert git(env.root, 'diff', '--cached', '--name-only') == 'unrelated.md'
    result = rawtidy.undo(row['id'], records_path=env.records)
    assert result['undone'] and result['undo_commit'] != row['commit']
    assert not new.exists()
    assert list(env.raw.rglob('_撤回的新笔记/*/003_原始输出/主题/主线.md'))
    assert all((env.root / n['path']).read_text() == n['_snapshot'] for n in notes)
    assert json.loads(env.records.read_text())['records'][0]['undone']
    assert '撤回整理' in git(env.root, 'log', '-1', '--format=%s')
    assert git(env.root, 'diff', '--cached', '--name-only') == 'unrelated.md'


@pytest.mark.parametrize('failure', ['long', 'number', 'coverage', 'ratio', 'index', 'duplicate'])
def test_invalid_group_does_not_block_other(env, failure):
    notes, valid = setup_merge(env)
    invalid = merge(notes)
    if failure in ('long', 'number', 'ratio'):
        bridge = {'long': '很' * 31, 'number': '再看 2026 年', 'ratio': '衔接文字' * 7}[failure]
        for _ in range(10 if failure == 'ratio' else 1):
            invalid['outputs'][0]['parts'].append({'bridge': bridge})
    elif failure == 'coverage':
        invalid['outputs'][0]['parts'] = [{'note': 1, 'paragraph': 1}]
    elif failure == 'index':
        invalid['outputs'][0]['parts'][0]['paragraph'] = 0
    else:
        invalid['outputs'][0]['parts'].append({'note': 1, 'paragraph': 1})
    result = rawtidy.propose(notes, write_fn=model_for(invalid, valid))
    assert result[0]['status'] == 'discarded' and result[0]['reason']
    assert result[1]['status'] == 'ready'
    assert rawtidy.apply(result[1], records_path=env.records)['commit']


def test_split(env):
    env.note('原篇.md')
    notes = rawtidy.select_notes(env.root, env.raw)
    plan = {'type': 'split', 'sources': [notes[0]['path']], 'outputs': [
        {'title': '话题甲', 'parts': [{'note': 1, 'paragraph': 1}]},
        {'title': '话题乙', 'parts': [{'note': 1, 'paragraph': p} for p in [2, 3]]}]}
    group = rawtidy.propose(notes, write_fn=model_for(plan))[0]
    row = rawtidy.apply(group, records_path=env.records)
    assert len(row['new_files']) == 2 and row['coverage'] >= .9
    assert all(vault.parse_frontmatter((env.root / p).read_text())[0]['type'] == '拆分' for p in row['new_files'])


def test_collision_and_source_edit_preserve_files(env):
    notes, plan = setup_merge(env)
    group = rawtidy.propose(notes, write_fn=model_for(plan))[0]
    target = env.raw / '主题/主线.md'
    target.write_text('既有内容')
    with pytest.raises(ValueError, match='同名'):
        rawtidy.apply(group, records_path=env.records)
    assert target.read_text() == '既有内容'
    target.unlink()
    original = env.root / notes[0]['path']
    original.write_text('刚编辑过')
    with pytest.raises(ValueError, match='变化'):
        rawtidy.apply(group, records_path=env.records)
    assert original.read_text() == '刚编辑过'


def test_api_single_run_and_ratios(env):
    notes, plan = setup_merge(env)
    entered, release = threading.Event(), threading.Event()
    reply = model_for(plan)
    def model(prompt):
        entered.set()
        assert release.wait(5)
        return reply(prompt)
    app = FastAPI()
    ctx = SimpleNamespace(places=SimpleNamespace(vault_path=lambda: str(env.root), raw_root=lambda: env.raw),
        store=SimpleNamespace(topics=lambda **_: []), data_dir=env.records.parent, write_fn=model)
    rawtidy.register(app, ctx)
    client = TestClient(app)
    assert client.post('/api/rawtidy/run', json={'limit': 6}).status_code == 422
    try:
        assert client.post('/api/rawtidy/run', json={'limit': 5}).status_code == 200
        assert entered.wait(2)
        assert client.get('/api/rawtidy').json()['busy']
        assert client.post('/api/rawtidy/run', json={'limit': 5}).status_code == 409
        assert client.post('/api/rawtidy/unknown/undo').status_code == 409
    finally:
        release.set()
    for _ in range(200):
        data = client.get('/api/rawtidy').json()
        if not data['busy']:
            break
        time.sleep(.01)
    assert not data['busy'] and data['error'] is None
    assert data['results'][0]['status'] == 'applied'
    row = data['records'][0]
    assert row['change_ratio'] <= .05 and row['coverage'] >= .9
    assert client.post(f'/api/rawtidy/{row["id"]}/undo').json()['undone']
    assert client.get('/api/rawtidy').json()['records'][0]['undone']


def test_failed_record_write_rolls_back(env, monkeypatch):
    notes, plan = setup_merge(env)
    group = rawtidy.propose(notes, write_fn=model_for(plan))[0]
    def fail(*_):
        raise OSError('disk full')
    monkeypatch.setattr(rawtidy, '_save', fail)
    with pytest.raises(OSError):
        rawtidy.apply(group, records_path=env.records)
    assert all((env.root / n['path']).read_text() == n['_snapshot'] for n in notes)
    assert not (env.raw / '主题/主线.md').exists()
    assert git(env.root, 'log', '-1', '--format=%s') == 'initial'


def test_git_failure_is_logged_but_undo_remains_available(env, monkeypatch, caplog):
    notes, plan = setup_merge(env)
    group = rawtidy.propose(notes, write_fn=model_for(plan))[0]
    run = subprocess.run
    def fail_commit(args, **kwargs):
        if 'commit' in args:
            raise subprocess.CalledProcessError(1, args)
        return run(args, **kwargs)
    monkeypatch.setattr(rawtidy.subprocess, 'run', fail_commit)
    row = rawtidy.apply(group, records_path=env.records)
    assert row['commit'] is None and 'Git 提交失败' in caplog.text
    assert json.loads(env.records.read_text())['records'][0]['id'] == row['id']
    assert rawtidy.undo(row['id'], records_path=env.records)['undone']


def test_undo_collision_leaves_everything_in_place(env):
    notes, plan = setup_merge(env)
    row = rawtidy.apply(rawtidy.propose(notes, write_fn=model_for(plan))[0], records_path=env.records)
    occupied = env.root / row['sources'][0]
    occupied.write_text('新的内容')
    with pytest.raises(ValueError, match='同名'):
        rawtidy.undo(row['id'], records_path=env.records)
    assert occupied.read_text() == '新的内容'
    assert all((env.root / p).is_file() for p in row['new_files'] + row['backups'])
    assert not json.loads(env.records.read_text())['records'][0]['undone']


def test_untracked_sources_commit_in_new_vault(env):
    env.note('甲.md')
    env.note('乙.md')
    notes = rawtidy.select_notes(env.root, env.raw)
    row = rawtidy.apply(rawtidy.propose(notes, write_fn=model_for(merge(notes)))[0], records_path=env.records)
    assert row['commit']
    assert git(env.root, 'status', '--porcelain') == ''


def test_two_steps_include_long_note_tail(env):
    body = '\n\n'.join(''.join(chr(0x4e00 + j * 300 + k) for k in range(300)) for j in range(10))
    env.note('长笔记.md', body)
    env.note('短笔记.md')
    notes = rawtidy.select_notes(env.root, env.raw)
    plan = merge(notes)
    calls = []
    reply = model_for(plan)
    def model(prompt):
        calls.append(prompt)
        listing = json.loads(prompt.split('清单：\n')[-1]) if len(calls) > 1 else json.loads(prompt.split('清单（正文前 300 字）：\n')[-1])
        if len(calls) == 1:
            assert listing == [{'path': n['path'], 'title': n['title'], 'preview': n['body'][:300]} for n in notes]
        else:
            for n, item in zip(notes, listing):
                assert [p['text'] for p in item['paragraphs']] == rawtidy.paragraphs(n['body'])
            long = next(item for item in listing if item['path'].endswith('长笔记.md'))
            assert long['paragraphs'][9]['paragraph'] == 10
            assert body.index(long['paragraphs'][9]['text']) > 1500
        return reply(prompt)
    group = rawtidy.propose(notes, write_fn=model)[0]
    assert len(calls) == 2 and group['status'] == 'ready'
    assert group['coverage'] >= .9
    assert rawtidy.paragraphs(body)[9] in group['outputs'][0]['body']


@pytest.mark.parametrize('length', [12000, 12001])
def test_oversized_source_discards_group_before_arranging(env, length):
    env.note('超长.md', '原' * length)
    env.note('正常甲.md')
    env.note('正常乙.md')
    notes = rawtidy.select_notes(env.root, env.raw)
    huge = next(n for n in notes if n['path'].endswith('超长.md'))
    normal = [n for n in notes if n is not huge]
    plans = [merge([huge, normal[0]]), merge(normal)]
    replies = iter([
        [{k: p[k] for k in ('type', 'sources', 'mainline')} for p in plans],
        {'outputs': plans[0 if length == 12000 else 1]['outputs']},
    ])
    calls = []
    def model(prompt):
        calls.append(prompt)
        return json.dumps(next(replies))
    result = rawtidy.propose(notes, write_fn=model)
    assert len(calls) == 2
    if length > 12000:
        assert result[0]['status'] == 'discarded'
        assert '12,000' in result[0]['reason'] and huge['path'] in result[0]['reason']
        assert result[1]['status'] == 'ready'
    else:
        assert result[0]['status'] == 'ready'
        assert result[1]['status'] == 'discarded'  # 不重复安排同一来源。


def test_group_limit_bounds_calls(env):
    for i in range(6):
        env.note(f'笔记{i}.md')
    notes = rawtidy.select_notes(env.root, env.raw)
    plans = [merge(notes[i:i + 2]) for i in range(0, 6, 2)]
    calls = []
    reply = model_for(*plans)
    def model(prompt):
        calls.append(prompt)
        return reply(prompt)
    result = rawtidy.propose(notes, write_fn=model, limit=2)
    assert len(result) == 2 and all(g['status'] == 'ready' for g in result)
    assert len(calls) == 3
