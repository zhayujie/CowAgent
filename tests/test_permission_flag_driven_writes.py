# encoding:utf-8
"""Read-only and workspace-write must catch writes that arrive as a flag, not a redirect."""

import pytest

from agent.permission.policy import READ_ONLY, WORKSPACE_WRITE, check_tool_call

WORKSPACE = "H:/ws"


def _read_only(command, shell=None):
    return check_tool_call(READ_ONLY, "bash", {"command": command}, shell=shell)


def _workspace_write(command):
    return check_tool_call(WORKSPACE_WRITE, "bash", {"command": command}, WORKSPACE)


# --- the bypasses ---------------------------------------------------------

READ_ONLY_WRITES = [
    # find: deletes, or writes through -fls / -fprint, or runs another command
    "find . -name '*.log' -delete",
    "find . -type f -exec rm {} ;",
    "find . -type f -execdir rm {} ;",
    "find . -type f -fls listing.txt",
    "find . -type f -fprint stolen.txt",
    "find . -type f -fprintf stolen.txt %p",
    "find . -type f -ok rm {} ;",
    "find . -type f -okdir rm {} ;",
    "find /etc -delete",
    # fd shares find's -exec family
    "fd -e txt --exec rm {} ;",
    "fd -e txt -X rm",
    # sort writes its output file instead of stdout
    "sort -o out.txt in.txt",
    "sort --output=out.txt in.txt",
    "sort --output=out.txt",
    "sort -uo out.txt in.txt",
    "sed -i.bak s/a/b/ f.txt",
    "sed -Ei s/a/b/ f.txt",
    "xxd dump.bin out.hex",
    # xxd -r converts a hex dump back into the named binary
    "xxd -r dump.hex out.bin",
    "xxd --reverse dump.hex out.bin",
    # sed's `w` command writes the named file from inside the script
    "sed -e 'w written.txt' in.txt",
    "sed -e 's/a/b/;w written.txt' in.txt",
    # awk can hand a string to the shell
    "awk 'BEGIN{system(\"rm -f victim\")}'",
    # the redirect scan does not catch it when it is piped or sequenced
    "find . -name '*.log' -delete | cat",
    "sort -o out.txt in.txt && echo done",
    "Start-Process cmd.exe -Verb RunAs",
]

# --- what must keep working ----------------------------------------------

READ_ONLY_OK = [
    "ls -la",
    "grep -r foo .",
    "tr a b < in.txt",
    "cat a.txt",
    # the plain reading forms of the guarded commands
    "find . -name '*.log'",
    "find . -type f -print",
    "fd -e txt",
    "sort in.txt",
    "sort -k2 in.txt",
    "sort -u in.txt",
    "xxd dump.hex",
    "xxd -l 16 dump.bin",
    "fd --print0 -e txt",
    "sed -n '1,10p' in.txt",
    "sed 's/a/b/' in.txt",
    "awk '{print $1}' f.txt",
]

PWSH_READ_ONLY_OK = [
    "Get-Content -LiteralPath C:/outside.txt",
    "Get-ChildItem -Path C:/outside",
    "Select-String -Path C:/outside.txt -Pattern x",
    "gc C:/outside.txt",
    "gci C:/outside",
    "sls -Path C:/outside.txt -Pattern x",
    "Get-Item C:/outside.txt",
    "Test-Path C:/outside.txt",
]


@pytest.mark.parametrize("command", READ_ONLY_WRITES)
def test_read_only_refuses_a_write_hidden_behind_a_flag(command):
    decision = _read_only(command)
    assert not decision.allowed, f"{command!r} was allowed to write"
    # The reason has to name the form, or the model retries the same thing.
    assert command.split()[0] in decision.reason


@pytest.mark.parametrize("command", READ_ONLY_OK)
def test_read_only_still_allows_the_reading_forms(command):
    assert _read_only(command).allowed


@pytest.mark.parametrize("command", PWSH_READ_ONLY_OK)
def test_powershell_read_commands_are_only_allowlisted_for_pwsh(command):
    assert _read_only(command, shell="pwsh").allowed
    for shell in (None, "cmd"):
        assert not _read_only(command, shell=shell).allowed

    name, args = command.split(maxsplit=1)
    assert not _read_only(f"{name}.exe {args}", shell="pwsh").allowed
    assert not _read_only(fr".\{name}.exe {args}", shell="pwsh").allowed


# --- workspace-write: the same commands, confined to the workspace --------

