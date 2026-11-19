"""PowerShell file targets must be checked using PowerShell argument syntax."""

import os

import pytest

from agent.permission import READ_ONLY, WORKSPACE_WRITE, check_tool_call, policy


@pytest.fixture
def check(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("mcp.json", "m[c]p.json", "notes-1.txt"):
        (workspace / name).touch()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mcp.json").touch()
    # Keep the sibling fixture outside both of the policy's default write roots.
    monkeypatch.setattr(policy.tempfile, "gettempdir", lambda: str(workspace))

    def decide(command, shell=None):
        native = os.path.join(outside.anchor, "cowagent-policy-outside")
        return check_tool_call(
            WORKSPACE_WRITE, "bash",
            {"command": command.format(outside=outside.as_posix(), native=native, workspace=workspace.as_posix())},
            cwd=str(workspace), protected_paths=[str(workspace / "mcp.json")], shell=shell,
        )

    return decide


@pytest.mark.skipif(os.name != "nt", reason="requires Windows path resolution")
@pytest.mark.parametrize("command", [
    r"ri {native}\test.txt",
    r"cpi notes.txt {native}\test.txt",
    r"Set-Content ..\outside\test.txt sample",
    r"Set-Content './notes.txt',{native}\test.txt sample",
    r"Set-Content -Path './notes.txt',{native}\test.txt -Value sample",
    r'Set-Content FileSystem::{native}\test.txt sample',
    'Set-Content {native}\u201ctest file\u201d sample',
])
def test_windows_separators_and_path_arrays(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "Move-Item -Path notes.txt {outside}/moved.txt",
    "Move-Item {outside}/source.txt -Destination moved.txt",
    "mi -LiteralPath notes.txt '{outside}/moved.txt'",
    "cpi -Path notes.txt '{outside}/copy.txt'",
    "Expand-Archive -LiteralPath archive.zip '{outside}'",
    "Set-Content notes.txt,\n'{outside}/test.txt' sample",
    "ni -Path . -Name ../outside/test.txt -ItemType File",
])
def test_all_write_paths_are_checked(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "New-Item -Path . -Name mcp.json -ItemType File",
    "Rename-Item -Path notes.txt -NewName mcp.json",
    "Rename-Item -LiteralPath ./notes.txt mcp.json",
    "Copy-Item -Path templates/mcp.json -Destination .",
    "Copy-Item notes.txt,templates/mcp.json .",
    "Move-Item -LiteralPath templates/mcp.json .",
    "${{result}} = Set-Content -Path mcp.json -Value sample",
    "[ IO.File ]::WriteAllText('mcp.json', 'sample')",
    "[IO.File]::'WriteAllText'('mcp.json', 'sample')",
    """[ IO.File ]::"WriteAllText"('mcp.json', 'sample')""",
    "Set-Content -N mcp.json -Value sample",
])
def test_protected_destinations_are_checked_after_resolving_the_name(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "mcp.json" in decision.reason
    assert "full-access" in decision.reason


@pytest.mark.parametrize("method", ["WriteAllText", "WriteAllBytes", "AppendAllText", "WriteAllLines"])
@pytest.mark.parametrize("type_name", ["IO.File", "System.IO.File"])
def test_each_static_write_is_checked(check, method, type_name):
    decision = check(
        f"[IO.File]::{method}('notes.txt', $data); "
        f"[{type_name}]::{method}('{{outside}}/test.txt', $data)"
    )
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


def test_dynamic_static_path_is_checked_even_after_a_literal_path(check):
    assert not check("[IO.File]::AppendAllText('notes.txt', 'x'); [IO.File]::AppendAllText($path, 'y')").allowed


def test_static_writer_with_whitespace_before_method_is_checked(check):
    decision = check("[IO.File]:: AppendAllText('{outside}/test.txt', 'x')")
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "Copy-Item -Path '{outside}/source.txt' copy.txt",
    "Copy-Item -LiteralPath '{outside}/source.txt' copy.txt",
    "Move-Item -Path notes.txt moved.txt",
    "Move-Item notes.txt -Destination moved.txt",
    "Expand-Archive -Path archive.zip extracted",
    "Set-Content -NoNewline notes.txt -Value sample",
    "Add-Content -NoNewline notes.txt -Value sample",
    "Out-File -NoNewline notes.txt -InputObject sample",
    "Out-File -LiteralPath notes.txt -InputObject sample",
    "Tee-Object -LiteralPath notes.txt -InputObject sample",
    'Tee-Object -Path:"notes, copies.txt" -InputObject sample',
    'Set-Content notes" and copies.txt" sample',
    "Set-Content 'notes, copies.txt',second.txt sample",
    "Set-Content notes.txt,\nsecond.txt sample",
    "Remove-Item ./build -Recurse",
    "New-Item -Path . -Name subfolder -ItemType Directory",
    "Rename-Item -LiteralPath notes.txt moved.txt",
    "[IO.File]::AppendAllText('notes.txt','x'); [System.IO.File]::AppendAllText('second.txt','y')",
    """Write-Output "[IO.File]::AppendAllText('{outside}/test.txt', 'y')" """,
])
def test_powershell_write_forms_within_workspace_are_allowed(check, command):
    decision = check(command)
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", [
    "Set-Content 2>&1 '{outside}/test.txt' sample",
    "Set-Content *> $null '{outside}/test.txt' sample",
])
def test_stream_redirects_do_not_hide_the_next_argument(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "$null = New-Item -ItemType Directory '{outside}/dir'",
    "$result = Remove-Item '{outside}/test.txt'",
    "$result=Remove-Item '{outside}/test.txt'",
    "$result =ri '{outside}/test.txt'",
    "[string]$result = sc '{outside}/test.txt' sample",
    "$state.Item = ni '{outside}/test.txt'",
    "${{result}}=Set-Content -Path '{outside}/test.txt' -Value sample",
    "[string]${{result name}} = Set-Content -Path '{outside}/test.txt' -Value sample",
])
def test_assignment_prefixes_do_not_hide_cmdlets(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "$null = New-Item -ItemType Directory out",
    "$content = Get-Content notes.txt",
    "$count = 1",
])
def test_assignments_within_workspace_are_allowed(check, command):
    decision = check(command)
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", [
    "rni notes.txt '{outside}/test.txt'",
    "clc '{outside}/test.txt'",
    "ac '{outside}/test.txt' sample",
])
def test_remaining_cmdlet_aliases_are_checked(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "cp -Destination '{outside}/test.txt' notes.txt",
    "copy -Destination '{outside}' notes.txt",
    "rm -Path '{outside}/test.txt' -Recurse",
    "del -LiteralPath '{outside}/test.txt'",
    "mv notes.txt -Destination '{outside}/test.txt'",
    "ren notes.txt '{outside}/test.txt'",
    "tee -FilePath '{outside}/test.txt'",
    "'sample' > '{outside}/test.txt'",
    "Get-Content notes.txt >> '{outside}/test.txt'",
])
def test_pwsh_binds_posix_named_aliases_as_cmdlets(check, command):
    decision = check(command, shell="pwsh")
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "rm -r -fo build",
    "Remove-Item build -r -fo -ea 0",
    "rm build -Recurse -Force",
    "cp notes.txt build",
    "cp -Destination copied.txt -LiteralPath '{outside}/source.txt'",
    "Copy-Item notes.txt -Dest build",
    "del notes.txt",
    "Get-Process | Tee-Object -Variable processes",
    "Get-Process | tee -Variable processes",
    "Get-Process | tee -Variable mcp.json",
    "Set-Content -N notes.txt -Value sample",
    "Out-File -Pa notes.txt -InputObject sample",
    "'sample' > out.txt",
    "ri build 2>$null",
    "ri build *> $null",
])
def test_pwsh_workspace_forms_are_allowed(check, command):
    decision = check(command, shell="pwsh")
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", [
    "Set-Location '{outside}'; Set-Content notes.txt sample",
    "sl '{outside}' && Add-Content ./notes.txt sample",
    "Push-Location '{outside}'; [string](Get-Date) > notes.txt",
    "Pop-Location; Copy-Item notes.txt output.txt",
    r"cd\; New-Item -Name notes.txt -ItemType File",
    "if ($useOutside) {{ cd '{outside}' }}; Remove-Item notes.txt",
    "Set-Content -Value (Set-Location '{outside}') notes.txt",
    "Set-Location '{outside}'; cp.exe notes.txt output.txt",
])
def test_pwsh_relative_writes_require_a_known_location(check, command):
    decision = check(command, shell="pwsh")
    assert not decision.allowed
    assert "statically" in decision.reason


