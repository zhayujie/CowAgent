# encoding:utf-8
"""workspace-write must catch the destination when it arrives as a flag.

``cp -t DIR`` copies into DIR and ``unzip -d DIR`` extracts into DIR, so the
policy read the last operand as the destination and let the write through.
``tar`` writes the archive ``-f`` names when it creates one and the directory
``-C`` names when it extracts one.
"""

import pytest

from agent.permission.policy import WORKSPACE_WRITE, check_tool_call

WORKSPACE = "H:/ws"


def _workspace_write(command):
    return check_tool_call(WORKSPACE_WRITE, "bash", {"command": command}, WORKSPACE)


# The destination arrives as a flag instead of as an operand.
FLAG_DESTINATIONS = [
    "cp -t /etc/ src.txt",
    "cp -t/etc/ src.txt",
    "cp --target-directory /etc/ src.txt",
    "cp --target-directory=/etc/ src.txt",
    "install -t /etc/ src.txt",
    "ln -t /etc/ src.txt",
    "mv -t /etc/ src.txt",
    "mv -t/etc/ src.txt",
    "mv --target-directory=/etc/ src.txt",
    "unzip -d /etc/ payload.zip",
    "unzip -d/etc/ payload.zip",
    "tar -cf /etc/evil.tar .",
    "tar -czf /etc/evil.tgz .",
    "tar -cf /etc/evil.tar -C /etc passwd",
    "tar --create --file=/etc/evil.tar .",
    "tar -xf payload.tar -C /etc/",
    "tar -xzf payload.tgz -C /etc/",
    "tar -xf payload.tar -C/etc/",
    "tar -xzf payload.tgz --directory=/etc/",
    "tar --extract --file=payload.tar --directory=/etc/",
    "tar -xf payload.tar -C sub/ -C /etc/",
    "rsync -a src/ /etc/",
]

# The same forms, writing inside the workspace, plus a tar run that only reads.
INSIDE_FLAG_DESTINATIONS = [
    "cp -t sub/ src.txt",
    "cp --target-directory=sub/ src.txt",
    "install -t sub/ src.txt",
    "ln -t sub/ src.txt",
    "mv -t sub/ src.txt",
    "unzip -d sub/ payload.zip",
    "tar -cf out.tar .",
    "tar -czf out.tgz .",
    "tar --create --file=out.tar .",
    "tar -xf payload.tar -C sub/",
    "tar -xzf payload.tgz --directory=sub/",
    "tar -xf payload.tar -C sub/ -C deep/",
    "tar -tf payload.tar",
    "tar --list --file=payload.tar",
]


@pytest.mark.parametrize("command", FLAG_DESTINATIONS)
def test_workspace_write_refuses_a_destination_named_by_a_flag(command):
    decision = _workspace_write(command)
    assert not decision.allowed, f"{command!r} escaped the roots"
    # The reason has to name the path that was refused, or the model retries.
    assert "outside the writable area" in decision.reason


@pytest.mark.parametrize("command", INSIDE_FLAG_DESTINATIONS)
def test_workspace_write_allows_a_flag_destination_inside_the_roots(command):
    assert _workspace_write(command).allowed