WORKSPACE_WRITE_DENY = [
    "sort -o /etc/out.txt in.txt",
    "sort --output=/etc/out.txt in.txt",
    "find /etc -delete",
    "find /etc -type f -exec rm {} ;",
    "xxd -r /etc/dump.hex /etc/out.bin",
    "sed -i s/a/b/ /etc/f.txt",
    "sed -e 'w /etc/written.txt' in.txt",
    "sed -i.bak s/a/b/ /etc/f.txt",
    "sort -uo /etc/out.txt in.txt",
    "fd . /etc -x rm",
    # the checks that already existed
    "rm /etc/passwd",
    "cp a.txt /etc/b.txt",
    "cat a.txt > /etc/b.txt",
    "Set-Content -Path /outside.txt -Value x",
    "Out-File -FilePath /outside.txt -InputObject x",
    "Remove-Item -LiteralPath /outside.txt",
    "New-Item -Path /outside.txt",
    "Copy-Item -Path inside.txt -Destination /outside.txt",
    "Move-Item -Path inside.txt -Destination /outside.txt",
    "Move-Item -Path /outside.txt -Destination inside.txt",
    "[IO.File]::WriteAllText('/outside.txt', 'x')",
    "[IO.File]::WriteAllText($path, 'x')",
    "ri -LiteralPath /outside.txt",
    "cpi -Path inside.txt -Destination /outside.txt",
    "mi -Path inside.txt -Destination /outside.txt",
    "ni -Path /outside.txt",
    "sc -Path /outside.txt -Value x",
    "Add-Content -Path /outside.txt -Value x",
    "Clear-Content -LiteralPath /outside.txt",
    "Rename-Item -Path /outside.txt -NewName renamed.txt",
    "Tee-Object -FilePath /outside.txt -InputObject x",
    "Expand-Archive -Path archive.zip -DestinationPath /outside",
    "[IO.File]::WriteAllBytes('/outside.bin', $bytes)",
    "[IO.File]::AppendAllText('/outside.txt', 'x')",
    "[IO.File]::WriteAllLines('/outside.txt', $lines)",
    "[IO.File]::AppendAllText($path, 'x')",
    "Remove-Item /outside.txt -Recurse",
    "Set-Content /outside.txt hi",
    "Add-Content /outside.txt hi",
    "Clear-Content /outside.txt",
    "New-Item /outside.txt -ItemType File",
    "Copy-Item inside.txt /outside.txt",
    "Move-Item /outside.txt inside.txt",
    "Move-Item inside.txt /outside.txt",
    "Rename-Item /outside.txt renamed.txt",
    "Tee-Object /outside.txt",
    "Expand-Archive archive.zip /outside",
    "Remove-Item -Recurse",
    "Set-Content -Value hi",
]

WORKSPACE_WRITE_OK = [
    # writing inside the workspace is what this mode is for
    "sort -o out.txt in.txt",
    "find . -name '*.log' -delete",
    "sed -i s/a/b/ f.txt",
    "sed -e 'w written.txt' in.txt",
    # reading outside it always worked and must keep working
    "cat /etc/hostname",
    "Set-Content -Path out.txt -Value x",
    "Out-File -FilePath out.txt -InputObject x",
    "Remove-Item -LiteralPath out.txt",
    "New-Item -Path out.txt",
    "Copy-Item -Path /etc/hosts -Destination copy.txt",
    "Move-Item -Path move-source.txt -Destination moved.txt",
    "Remove-Item ./build -Recurse",
    "Set-Content notes.txt hi",
    "Copy-Item /etc/hosts copy.txt",
    "Move-Item move-source.txt moved.txt",
    "Add-Content notes.txt hi",
    "Clear-Content notes.txt",
    "Rename-Item old.txt new.txt",
    "Tee-Object notes.txt",
    "Expand-Archive archive.zip extracted",
    "[IO.File]::WriteAllText('out.txt', 'x')",
    "[IO.File]::WriteAllBytes('out.bin', $bytes)",
    "[IO.File]::AppendAllText('out.txt', 'x')",
    "[IO.File]::WriteAllLines('out.txt', $lines)",
    "Move-Item -Path inside.txt -Destination moved.txt",
    "ls -la /etc",
    "find . -name '*.log'",
    "fd foo /etc",
    "xxd /etc/hosts",
    "xxd -l 16 /etc/hosts",
]


@pytest.mark.parametrize("command", WORKSPACE_WRITE_DENY)
def test_workspace_write_refuses_a_write_outside_the_roots(command):
    assert not _workspace_write(command).allowed, f"{command!r} escaped the roots"


@pytest.mark.parametrize("command", WORKSPACE_WRITE_OK)
def test_workspace_write_allows_inside_the_roots(command):
    assert _workspace_write(command).allowed


@pytest.mark.parametrize("command", [
    "Start-Process cmd.exe -Verb RunAs",
    "start-process -FilePath powershell.exe -Verb:RunAs",
    "Start-Process powershell.exe -Verb 'RunAs'",
])
def test_workspace_write_refuses_powershell_elevation(command):
    assert not _workspace_write(command).allowed


def test_an_unparsable_line_still_fails_closed_in_read_only():
    # Unchanged behaviour, kept so a future parser change cannot quietly turn
    # this into a fail-open path.
    assert not _read_only("echo 'unterminated").allowed
