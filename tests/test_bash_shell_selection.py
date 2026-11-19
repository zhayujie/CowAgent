"""CMD compatibility and PowerShell 7 execution coverage."""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

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


def test_pwsh_notice_mentions_old_commands_only_after_a_switch(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(Bash, '_IS_WIN', True)
    state = {'tools': {'bash': {'windows_shell': 'pwsh'}}}
    monkeypatch.setattr(config, 'conf', lambda: state)
    tool = Bash({'cwd': str(tmp_path), 'windows_shell': 'pwsh'})
    tool.refresh_runtime_config()
    assert 'Earlier CMD' not in tool.runtime_shell_notice()
    state['tools']['bash']['windows_shell'] = 'cmd'
    tool.refresh_runtime_config()
    tool.runtime_shell_notice()
    state['tools']['bash']['windows_shell'] = 'pwsh'
    tool.refresh_runtime_config()
    assert 'Earlier CMD' in tool.runtime_shell_notice()
    assert 'Earlier CMD' not in tool.runtime_shell_notice()


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
    for selected in ('cmd', 'pwsh', 'cmd', 'cmd'):
        state['tools']['bash']['windows_shell'] = selected
        executor._call_llm_stream(retry_on_empty=False)
        system = requests[-1].system
        has_notice = 'CURRENT COMMAND ENVIRONMENT:' in system
        if selected == 'pwsh':
            assert has_notice and 'Use $env:NAME' in system
        elif selected == 'cmd' and requests.index(requests[-1]) == 2:
            assert has_notice and 'Use %NAME%' in system
        else:
            assert not has_notice
        assert system.count('CURRENT COMMAND ENVIRONMENT:') <= 1
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


def test_real_pwsh_workspace_write_paths(pwsh_tool):
    from agent.permission import WORKSPACE_WRITE
    from agent.protocol.agent_stream import AgentStreamExecutor

    workspace = Path(pwsh_tool.cwd)
    protected = workspace / 'mcp.json'
    protected.write_text('{}', encoding='utf-8')
    (workspace / 'templates').mkdir()
    (workspace / 'templates' / 'mcp.json').write_text('sample', encoding='utf-8')
    build = workspace / 'build'
    build.mkdir()
    (build / 'output.txt').write_text('sample', encoding='utf-8')
    assert build.resolve().parent == workspace.resolve()
    with ZipFile(workspace / 'archive.zip', 'w') as archive:
        archive.writestr('entry.txt', 'sample')
    executor = SimpleNamespace(
        tools={'bash': pwsh_tool},
        agent=SimpleNamespace(
            effective_permission_mode=lambda: WORKSPACE_WRITE,
            effective_cwd=lambda: str(workspace),
            write_roots=lambda: [str(workspace)],
            protected_paths=lambda: [str(protected)],
        ),
    )

    for command in (
        'Remove-Item ./build -Recurse',
        r"Set-Content -NoNewline .\notes.txt,'.\notes, copy.txt' -Value sample",
        r"Copy-Item -LiteralPath .\notes.txt .\copied.txt",
        r"Move-Item .\copied.txt -Destination .\moved.txt",
        r"Out-File -LiteralPath .\out.txt -NoNewline -InputObject sample",
        r"Tee-Object -Path .\tee.txt -InputObject sample",
        r"New-Item -Path . -Name .\folder -ItemType Directory",
        r"Copy-Item -Path .\moved.txt .\folder",
        r"Rename-Item -LiteralPath .\folder\moved.txt renamed.txt",
        r"Expand-Archive -Path .\archive.zip .\extracted",
        "[IO.File]::WriteAllText('text.txt', 'sample'); "
        "[System.IO.File]::WriteAllBytes('bytes.bin', [byte[]]@(1, 2))",
        "[IO.File]::WriteAllLines('lines.txt', [string[]]@('a')); "
        "[IO.File]::AppendAllText('lines.txt', 'b'); [System.IO.File]::AppendAllText('lines.txt', 'c')",
    ):
        args = {'command': command}
        assert AgentStreamExecutor._permission_denial(executor, 'bash', args) is None
        result = pwsh_tool.execute(args)
        assert result.status != 'error', result.result

    for command in (
        r"Copy-Item .\templates\mcp.json .",
        r"Rename-Item .\notes.txt -NewName mcp.json",
        r"New-Item -Path . -Name mcp.json -ItemType File",
        "[IO.File]::AppendAllText('lines.txt', 'd'); [System.IO.File]::AppendAllText('mcp.json', 'x')",
    ):
        denial = AgentStreamExecutor._permission_denial(executor, 'bash', {'command': command})
        assert denial and 'mcp.json' in denial

    for name in (
        'notes.txt', 'notes, copy.txt', 'out.txt', 'tee.txt', 'folder/renamed.txt',
        'extracted/entry.txt', 'text.txt',
    ):
        assert (workspace / name).read_text(encoding='utf-8').strip() == 'sample'
    assert (workspace / 'bytes.bin').read_bytes() == b'\x01\x02'
    assert (workspace / 'lines.txt').read_text(encoding='utf-8') == 'a\nbc'
    assert protected.read_text(encoding='utf-8') == '{}'
    assert not build.exists()


def test_real_pwsh_permission_parser_forms(pwsh_tool, monkeypatch):
    from agent.permission import WORKSPACE_WRITE, policy
    from agent.protocol.agent_stream import AgentStreamExecutor

    scratch = Path(pwsh_tool.cwd)
    workspace = scratch / 'workspace'
    workspace.mkdir()
    source = scratch / 'source.txt'
    source.write_text('outside source', encoding='utf-8')
    pwsh_tool.set_cwd(str(workspace))
    # Make the sibling read source fall outside the policy's writable roots.
    monkeypatch.setattr(policy.tempfile, 'gettempdir', lambda: str(workspace))
    executor = SimpleNamespace(
        tools={'bash': pwsh_tool},
        agent=SimpleNamespace(
            effective_permission_mode=lambda: WORKSPACE_WRITE,
            effective_cwd=lambda: str(workspace),
            write_roots=lambda: [str(workspace)],
            protected_paths=lambda: [],
        ),
    )

    for command in (
        '${result name} = Set-Content -N notes.txt -Value sample',
        f"cp -Destination copied.txt -LiteralPath '{source.as_posix()}'",
        "Set-Content -Value (Get-Date) date.txt",
        """[ IO.File ]::"WriteAllText"('staged.txt', 'new')""",
        "[IO.File]::'WriteAllText'('current.txt', 'old')",
        "[ IO.File ]::'Replace'('staged.txt', 'current.txt', [NullString]::Value)",
    ):
        args = {'command': command}
        denial = AgentStreamExecutor._permission_denial(executor, 'bash', args)
        assert denial is None, denial
        result = pwsh_tool.execute(args)
        assert result.status != 'error', result.result

    assert (workspace / 'notes.txt').read_text(encoding='utf-8') == 'sample'
    assert (workspace / 'copied.txt').read_text(encoding='utf-8') == 'outside source'
    assert (workspace / 'date.txt').read_text(encoding='utf-8').strip()
    assert source.read_text(encoding='utf-8') == 'outside source'
    assert (workspace / 'current.txt').read_text(encoding='utf-8') == 'new'
    assert not (workspace / 'staged.txt').exists()


def test_real_pwsh_location_and_wildcard_targets(pwsh_tool, monkeypatch):
    from agent.permission import WORKSPACE_WRITE, check_tool_call, policy

    scratch = Path(pwsh_tool.cwd)
    workspace = scratch / 'workspace'
    workspace.mkdir()
    protected = workspace / 'mcp.json'
    protected.write_text('protected', encoding='utf-8')
    (workspace / 'm[c]p.json').touch()
    (workspace / 'notes-1.txt').touch()
    pwsh_tool.set_cwd(str(workspace))
    monkeypatch.setattr(policy.tempfile, 'gettempdir', lambda: str(workspace))

    def decide(command):
        return check_tool_call(
            WORKSPACE_WRITE, 'bash', {'command': command},
            cwd=str(workspace), protected_paths=[str(protected)], shell=pwsh_tool.windows_shell,
        )

    change_location = f"Set-Location -LiteralPath '{scratch.as_posix()}'"
    assert not decide(f"{change_location}; Set-Content relative.txt sample").allowed
    probe = pwsh_tool.execute({'command': (
        f"{change_location}; "
        "$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath('relative.txt')"
    )})
    assert probe.status != 'error', probe.result
    assert Path(probe.result['output'].strip()) == scratch / 'relative.txt'
    assert not (scratch / 'relative.txt').exists()

    assert not decide("Set-Content 'm[c]p.json' sample").allowed
    probe = pwsh_tool.execute({'command': "(Get-Item 'm[c]p.json').FullName"})
    assert probe.status != 'error', probe.result
    assert Path(probe.result['output'].strip()) == protected

    for command in (
        f"{change_location}; Set-Content '{workspace.as_posix()}/absolute.txt' sample",
        "Set-Content -LiteralPath 'm[c]p.json' sample",
        "'sample' > 'notes-*.txt'",
    ):
        decision = decide(command)
        assert decision.allowed, decision.reason
        result = pwsh_tool.execute({'command': command})
        assert result.status != 'error', result.result

    for name in ('absolute.txt', 'm[c]p.json', 'notes-1.txt'):
        assert (workspace / name).read_text(encoding='utf-8').strip() == 'sample'
    assert protected.read_text(encoding='utf-8') == 'protected'


def test_real_pwsh_unicode_parameters_and_readonly_open(pwsh_tool, monkeypatch):
    from agent.permission import READ_ONLY, WORKSPACE_WRITE, check_tool_call, policy

    scratch = Path(pwsh_tool.cwd)
    workspace = scratch / 'workspace'
    workspace.mkdir()
    source = scratch / 'source.txt'
    source.write_text('outside source', encoding='utf-8')
    pwsh_tool.set_cwd(str(workspace))
    monkeypatch.setattr(policy.tempfile, 'gettempdir', lambda: str(workspace))

    def decide(command, mode=WORKSPACE_WRITE):
        return check_tool_call(
            mode, 'bash', {'command': command}, cwd=str(workspace), shell=pwsh_tool.windows_shell,
        )

    for index, dash in enumerate(('\u2013', '\u2014', '\u2015')):
        prefix = f"Set-Content {dash}Value sample"
        assert not decide(f"{prefix} '{scratch.as_posix()}/blocked.txt'").allowed
        name = f"allowed-{index}.txt"
        command = f"{prefix} {name}"
        assert decide(command).allowed
        result = pwsh_tool.execute({'command': command})
        assert result.status != 'error', result.result
        assert (workspace / name).read_text(encoding='utf-8').strip() == 'sample'
    assert not (scratch / 'blocked.txt').exists()

    path = f"'{source.as_posix()}'"
    access = "[IO.FileMode]::Open, [IO.FileAccess]::Read"
    command = (
        f"$stream = [IO.File]::Open({path}, {access}); "
        "try { $stream.CanRead; $stream.CanWrite } finally { $stream.Dispose() }"
    )
    assert decide(command).allowed
    result = pwsh_tool.execute({'command': command})
    assert result.status != 'error', result.result
    assert result.result['output'].split() == ['True', 'False']
    assert not decide(f"[IO.File]::Open({path}, [IO.FileMode]::Open)").allowed

    command = f"gc -LiteralPath {path}"
    assert decide(command, READ_ONLY).allowed
    result = pwsh_tool.execute({'command': command})
    assert result.status != 'error', result.result
    assert result.result['output'].strip() == 'outside source'
    assert source.read_text(encoding='utf-8') == 'outside source'


@pytest.mark.skipif(sys.platform != 'win32', reason='requires Windows CMD')
def test_real_cmd_builtin_switches_and_external_arguments(tmp_path, monkeypatch):
    from agent.permission import WORKSPACE_WRITE, check_tool_call, policy

    tool = Bash({'cwd': str(tmp_path), 'windows_shell': 'cmd'})
    (tmp_path / 'source.txt').write_text('sample', encoding='utf-8')
    (tmp_path / 'tee.cmd').write_bytes(b'@echo %~f1\r\n')
    monkeypatch.setattr(policy.tempfile, 'gettempdir', lambda: str(tmp_path))

    def decide(command):
        return check_tool_call(
            WORKSPACE_WRITE, 'bash', {'command': command}, cwd=str(tmp_path), shell=tool.windows_shell,
        )

    for command in (
        'copy /Y source.txt copied.txt /B',
        'move /Y copied.txt moved.txt',
        'del /Q /A:-H moved.txt',
        'md empty',
        'rd /S /Q empty',
    ):
        decision = decide(command)
        assert decision.allowed, decision.reason
        result = tool.execute({'command': command})
        assert result.status != 'error', result.result

    assert (tmp_path / 'source.txt').read_text(encoding='utf-8') == 'sample'
    assert not (tmp_path / 'copied.txt').exists()
    assert not (tmp_path / 'moved.txt').exists()
    assert not (tmp_path / 'empty').exists()

    # The external fixture only echoes the resolved argument, even for the
    # denied operand. It never opens the path.
    command = 'tee /cowagent-policy-outside'
    decision = decide(command)
    assert not decision.allowed
    assert 'outside the writable area' in decision.reason
    probe = tool.execute({'command': command})
    assert probe.status != 'error', probe.result
    assert Path(probe.result['output'].strip()) == Path(tmp_path.anchor) / 'cowagent-policy-outside'


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
