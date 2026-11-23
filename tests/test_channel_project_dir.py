"""Channel defaults: persistence, hot edits, session isolation and precedence."""
import json
from types import SimpleNamespace

import pytest

from agent import team
from channel import channel_instances as ci
from channel.channel import Channel
from config import conf
from bridge.agent_bridge import AgentBridge


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setitem(conf(), 'agent_workspace', str(tmp_path / 'state'))
    team.write(conf(), {'channel_instances': [
        {'instance_id': 'bot-a', 'channel_type': 'feishu', 'agent_id': 'default'},
        {'instance_id': 'bot-b', 'channel_type': 'feishu', 'agent_id': 'default'},
    ]})
    return conf()


def context(iid):
    ch = Channel()
    ch.instance_id = iid
    ch.channel_type = 'feishu'
    ctx = {'session_id': 'same-user', 'instance_id': iid}
    ch.prepare_project_context(ctx)
    return ctx


def test_partial_updates_and_clear_keep_namespace(settings, tmp_path):
    first = ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(tmp_path))
    assert first.project_dir == str(tmp_path.resolve())
    assert first.session_namespace
    second = ci.upsert_instance(settings, 'feishu', 'bot-a', name='Renamed')
    assert second.project_dir == first.project_dir
    cleared = ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir='')
    assert cleared.project_dir == ''
    assert cleared.session_namespace
    assert ci.get_instance(settings, 'bot-b').project_dir == ''


def test_validation_does_not_write(settings, tmp_path):
    before = team.read(settings)
    for value in (str(tmp_path / 'missing'), 42):
        with pytest.raises(ValueError):
            ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=value)
    assert team.read(settings) == before


def test_namespace_opt_in_is_idempotent_and_isolates_bots(settings, tmp_path):
    assert context('bot-a')['session_id'] == 'same-user'
    for iid in ('bot-a', 'bot-b'):
        ci.upsert_instance(settings, 'feishu', iid, project_dir=str(tmp_path))
    a, b = context('bot-a'), context('bot-b')
    assert a['session_id'] != b['session_id']
    assert json.loads(a['session_id'][len('channel:'):]) == ['bot-a', 'same-user']
    Channel().prepare_project_context(a)
    assert a['session_id'] == context('bot-a')['session_id']
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir='')
    assert a['session_id'] == context('bot-a')['session_id']


def test_precedence_hot_edit_clear_and_missing_fail_closed(settings, tmp_path, monkeypatch):
    from agent.workspace import project_store
    monkeypatch.setattr(project_store, 'get_project_dir', lambda *args: None)
    other = tmp_path / 'other'
    other.mkdir()
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(tmp_path))
    sid = context('bot-a')['session_id']
    seen = []
    agent = SimpleNamespace(apply_project_dir=seen.append)
    bridge = object.__new__(AgentBridge)
    bridge._apply_session_project(agent, sid, 'default')
    assert seen[-1] == str(tmp_path.resolve())
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(other))
    bridge._apply_session_project(agent, sid, 'default')
    assert seen[-1] == str(other.resolve())
    monkeypatch.setattr(project_store, 'get_project_dir', lambda *args: 'explicit-session-project')
    bridge._apply_session_project(agent, sid, 'default')
    assert seen[-1] == 'explicit-session-project'
    monkeypatch.setattr(project_store, 'get_project_dir', lambda *args: None)
    other.rmdir()
    with pytest.raises(ValueError, match='does not exist'):
        bridge._apply_session_project(agent, sid, 'default')
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir='')
    bridge._apply_session_project(agent, sid, 'default')
    assert seen[-1] is None


