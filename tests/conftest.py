# encoding:utf-8
"""Keep the suite out of the developer's real workspace.

Whatever a test loads config for, ``agent_workspace`` ends up pointing at the
directory the person running the suite actually uses, and anything that resolves
a path without pinning one down writes there. Task records reached a live
database this way; the memory files, scheduler store and tmp directory are all
reachable by the same route.

Only that one key is redirected, and only for the session. Loading the config
outright would be worse than the problem: tests would inherit the developer's
model, language and channel settings, and start passing or failing on them.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True, scope="session")
def workspace_out_of_the_way():
    import config as config_module

    with tempfile.TemporaryDirectory(prefix="cow-tests-") as tmp:
        workspace = os.path.join(tmp, "cow")
        real_load = config_module.load_config

        def load_then_redirect():
            real_load()
            config_module.conf()["agent_workspace"] = workspace

        # Applied now for tests that never load, and re-applied after any that
        # do, since loading replaces the value with the real one.
        config_module.conf()["agent_workspace"] = workspace
        config_module.load_config = load_then_redirect

        # Collection imports every test module before this runs, and a module
        # that loads config on import can leave a registry or a store already
        # resolved against the real path. Drop those.
        _forget_resolved_paths()
        try:
            yield workspace
        finally:
            config_module.load_config = real_load


def _forget_resolved_paths():
    from agent.memory import clear_conversation_store_cache
    from agent.memory.config import reset_memory_configs
    from agent.registry import set_agent_registry

    set_agent_registry(None)
    reset_memory_configs()
    clear_conversation_store_cache()