@pytest.mark.parametrize("command,allowed", [
    ("Set-Location '{outside}'; Set-Content '{workspace}/notes.txt' sample", True),
    ("Set-Location '{outside}'; Set-Content '{outside}/notes.txt' sample", False),
    ("Set-Location '{outside}'; [IO.File]::WriteAllText('notes.txt', 'sample')", True),
    ("[IO.Directory]::SetCurrentDirectory('{outside}'); [IO.File]::WriteAllText('notes.txt', 'sample')", False),
])
def test_pwsh_checks_absolute_paths_and_distinguishes_dotnet_location(check, command, allowed):
    decision = check(command, shell="pwsh")
    assert decision.allowed == allowed, decision.reason


@pytest.mark.parametrize("dash", ["\u2013", "\u2014", "\u2015"])
def test_pwsh_binds_unicode_parameter_prefixes(check, dash):
    decision = check(f"Set-Content {dash}Value sample '{{outside}}/notes.txt'", shell="pwsh")
    assert not decision.allowed
    assert "outside the writable area" in decision.reason
    decision = check(f"Set-Content {dash}Value:sample notes.txt", shell="pwsh")
    assert decision.allowed, decision.reason


def test_pwsh_does_not_bind_a_unicode_minus_as_a_parameter(check):
    decision = check("Set-Content \u2212Value '{outside}/text-as-value.txt'", shell="pwsh")
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("value", ["(Get-Date)", "@(Get-Date)", "$(Get-Date)", "date$(Get-Date)"])
def test_pwsh_binds_positionals_after_expression_values(check, value):
    decision = check(f"Set-Content -Value {value} notes.txt", shell="pwsh")
    assert decision.allowed, decision.reason
    decision = check(f"Set-Content -Value {value} mcp.json", shell="pwsh")
    assert not decision.allowed
    assert "mcp.json" in decision.reason and "full-access" in decision.reason


