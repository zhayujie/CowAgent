"""A background command belongs to the conversation that started it.

The registry lives at module level, so every conversation in one process shares
it. Without an owner on each job, a poll from another conversation answers for
it - and the "no such id, currently tracked: ..." message names it, so the id is
not even a secret. The same holds for the cap: a busy conversation evicted
another's finished job, losing its exit code and output.
"""

import os
import sys
import time

import pytest

from agent.tools.bash import background
from agent.tools.bash.bash import Bash
from common.runtime_identity import identity_scope

# Runs on cmd.exe and on sh, so the tests do not need a POSIX shell.
PRINTS_THEN_SLEEPS = f'"{sys.executable}" -c "import time; print(\'owner-only\'); time.sleep(60)"'
QUICK = f'"{sys.executable}" -c "pass"'

OWNER = {"agent_id": "writer", "session_id": "chat-A"}
OTHER = {"agent_id": "writer", "session_id": "chat-B"}


@pytest.fixture(autouse=True)
def isolated_registry():
    background.reset()
    yield
    background.reset()


def start(tmp_path, command=PRINTS_THEN_SLEEPS, **identity):
    with identity_scope(**identity):
        return background.start(command, str(tmp_path), os.environ.copy())


def wait_until_done(job_id, timeout=20, **identity):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with identity_scope(**identity):
            state = background.read(job_id)
        if state is not None and not state["running"]:
            return state
        time.sleep(0.05)
    raise AssertionError(f"background job {job_id} did not finish in {timeout}s")


def test_another_conversation_cannot_read_the_output(tmp_path):
    job = start(tmp_path, **OWNER)
    with identity_scope(**OWNER):
        assert background.read(job) is not None

    with identity_scope(**OTHER):
        assert background.read(job) is None, "a poll must not answer for another conversation"
        assert background.list_jobs() == []


def test_another_conversation_cannot_kill_the_job(tmp_path):
    job = start(tmp_path, **OWNER)

    with identity_scope(**OTHER):
        assert background.kill(job) is None

    with identity_scope(**OWNER):
        assert background.read(job)["running"], "the owner's server must still be up"


def test_the_unknown_id_message_names_only_the_callers_jobs(tmp_path):
    job = start(tmp_path, **OWNER)

    with identity_scope(**OTHER):
        result = Bash({"cwd": str(tmp_path)}).execute({"bash_id": "bash_missing"})
        assert result.status == "error"
        assert "none are being tracked" in str(result.result)
        assert job not in str(result.result)

    with identity_scope(**OWNER):
        result = Bash({"cwd": str(tmp_path)}).execute({"bash_id": "bash_missing"})
        assert job in str(result.result), "the owner must still be told what it has"


def test_eviction_drops_only_the_callers_own_history(tmp_path, monkeypatch):
    monkeypatch.setattr(background, "_MAX_JOBS", 2)
    # Started first, so a registry-wide cap would pick this one to drop.
    theirs = start(tmp_path, QUICK, **OTHER)
    wait_until_done(theirs, **OTHER)
    mine = [start(tmp_path, QUICK, **OWNER) for _ in range(2)]
    for job in mine:
        wait_until_done(job, **OWNER)

    overflow = start(tmp_path, QUICK, **OWNER)
    wait_until_done(overflow, **OWNER)

    with identity_scope(**OWNER):
        assert background.read(mine[0]) is None, "the cap must still bound a conversation"
        assert background.read(overflow) is not None
    with identity_scope(**OTHER):
        assert background.read(theirs) is not None, "another conversation's cap must not evict this"


def test_the_same_conversation_still_reads_and_kills_its_own_job(tmp_path):
    job = start(tmp_path, **OWNER)
    with identity_scope(**OWNER):
        assert background.read(job) is not None
        assert background.kill(job) is True
        assert [j["id"] for j in background.list_jobs()] == [job]


def test_a_new_task_in_the_same_conversation_still_sees_the_job(tmp_path):
    job = start(tmp_path, **dict(OWNER, run_id="first-task"))
    with identity_scope(**dict(OWNER, run_id="next-task")):
        assert background.read(job) is not None, "a job outlives the task that started it"
