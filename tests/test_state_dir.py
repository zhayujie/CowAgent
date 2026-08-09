import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from common import state_dir
from common.runtime_identity import (
    EMPTY_IDENTITY,
    RuntimeIdentity,
    current_agent_id,
    current_identity,
    identity_scope,
    submit,
    use_identity,
    wrap,
)


@pytest.fixture
def registry(tmp_path):
    reg = AgentRegistry(
        [
            AgentProfile(id="alpha", name="Alpha", workspace=str(tmp_path / "alpha")),
            AgentProfile(id="beta", name="Beta", workspace=str(tmp_path / "beta")),
        ],
        "alpha",
    )
    set_agent_registry(reg)
    yield reg
    set_agent_registry(None)


def test_absent_identity_resolves_to_default_agent(registry, tmp_path):
    assert state_dir.state_root() == tmp_path / "alpha"


def test_identity_selects_the_agent_workspace(registry, tmp_path):
    with identity_scope(agent_id="beta"):
        assert state_dir.state_root() == tmp_path / "beta"
        assert state_dir.scheduler_file() == tmp_path / "beta" / "scheduler" / "tasks.json"
    assert state_dir.state_root() == tmp_path / "alpha"


def test_unknown_agent_raises_instead_of_falling_back(registry):
    with identity_scope(agent_id="ghost"):
        with pytest.raises(state_dir.StateDirError, match="unknown agent id"):
            state_dir.state_root()


def test_user_scoped_paths_collapse_onto_the_root_without_a_user(registry, tmp_path):
    with identity_scope(agent_id="alpha"):
        assert state_dir.memory_dir() == tmp_path / "alpha" / "memory"
        assert state_dir.runs_dir() == tmp_path / "alpha" / "runs"


def test_user_scoped_paths_split_once_a_user_is_present(registry, tmp_path):
    with identity_scope(agent_id="alpha", user_id="u1"):
        assert state_dir.memory_dir() == tmp_path / "alpha" / "users" / "u1" / "memory"
        assert state_dir.runs_dir() == tmp_path / "alpha" / "users" / "u1" / "runs"
        # agent assets stay shared across users
        assert state_dir.skills_dir() == tmp_path / "alpha" / "skills"
        assert state_dir.mcp_config_file() == tmp_path / "alpha" / "mcp.json"


def test_the_index_stays_one_database_while_its_content_splits(registry, tmp_path):
    """One database, isolated by column, was a deliberate call: it also holds
    sessions and runs, and one file per user turns "what do I know about Wang"
    into a fan-out. The memory files it indexes do follow the user."""
    with identity_scope(agent_id="alpha", user_id="u1"):
        assert state_dir.memory_dir(ensure=False) == (
            tmp_path / "alpha" / "users" / "u1" / "memory"
        )
        assert state_dir.memory_index_db(ensure=False) == (
            tmp_path / "alpha" / "memory" / "long-term" / "index.db"
        )


def test_a_user_sits_beside_the_agents_not_under_one(registry, tmp_path):
    """The same person talking to two Agents has one profile, not two. Both
    resolve into the shared area, which is the default Agent's workspace."""
    with identity_scope(agent_id="beta", user_id="u1"):
        assert state_dir.user_root() == tmp_path / "alpha" / "users" / "u1"
        assert state_dir.memory_file() == tmp_path / "alpha" / "users" / "u1" / "MEMORY.md"
        # ...while what makes beta a different Agent stays with beta
        assert state_dir.tmp_dir(ensure=False) == tmp_path / "beta" / "tmp"


def test_a_second_agent_reads_the_shared_assets(registry, tmp_path):
    """Nothing to configure and nothing to copy: beta gets alpha's skills,
    knowledge and credentials, because they belong to whoever runs the
    instance rather than to one Agent."""
    with identity_scope(agent_id="beta"):
        assert state_dir.skills_dir() == tmp_path / "alpha" / "skills"
        assert state_dir.knowledge_dir() == tmp_path / "alpha" / "knowledge"
        assert state_dir.subagents_dir() == tmp_path / "alpha" / "subagents"
        assert state_dir.mcp_config_file() == tmp_path / "alpha" / "mcp.json"
        assert state_dir.env_file() == tmp_path / "alpha" / ".env"


def test_scaffolding_a_second_agent_does_not_opt_it_out(registry, tmp_path):
    """The one way this layout can fail quietly: something creates the
    directories on the Agent's behalf, and presence-based opt-out reads that as
    a deliberate choice. Booting beta has to leave the shared copy in charge."""
    from agent.prompt import ensure_workspace

    ensure_workspace(str(tmp_path / "alpha"), create_templates=False)
    ensure_workspace(str(tmp_path / "beta"), create_templates=False)

    for name in ("skills", "knowledge", "websites"):
        assert (tmp_path / "alpha" / name).is_dir(), name
        assert not (tmp_path / "beta" / name).exists(), name

    with identity_scope(agent_id="beta"):
        assert state_dir.skills_dir() == tmp_path / "alpha" / "skills"


def test_an_agent_opts_out_by_having_its_own_copy(registry, tmp_path):
    """Presence is the opt-out, so the Agent that wants private skills makes a
    directory and every other Agent is unaffected."""
    (tmp_path / "beta" / "skills").mkdir(parents=True)

    with identity_scope(agent_id="beta"):
        assert state_dir.skills_dir() == tmp_path / "beta" / "skills"
        # only the one it made: knowledge still comes from the shared copy
        assert state_dir.knowledge_dir() == tmp_path / "alpha" / "knowledge"