def test_pwsh_checks_nested_writes_inside_expression_values(check):
    decision = check("Set-Content -Value (Set-Content '{outside}/test.txt' sample) notes.txt", shell="pwsh")
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "Remove-Item m[c]p.json",
    "Set-Content -Path '*.json' sample",
    "Out-File -FilePath m*p.json -InputObject sample",
    "Tee-Object -FilePath m[c]p.json -InputObject sample",
    "'sample' > m*c*p.json",
    "Move-Item m[c]p.json moved.json",
    "Copy-Item '{outside}/m[c]p.json' .",
])
def test_pwsh_checks_wildcard_targets_including_copies_into_directories(check, command):
    decision = check(command, shell="pwsh")
    assert not decision.allowed
    assert "mcp.json" in decision.reason and "full-access" in decision.reason


@pytest.mark.parametrize("command", [
    "Remove-Item -LiteralPath m[c]p.json",
    "Remove-Item -LP:m[c]p.json",
    "Remove-Item -PSPath m[c]p.json",
    "Clear-Content notes-*.txt",
    "New-Item 'new[1].txt' -ItemType File",
])
def test_pwsh_allows_safe_globs_and_literal_brackets(check, command):
    decision = check(command, shell="pwsh")
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("path", ["missing*.txt", "sub*/notes.txt", "m?p.json", "'m`[c`]p.json'"])
def test_pwsh_refuses_globs_it_cannot_resolve(check, path):
    decision = check(f"Remove-Item {path}", shell="pwsh")
    assert not decision.allowed
    assert "statically checkable" in decision.reason


@pytest.mark.parametrize("modes,allowed", [
    ("[IO.FileMode]::Open, [IO.FileAccess]::Read", True),
    ("[ System.IO.FileMode ]::Open, [System.IO.FileAccess]::Read, [IO.FileShare]::Read", True),
    ("[IO.FileMode]::Open, [IO.FileAccess]::ReadWrite", False),
    ("[IO.FileMode]::Create, [IO.FileAccess]::Write", False),
    ("[IO.FileMode]::Open", False),
    ("[IO.FileMode]::Open, $access", False),
    ("$options", False),
])
def test_only_explicit_readonly_file_open_can_use_an_outside_path(check, modes, allowed):
    decision = check(f"[IO.File]::Open('{{outside}}/source.txt', {modes})", shell="pwsh")
    assert decision.allowed == allowed, decision.reason
    if not allowed:
        assert "outside the writable area" in decision.reason


def test_ambiguous_parameter_prefix_fails_closed(check):
    decision = check("Copy-Item notes.txt -De '{outside}/test.txt'", shell="pwsh")
    assert not decision.allowed


@pytest.mark.parametrize("shell,command", [
    ("pwsh", "cp.exe notes.txt '{outside}/test.txt'"),
    ("cmd", "copy notes.txt {native}\\test.txt"),
    (None, "cp notes.txt '{outside}/test.txt'"),
])
def test_native_copy_still_checks_its_destination(check, shell, command):
    if shell == "cmd" and os.name != "nt":
        pytest.skip("requires Windows path resolution")
    decision = check(command, shell=shell)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.skipif(os.name != "nt", reason="requires Windows path resolution")
