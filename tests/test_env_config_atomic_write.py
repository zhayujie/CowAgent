"""A failed env_config save must not take the stored credentials with it.

``~/.cow/.env`` is where the agent keeps its API keys, and ``_write_env_file``
rebuilds the whole file from an in-memory dict on every ``set``/``delete``.
Writing straight into the file truncates it first, so anything that goes wrong
after that point -- a value the codec cannot encode, a full disk, the process
being killed -- leaves it empty. The next read then reports "nothing is
configured" rather than an error, and every key is already gone with no way
back.

Nothing here is a cache that could be rebuilt: the file is the only copy of the
credentials, and ``bridge/agent_initializer.py`` and ``agent/tools/bash/bash.py``
read it to decide which providers and skills are usable at all.

The file also never restricted its permissions, while ``mcp_oauth.json`` -- the
other credentials file in the same directory -- is written 0o600. Both are
pinned below.
"""

import errno
import json
import os
import stat

import pytest

from agent.tools.env_config.env_config import EnvConfig
from common.atomic_write import write_text_atomic

HEADER = (
    "# Environment variables for agent skills\n"
    "# Auto-managed by env_config tool\n\n"
)


@pytest.fixture()
def tool(tmp_path):
    """An EnvConfig pinned to a temp dir; the developer's ~/.cow is never used."""
    instance = EnvConfig(config={})
    instance.env_dir = str(tmp_path)
    instance.env_path = str(tmp_path / ".env")
    instance._ensure_env_file()
    return instance


def _text(tool):
    with open(tool.env_path, encoding="utf-8") as handle:
        return handle.read()


def _unencodable_value():
    """A value json accepts but utf-8 cannot encode.

    It stands in for everything that fails once the file has already been
    truncated: the document is rebuilt from a dict, so a full disk or a killed
    process reaches the same state. A model really does emit a lone surrogate
    for a broken emoji, and json.loads hands it through unchanged.
    """
    return json.loads('"\\ud800"')


def _a_disk_that_fills_up_at_the_swap(path):
    """Stand-in for ``os.fsync`` -- the last step before the file is swapped in.

    The temp file is already complete at that point, so a failure here is the
    case a plain in-place write gets wrong by construction.
    """
    raise OSError(errno.ENOSPC, "No space left on device")


# ---------------------------------------------------------------------------
# The helper the fix rests on.
# ---------------------------------------------------------------------------

def test_a_write_that_cannot_serialise_keeps_the_previous_file(tool):
    with open(tool.env_path, "w", encoding="utf-8") as handle:
        handle.write("KEEP=me\n")

    with pytest.raises(UnicodeEncodeError):
        write_text_atomic(tool.env_path, f"KEEP=me\nBAD={_unencodable_value()}\n")

    assert _text(tool) == "KEEP=me\n"


def test_a_write_that_fails_at_the_swap_keeps_the_previous_file(tool, monkeypatch):
    with open(tool.env_path, "w", encoding="utf-8") as handle:
        handle.write("KEEP=me\n")

    monkeypatch.setattr(os, "fsync", _a_disk_that_fills_up_at_the_swap)

    with pytest.raises(OSError):
        write_text_atomic(tool.env_path, "GONE=1\n")

    assert _text(tool) == "KEEP=me\n"


def test_a_write_leaves_no_temp_file_behind(tool):
    write_text_atomic(tool.env_path, "A_KEY=1\n")

    assert sorted(entry.name for entry in os.scandir(tool.env_dir)) == [".env"]


# ---------------------------------------------------------------------------
# The tool path the agent actually calls.
# ---------------------------------------------------------------------------

def test_failed_save_keeps_the_keys_already_stored(tool):
    """The regression: one unusable value used to wipe every configured key."""
    assert tool.execute(
        {"action": "set", "key": "OPENAI_API_KEY", "value": "sk-live-1234"}
    ).status == "success"

    failed = tool.execute(
        {"action": "set", "key": "GEMINI_API_KEY", "value": _unencodable_value()}
    )
    assert failed.status == "error"

    assert "OPENAI_API_KEY=sk-live-1234" in _text(tool)

    listed = tool.execute({"action": "list"})
    assert listed.status == "success"
    assert list(listed.result["variables"]) == ["OPENAI_API_KEY"]


def test_a_failed_save_leaves_no_temp_file_behind(tool):
    tool.execute({"action": "set", "key": "A_KEY", "value": "1"})
    tool.execute({"action": "set", "key": "B_KEY", "value": _unencodable_value()})

    assert sorted(entry.name for entry in os.scandir(tool.env_dir)) == [".env"]


def test_a_successful_save_keeps_the_file_layout(tool):
    """Byte for byte what the previous implementation produced."""
    tool.execute({"action": "set", "key": "B_KEY", "value": "2"})
    tool.execute({"action": "set", "key": "A_KEY", "value": "1"})

    assert _text(tool) == HEADER + "A_KEY=1\nB_KEY=2\n"


# ---------------------------------------------------------------------------
# Permissions: this file holds credentials.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_new_env_file_is_readable_by_its_owner_only(tool):
    tool.execute({"action": "set", "key": "OPENAI_API_KEY", "value": "sk-live-1234"})

    assert stat.S_IMODE(os.stat(tool.env_path).st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_group_readable_file_is_narrowed_on_its_next_use(tool):
    """One an earlier version created 0o644 is restricted, not left open."""
    os.chmod(tool.env_path, 0o644)

    tool.execute({"action": "list"})

    assert stat.S_IMODE(os.stat(tool.env_path).st_mode) == 0o600
