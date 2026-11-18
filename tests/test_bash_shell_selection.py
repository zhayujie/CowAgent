"""CMD compatibility and PowerShell 7 execution coverage."""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.tools.bash.bash import Bash
from agent.tools.bash import background, shell


@pytest.mark.parametrize("value", ["powershell", "", None, 42])
def test_invalid_shell_config_falls_back_to_cmd(monkeypatch, tmp_path, caplog, value):
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    tool = Bash({'cwd': str(tmp_path), 'windows_shell': value})
    assert tool.windows_shell == 'cmd'
    assert 'cmd.exe' in tool.description
    assert "falling back to cmd" in caplog.text


def test_invalid_shell_config_falls_back_on_non_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(Bash, '_IS_WIN', False)
    tool = Bash({'cwd': str(tmp_path), 'windows_shell': 'powershell'})
    assert tool.windows_shell == 'cmd'
    assert tool.description


def test_default_stays_cmd(monkeypatch, tmp_path):
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    tool = Bash({'cwd': str(tmp_path)})
    assert tool.windows_shell == 'cmd'
    assert 'cmd.exe' in tool.description


def test_pwsh_description_and_argv_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    monkeypatch.setattr(shell, 'detect_pwsh', lambda: {'available': True, 'path': 'pwsh.exe', 'version': '7.5.0'})
    tool = Bash({'cwd': str(tmp_path), 'windows_shell': 'pwsh'})
    assert 'PowerShell 7' in tool.description
    assert '$env:VAR_NAME' in tool.description
    paths = []
    def run(command, timeout, env, dotenv):
        assert isinstance(command, list)
        assert command[0] == 'pwsh.exe'
        path = Path(command[-1])
        paths.append(path)
        text = path.read_text(encoding='utf-8-sig')
        assert "Write-Output '中文'" in text
        assert "chcp 65001" not in text
        return SimpleNamespace(returncode=0, stdout='中文', stderr='')
    monkeypatch.setattr(tool, '_run_streaming', run)
    assert not tool.execute({'command': "Write-Output '中文'"}).status == 'error'
    assert paths and not paths[0].exists()


def test_unavailable_pwsh_does_not_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    monkeypatch.setattr(shell, 'detect_pwsh', lambda: {'available': False})
    tool = Bash({'cwd': str(tmp_path), 'windows_shell': 'pwsh'})
    monkeypatch.setattr(tool, '_run_streaming', lambda *a: pytest.fail('must not start CMD'))
    result = tool.execute({'command': 'echo test'})
    assert result.status == 'error'
    assert 'unavailable' in str(result.result)


def test_model_schema_refreshes_cached_shell(monkeypatch, tmp_path):
    import config
    from agent.protocol.agent_stream import build_tools_schema
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    state = {'tools': {'bash': {'windows_shell': 'cmd'}}}
    monkeypatch.setattr(config, 'conf', lambda: state)
    tool = Bash({'cwd': str(tmp_path)})
    state['tools']['bash']['windows_shell'] = 'pwsh'
    assert 'PowerShell 7' in build_tools_schema([tool])[0]['description']
    assert tool.windows_shell == 'pwsh'
    assert 'Use $env:NAME' in tool.runtime_shell_notice()
    state['tools']['bash']['windows_shell'] = 'cmd'
    assert 'cmd.exe' in build_tools_schema([tool])[0]['description']
    assert tool.windows_shell == 'cmd'
    assert 'Use %NAME%' in tool.runtime_shell_notice()


def test_request_system_tracks_shell_without_accumulating(monkeypatch, tmp_path):
    import config
    from agent.protocol.agent_stream import AgentStreamExecutor
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    state = {'tools': {'bash': {'windows_shell': 'cmd'}}}
    monkeypatch.setattr(config, 'conf', lambda: state)
    requests = []
    class Model:
        model = 'test-model'
        def call_stream(self, request):
            requests.append(request)
            yield {'choices': [{'delta': {'content': 'ok'}}]}
    class Executor(AgentStreamExecutor):
        def _validate_and_fix_messages(self):
            pass
        def _catalog_max_output_tokens(self):
            return 16
        def _is_thinking_enabled(self):
            return False
    tool = Bash({'cwd': str(tmp_path)})
    executor = Executor(agent=SimpleNamespace(), model=Model(), system_prompt='base',
                        tools=[tool], messages=[], max_turns=2)
    for selected in ('cmd', 'pwsh', 'cmd'):
        state['tools']['bash']['windows_shell'] = selected
        executor._call_llm_stream(retry_on_empty=False)
        system = requests[-1].system
        assert system.count('CURRENT COMMAND ENVIRONMENT:') == 1
        assert ('Use $env:NAME' if selected == 'pwsh' else 'Use %NAME%') in system
        assert executor.system_prompt == 'base'


@pytest.mark.parametrize('version,available', [('5.1.0', False), ('7.5.0', True), ('10.0.0', True), ('garbage', False)])
def test_probe_requires_version_seven(monkeypatch, version, available):
    monkeypatch.setattr(shell, '_probe_cache', None)
    monkeypatch.setattr(shell.shutil, 'which', lambda name: 'pwsh.exe')
    monkeypatch.setattr(shell.os.path, 'isfile', lambda path: True)
    calls = []
    def probe(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=version.encode())
    monkeypatch.setattr(shell.subprocess, 'run', probe)
    assert shell.detect_pwsh()['available'] == available
    assert all(argv[0].endswith('pwsh.exe') for argv in calls)


@pytest.fixture
def pwsh_tool(tmp_path):
    if sys.platform != 'win32' or not shell.detect_pwsh()['available']:
        pytest.skip('requires Windows and PowerShell 7')
    return Bash({'cwd': str(tmp_path), 'windows_shell': 'pwsh'})


@pytest.mark.parametrize('command,failed,expected', [
    ("Write-Output '你好世界'", False, '你好世界'),
    ("$x = 4\nWrite-Output ($x + 3)", False, '7'),
    ('Get-Item ./missing-pwsh-test-file', True, 'missing-pwsh-test-file'),
    ('exit 9', True, 'code 9'),
    (f'& "{sys.executable}" -c "import sys; sys.exit(3)"', True, 'code 3'),
])
def test_real_pwsh(pwsh_tool, command, failed, expected):
    result = pwsh_tool.execute({'command': command})
    assert (result.status == 'error') == failed
    assert expected in str(result.result)


def test_real_pwsh_background(pwsh_tool):
    result = pwsh_tool.execute({'command': "Write-Output '后台中文'; Start-Sleep -Milliseconds 100", 'run_in_background': True})
    assert not result.status == 'error'
    job_id = result.result['bash_id']
    output = ''
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = background.read(job_id)
            output += state['output']
            if not state['running']:
                assert state['exit_code'] == 0
                break
            time.sleep(.05)
        else:
            pytest.fail('background command did not finish')
        assert '后台中文' in output
        assert not Path(background._jobs[job_id].temp_script or '').is_file()
    finally:
        background.kill(job_id)


def test_real_pwsh_cancel(pwsh_tool):
    pwsh_tool.cancel_event = threading.Event()
    timer = threading.Timer(1, pwsh_tool.cancel_event.set)
    timer.start()
    try:
        result = pwsh_tool.execute({'command': 'Start-Sleep -Seconds 30'})
        assert result.status == 'error'
        assert 'cancelled' in str(result.result)
    finally:
        timer.cancel()


def test_real_pwsh_timeout(pwsh_tool):
    result = pwsh_tool.execute({'command': 'Start-Sleep -Seconds 30', 'timeout': 1})
    assert result.status == 'error'
    assert 'timed out' in str(result.result)