def test_two_bots_same_agent_have_independent_cached_runtimes(settings, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from test_multi_agent_runtime import _bridge
    bridge = _bridge(tmp_path)
    original = bridge.initializer.initialize_agent
    def initialize(**kwargs):
        runtime = original(**kwargs)
        runtime.apply_project_dir = lambda path: setattr(runtime, 'project_dir', path)
        return runtime
    bridge.initializer.initialize_agent = initialize
    directories = {}
    for iid in ('bot-a', 'bot-b'):
        directory = tmp_path / iid
        directory.mkdir()
        directories[iid] = str(directory.resolve())
        ci.upsert_instance(settings, 'feishu', iid, project_dir=str(directory))
    def fetch(iid):
        return bridge.get_agent(session_id=context(iid)['session_id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(fetch, ('bot-a', 'bot-b')))
    assert a is not b
    assert a.project_dir == directories['bot-a']
    assert b.project_dir == directories['bot-b']
    assert fetch('bot-a') is a
    assert fetch('bot-b') is b
    assert a.project_dir == directories['bot-a']


def test_legacy_directory_edit_bootstraps_only_ready_channels(tmp_path, monkeypatch):
    from app import _resolve_startup_channels
    monkeypatch.setitem(conf(), 'agent_workspace', str(tmp_path / 'state'))
    monkeypatch.setitem(conf(), 'channel_type', 'web,wechatmp,feishu')
    monkeypatch.setitem(conf(), 'feishu_app_id', 'A')
    monkeypatch.setitem(conf(), 'feishu_app_secret', 'S')
    ci.upsert_instance(conf(), 'feishu', 'feishu', project_dir=str(tmp_path))
    records = ci.read_raw_instances(conf())
    assert [r['instance_id'] for r in records] == ['feishu']
    assert records[0]['credentials']['feishu_app_id'] == 'A'
    assert records[0]['project_dir'] == str(tmp_path.resolve())
    entries = _resolve_startup_channels(conf()['channel_type'])
    types = [e if isinstance(e, str) else e.channel_type for e in entries]
    assert sorted(types) == ['feishu', 'web', 'wechatmp']
    with pytest.raises(ValueError, match='not supported'):
        ci.upsert_instance(conf(), 'wechatmp', 'wechatmp', project_dir=str(tmp_path))
    assert [r['instance_id'] for r in ci.read_raw_instances(conf())] == ['feishu']


def test_read_only_directory_is_accepted(settings, tmp_path):
    readonly = tmp_path / 'readonly'
    readonly.mkdir()
    readonly.chmod(0o555)
    try:
        assert ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(readonly)).project_dir == str(readonly.resolve())
    finally:
        readonly.chmod(0o755)


def test_session_store_error_falls_back(settings, tmp_path, monkeypatch):
    from agent.workspace import project_store
    def broken(*args):
        raise OSError('store unreadable')
    monkeypatch.setattr(project_store, 'get_project_dir', broken)
    seen = []
    agent = SimpleNamespace(apply_project_dir=seen.append)
    bridge = object.__new__(AgentBridge)
    bridge._apply_session_project(agent, 'plain-session', 'default')
    assert seen == [None]
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(tmp_path))
    bridge._apply_session_project(agent, context('bot-a')['session_id'], 'default')
    assert seen[-1] == str(tmp_path.resolve())


def test_file_roots_follow_channel_default(settings, tmp_path, monkeypatch):
    from agent.protocol.artifact import artifact_root_for
    from agent.workspace import project_store
    from channel.web.core._common import _get_workspace_root
    monkeypatch.setattr(project_store, 'get_project_dir', lambda *args: None)
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(tmp_path))
    sid = context('bot-a')['session_id']
    assert artifact_root_for(sid, 'default', str(tmp_path / 'ws')) == str(tmp_path.resolve())
    assert _get_workspace_root(sid, 'default') == str(tmp_path.resolve())
    assert artifact_root_for('plain-session', 'default', str(tmp_path / 'ws')) == str(tmp_path / 'ws')


def test_project_api_validates_and_persists(settings, tmp_path, monkeypatch):
    from channel.web.api import channels
    monkeypatch.setattr(channels, '_require_auth', lambda: None)
    monkeypatch.setattr(channels.web, 'header', lambda *args: None)
    def post(**fields):
        body = {'action': 'set_project', 'channel': 'feishu', 'instance_id': 'bot-a', **fields}
        monkeypatch.setattr(channels.web, 'data', lambda: json.dumps(body))
        return json.loads(channels.ChannelsHandler().POST())
    assert post(project_dir=str(tmp_path))['status'] == 'success'
    assert ci.get_instance(settings, 'bot-a').project_dir == str(tmp_path.resolve())
    assert post(project_dir=str(tmp_path / 'missing'))['status'] == 'error'
    assert post(instance_id='unknown', project_dir=str(tmp_path))['status'] == 'error'
    assert ci.get_instance(settings, 'bot-a').project_dir == str(tmp_path.resolve())
    assert post(project_dir='')['status'] == 'success'
    assert ci.get_instance(settings, 'bot-a').session_namespace
    unsupported = post(channel='wechatmp', instance_id='', project_dir=str(tmp_path))
    assert unsupported['status'] == 'error' and 'not supported' in unsupported['message']
    assert {r['instance_id'] for r in ci.read_raw_instances(settings)} == {'bot-a', 'bot-b'}


def test_legacy_default_unchanged_without_setting():
    assert ci.resolve_channel_instances({'channel_type': 'feishu'})[0].project_dir == ''


def test_channel_view_includes_project(settings, tmp_path):
    from channel.web.api.channels import ChannelsHandler
    ci.upsert_instance(settings, 'feishu', 'bot-a', project_dir=str(tmp_path))
    cards = ChannelsHandler._channel_instances_view()
    assert next(c for c in cards if c['instance_id'] == 'bot-a')['project_dir'] == str(tmp_path.resolve())