def test_legacy_config_keeps_the_configured_workspace(tmp_path):
    set_agent_registry(AgentRegistry.from_config({"agent_workspace": str(tmp_path / "cow")}))
    try:
        assert state_dir.state_root() == (tmp_path / "cow").resolve()
    finally:
        set_agent_registry(None)


def test_ensure_creates_directories_only_when_asked(registry, tmp_path):
    with identity_scope(agent_id="alpha"):
        assert not state_dir.knowledge_dir().exists()
        state_dir.knowledge_dir(ensure=True)
        assert (tmp_path / "alpha" / "knowledge").is_dir()


def test_scope_derives_from_the_ambient_identity():
    with use_identity(RuntimeIdentity(agent_id="a", user_id="u", session_id="s")):
        with identity_scope(run_id="r1"):
            ident = current_identity()
            assert (ident.agent_id, ident.user_id, ident.session_id) == ("a", "u", "s")
            assert ident.run_id == "r1"
        assert current_identity().run_id is None


def test_unknown_identity_field_is_rejected():
    with pytest.raises(TypeError, match="unknown identity fields"):
        with identity_scope(agnet_id="typo"):
            pass


def test_identity_does_not_leak_across_plain_threads():
    seen = []
    with use_identity(RuntimeIdentity(agent_id="alpha")):
        thread = threading.Thread(target=lambda: seen.append(current_agent_id()))
        thread.start()
        thread.join()
    assert seen == [None]


def test_submit_carries_identity_into_the_pool():
    with ThreadPoolExecutor(max_workers=1) as pool:
        with use_identity(RuntimeIdentity(agent_id="alpha", user_id="u1")):
            future = submit(pool, lambda: current_identity())
        ident = future.result()
    assert (ident.agent_id, ident.user_id) == ("alpha", "u1")


def test_wrap_carries_identity_into_a_thread():
    seen = []
    with use_identity(RuntimeIdentity(agent_id="beta")):
        target = wrap(lambda: seen.append(current_agent_id()))
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert seen == ["beta"]


def test_ambient_identity_is_empty_by_default():
    assert current_identity() == EMPTY_IDENTITY
    assert current_agent_id() is None


def test_consumers_follow_the_routed_agent(registry, tmp_path):
    """The point of the whole exercise: leaf code that never heard of an
    agent id still lands in the right workspace."""
    from agent.memory.config import MemoryConfig
    from agent.protocol.artifact import get_workspace_root
    from common.tmp_dir import TmpDir

    with identity_scope(agent_id="beta"):
        assert TmpDir().path().startswith(str(tmp_path / "beta"))
        assert get_workspace_root() == os.path.realpath(str(tmp_path / "beta"))
        assert MemoryConfig().workspace_root == str(tmp_path / "beta")


def test_base_override_reuses_the_layout_without_an_identity(tmp_path):
    assert state_dir.memory_dir(base=tmp_path / "ws") == tmp_path / "ws" / "memory"
    assert state_dir.output_dir(base=tmp_path / "ws") == tmp_path / "ws" / "output"


def test_base_names_the_agents_own_root_not_a_self_contained_one(registry, tmp_path):
    """MemoryConfig and the CLI pass a root instead of an identity, and they
    want the same answer the identity would have given: beta's own skills if it
    has them, the shared ones otherwise."""
    assert state_dir.skills_dir(base=tmp_path / "beta") == tmp_path / "alpha" / "skills"

    (tmp_path / "beta" / "skills").mkdir(parents=True)
    assert state_dir.skills_dir(base=tmp_path / "beta") == tmp_path / "beta" / "skills"


# One workspace root, every accessor, exactly the paths a single-Agent install
# has today. Splitting shared from per-user state has to cost existing installs
# nothing, so this is the acceptance test for the layout: it fails the moment a
# path moves, whether or not the directory happens to be there already.
_SINGLE_AGENT_LAYOUT = {
    "state_root": (),
    "skills_dir": ("skills",),
    "knowledge_dir": ("knowledge",),
    "websites_dir": ("websites",),
    "subagents_dir": ("subagents",),
    "mcp_config_file": ("mcp.json",),
    "env_file": (".env",),
    "scheduler_file": ("scheduler", "tasks.json"),
    "tmp_dir": ("tmp",),
    "user_root": (),
    "memory_dir": ("memory",),
    "memory_file": ("MEMORY.md",),
    "memory_index_db": ("memory", "long-term", "index.db"),
    "output_dir": ("output",),
    "runs_dir": ("runs",),
}


@pytest.mark.parametrize("prepopulated", [False, True], ids=["empty", "populated"])
def test_a_single_agent_install_keeps_every_path_it_has_today(tmp_path, prepopulated):
    root = tmp_path / "cow"
    if prepopulated:
        for parts in _SINGLE_AGENT_LAYOUT.values():
            (root / Path(*parts)).mkdir(parents=True, exist_ok=True)

    set_agent_registry(AgentRegistry.from_config({"agent_workspace": str(root)}))
    try:
        resolved = root.resolve()
        for name, parts in _SINGLE_AGENT_LAYOUT.items():
            accessor = getattr(state_dir, name)
            kwargs = {"ensure": False} if "ensure" in accessor.__code__.co_varnames else {}
            assert accessor(**kwargs) == resolved.joinpath(*parts), name
    finally:
        set_agent_registry(None)
