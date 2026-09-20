# encoding:utf-8
"""The sender identity is resolved on the message path and carried outward.

``RuntimeIdentity.user_id`` was defined and read by consumers but never set, so
every site that branches on it stayed on its default. These tests pin the three
places that make the value real: the channel entry point that resolves it, the
header builder that carries it, and the env mapping that hands it to a
subprocess.
"""

import os
from types import SimpleNamespace

from channel.chat_channel import ChatChannel
from common.runtime_identity import EMPTY_IDENTITY, RuntimeIdentity, use_identity
from common.utils import apply_client_source, current_agent_user_id


def _context(**overrides):
    context = {
        "agent_id": "primary",
        "session_id": "session-1",
        "msg": SimpleNamespace(from_user_id="sender-1", actual_user_id=None),
    }
    context.update(overrides)
    return context


def _identity_for(context):
    return ChatChannel._identity_for(object.__new__(ChatChannel), context)


class TestChannelResolvesSender:
    def test_sender_lands_on_the_identity(self):
        identity = _identity_for(_context())

        assert identity.user_id == "sender-1"
        assert identity.agent_id == "primary"
        assert identity.session_id == "session-1"

    def test_actual_user_id_wins_when_a_message_was_routed_on_someone_behalf(self):
        context = _context(
            msg=SimpleNamespace(from_user_id="group-1", actual_user_id="real-sender"),
        )

        assert _identity_for(context).user_id == "real-sender"

    def test_channel_without_an_end_user_leaves_it_unset(self):
        assert _identity_for(_context(msg=None)).user_id is None

    def test_blank_sender_is_unset_rather_than_an_empty_string(self):
        context = _context(msg=SimpleNamespace(from_user_id="", actual_user_id=""))

        assert _identity_for(context).user_id is None

    def test_session_id_is_not_used_as_a_substitute(self):
        context = _context(msg=SimpleNamespace(from_user_id="", actual_user_id=None))

        identity = _identity_for(context)

        assert identity.user_id is None
        assert identity.session_id == "session-1"


class TestHeaderCarriesTheSender:
    def test_helper_reads_the_ambient_identity(self):
        with use_identity(RuntimeIdentity(user_id="sender-1")):
            assert current_agent_user_id() == "sender-1"

    def test_helper_returns_none_when_unset(self):
        os.environ.pop("COW_AGENT_USER_ID", None)
        with use_identity(EMPTY_IDENTITY):
            assert current_agent_user_id() is None

    def test_header_is_emitted_alongside_the_run_id(self):
        with use_identity(RuntimeIdentity(run_id="run-1", user_id="sender-1")):
            headers = apply_client_source({})

        assert headers["X-Agent-User-Id"] == "sender-1"
        assert headers["X-Agent-Run-Id"] == "run-1"

    def test_header_is_omitted_when_there_is_no_sender(self):
        with use_identity(EMPTY_IDENTITY):
            headers = apply_client_source({})

        assert "X-Agent-User-Id" not in headers

    def test_env_var_is_the_fallback_outside_a_run(self):
        os.environ["COW_AGENT_USER_ID"] = "sender-from-env"
        try:
            with use_identity(EMPTY_IDENTITY):
                headers = apply_client_source({})
                assert headers["X-Agent-User-Id"] == "sender-from-env"
        finally:
            del os.environ["COW_AGENT_USER_ID"]

    def test_ambient_identity_beats_the_env_var(self):
        os.environ["COW_AGENT_USER_ID"] = "sender-from-env"
        try:
            with use_identity(RuntimeIdentity(user_id="sender-ambient")):
                headers = apply_client_source({})
                assert headers["X-Agent-User-Id"] == "sender-ambient"
        finally:
            del os.environ["COW_AGENT_USER_ID"]


class TestEnvironmentReachesChildProcesses:
    """Run a real command and read what the child process actually saw.

    The probe goes through python rather than a shell builtin, so it reads the
    same way under cmd.exe and bash.
    """

    # Reads the variable back through python so the probe is identical under
    # cmd.exe and bash, where the shell's own expansion syntax differs.
    _PROBE = "python -c \"import os; print(os.environ.get('COW_AGENT_USER_ID') or 'unset')\""

    def _run(self, tmp_path, command):
        from agent.tools.bash.bash import Bash

        tool = Bash()
        tool.cwd = str(tmp_path)
        return tool.execute({"command": command})

    def test_child_env_receives_the_sender(self, tmp_path):
        with use_identity(RuntimeIdentity(run_id="run-1", user_id="sender-1")):
            result = self._run(tmp_path, self._PROBE)

        assert result.result["output"].strip() == "sender-1"

    def test_env_has_no_sender_when_there_is_none(self, tmp_path):
        os.environ.pop("COW_AGENT_USER_ID", None)
        with use_identity(EMPTY_IDENTITY):
            result = self._run(tmp_path, self._PROBE)

        assert result.result["output"].strip() == "unset"
