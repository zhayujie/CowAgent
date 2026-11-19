import json
import os
from unittest.mock import patch

from agent.tools.web_search import web_search as ws
from channel.web.api.models import ModelsHandler


def _keys(*providers):
    return lambda provider: 'fake-key' if provider in providers else ''


def test_disabled_provider_is_skipped_at_runtime(monkeypatch):
    monkeypatch.setattr(ws, '_get_api_key', _keys('deepseek', 'tavily'))
    monkeypatch.setattr(ws, '_get_searxng_url', lambda: '')
    monkeypatch.setattr(ws, 'conf', lambda: {'tools': {'web_search': {'disabled_providers': ['deepseek']}}})
    assert ws.configured_providers() == ['tavily']
    assert ws.WebSearch()._resolve_provider('deepseek') == 'tavily'


def test_disabled_list_accepts_comma_separated_string():
    assert ws.parse_provider_list(' DeepSeek, bocha ,') == ['deepseek', 'bocha']
    assert ws.parse_provider_list(None) == []


def test_console_reports_disabled_provider():
    cfg = {'deepseek_api_key': 'sk-test', 'tools': {'web_search': {'disabled_providers': ['deepseek']}}}
    cap = ModelsHandler._search_capability(cfg)
    providers = {p['id']: p for p in cap['providers']}
    assert providers['deepseek']['configured'] is False
    assert providers['deepseek']['disabled'] is True
    assert 'deepseek' not in cap['configured_providers']
    # Disabled without a credential is just "not configured".
    assert providers['bocha']['disabled'] is False


def _toggle(payload, file_cfg):
    local_cfg = json.loads(json.dumps(file_cfg))
    with patch('channel.web.api.models.conf', return_value=local_cfg), \
            patch.object(ModelsHandler, '_read_file_config', return_value=file_cfg), \
            patch.object(ModelsHandler, '_write_file_config') as write:
        out = json.loads(ModelsHandler()._handle_set_search_provider_enabled(payload))
    return out, write, local_cfg


def test_disable_then_enable_keeps_credential():
    file_cfg = {'deepseek_api_key': 'sk-test'}
    out, write, local_cfg = _toggle({'provider': 'deepseek', 'enabled': False}, file_cfg)
    assert out['status'] == 'success'
    saved = write.call_args[0][0]
    assert saved['tools']['web_search']['disabled_providers'] == ['deepseek']
    assert saved['deepseek_api_key'] == 'sk-test'
    assert local_cfg['tools']['web_search']['disabled_providers'] == ['deepseek']

    out, write, _ = _toggle({'provider': 'deepseek', 'enabled': True}, saved)
    assert out['status'] == 'success'
    assert write.call_args[0][0]['tools']['web_search']['disabled_providers'] == []


def test_toggle_rejects_unknown_provider_and_non_bool():
    out, write, _ = _toggle({'provider': 'nope', 'enabled': False}, {})
    assert out['status'] == 'error'
    write.assert_not_called()
    out, write, _ = _toggle({'provider': 'bocha', 'enabled': 'false'}, {})
    assert out['status'] == 'error'
    write.assert_not_called()


def test_saving_a_new_key_re_enables_provider():
    file_cfg = {'tools': {'web_search': {'disabled_providers': ['tavily', 'bocha']}}}
    with patch('channel.web.api.models.conf', return_value={}), \
            patch.object(ModelsHandler, '_read_file_config', return_value=file_cfg), \
            patch.object(ModelsHandler, '_write_file_config') as write:
        ModelsHandler()._handle_set_search_credential({'provider': 'tavily', 'api_key': 'tvly-new'})
    assert write.call_args[0][0]['tools']['web_search']['disabled_providers'] == ['bocha']


def test_delete_provider_drops_env_copy_mirrored_from_config(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-from-config')
    local_cfg = {'deepseek_api_key': 'sk-from-config'}
    with patch('channel.web.api.models.conf', return_value=local_cfg), \
            patch.object(ModelsHandler, '_read_file_config', return_value={}), \
            patch.object(ModelsHandler, '_write_file_config'), \
            patch.object(ModelsHandler, '_reset_bridge'):
        out = json.loads(ModelsHandler()._handle_delete_provider({'provider_id': 'deepseek'}))
    assert out['status'] == 'success'
    assert 'DEEPSEEK_API_KEY' not in os.environ
    assert 'deepseek' not in ModelsHandler._search_capability(local_cfg)['configured_providers']


def test_delete_provider_keeps_unrelated_env_value(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-from-shell')
    local_cfg = {'deepseek_api_key': 'sk-from-config'}
    with patch('channel.web.api.models.conf', return_value=local_cfg), \
            patch.object(ModelsHandler, '_read_file_config', return_value={}), \
            patch.object(ModelsHandler, '_write_file_config'), \
            patch.object(ModelsHandler, '_reset_bridge'):
        ModelsHandler()._handle_delete_provider({'provider_id': 'deepseek'})
    assert os.environ.get('DEEPSEEK_API_KEY') == 'sk-from-shell'