@pytest.mark.parametrize("shell", ["pwsh", "cmd"])
@pytest.mark.parametrize("command", [
    r"del {native}\test.txt",
    r"move notes.txt {native}\test.txt",
    r"echo sample > {native}\test.txt",
])
def test_windows_shells_keep_backslashes_in_paths(check, shell, command):
    decision = check(command, shell=shell)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "del /q notes.txt",
    "rd /s /q build",
    "sc query wuauserv",
])
def test_cmd_switches_and_service_control_are_not_paths(check, command):
    decision = check(command, shell="cmd")
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", [
    "tee /cowagent-policy-outside",
    "tee.exe /q",
    "del.exe /q",
    "copy.exe notes.txt /b",
])
def test_cmd_checks_slash_paths_passed_to_external_tools(check, command):
    decision = check(command, shell="cmd")
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "[IO.File]::Delete('{outside}/test.txt')",
    "[IO.File]::Copy('notes.txt', '{outside}/test.txt')",
    "[IO.File]::Move('{outside}/test.txt', 'moved.txt')",
    "[IO.File]::Replace('notes.txt', '{outside}/test.txt', [NullString]::Value)",
    "[System.IO.File]::WriteAllTextAsync('{outside}/test.txt', 'x')",
    "[IO.Directory]::Delete('{outside}', $true)",
    "[IO.Directory]::CreateDirectory('{outside}/dir')",
    "[IO.Directory]::Move('build', '{outside}/dir')",
    "[ IO.Directory ]::'CreateDirectory'('{outside}/dir')",
    "[IO.File]::Replace('{outside}/test.txt', 'current.txt', [NullString]::Value)",
    "[IO.File]::Replace('notes.txt', 'current.txt', '{outside}/backup.txt')",
])
def test_other_static_file_writers_are_checked(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", [
    "[IO.Directory]::CreateDirectory($path)",
    "[IO.File]::Delete(('{outside}/test.txt'))",
    "[IO.File]::Replace('notes.txt', 'current.txt', $backup)",
])
def test_dynamic_static_writer_paths_fail_closed(check, command):
    decision = check(command)
    assert not decision.allowed
    assert "statically checkable" in decision.reason


@pytest.mark.parametrize("command", [
    "[IO.File]::ReadAllText('{outside}/test.txt')",
    "[IO.File]::Exists('{outside}/test.txt')",
    "[IO.Directory]::GetFiles('{outside}')",
    "[IO.File]::Copy('{outside}/test.txt', 'copy.txt')",
    "[IO.File]::WriteAllText('notes.txt', (Get-Content second.txt))",
    "[ IO.File ]::'ReadAllText'('{outside}/test.txt')",
    "[IO.File]::'Copy'('{outside}/test.txt', 'copy.txt')",
    "[IO.File]::Replace('notes.txt', 'current.txt', [NullString]::Value)",
    "[IO.File]::Replace('notes.txt', 'current.txt', [System.Management.Automation.Language.NullString]::Value)",
])
def test_static_reads_and_workspace_writes_are_allowed(check, command):
    decision = check(command)
    assert decision.allowed, decision.reason


def test_permission_check_uses_the_bash_tools_windows_shell(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agent.protocol.agent_stream import AgentStreamExecutor

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    monkeypatch.setattr(policy.tempfile, "gettempdir", lambda: str(workspace))
    executor = SimpleNamespace(
        tools={"bash": SimpleNamespace(_IS_WIN=True, windows_shell="pwsh")},
        agent=SimpleNamespace(
            effective_permission_mode=lambda: WORKSPACE_WRITE,
            effective_cwd=lambda: str(workspace),
            write_roots=lambda: [str(workspace)],
            protected_paths=lambda: [],
        ),
    )
    command = {"command": f"cp -Destination '{outside.as_posix()}/x.txt' notes.txt"}
    assert AgentStreamExecutor._permission_denial(executor, "bash", command)
    executor.tools["bash"]._IS_WIN = False
    assert AgentStreamExecutor._permission_denial(executor, "bash", command) is None

    executor.agent.effective_permission_mode = lambda: READ_ONLY
    command = {"command": "gc notes.txt"}
    assert AgentStreamExecutor._permission_denial(executor, "bash", command)
    executor.tools["bash"]._IS_WIN = True
    assert AgentStreamExecutor._permission_denial(executor, "bash", command) is None
    executor.tools["bash"].windows_shell = "cmd"
    assert AgentStreamExecutor._permission_denial(executor, "bash", command)
