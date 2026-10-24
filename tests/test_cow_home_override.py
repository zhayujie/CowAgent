"""COW_HOME moves the agent's credentials with the rest of the desktop data.

The Windows installer can put app data under a folder other than the user's
home (issue #3136). The desktop client then sets COW_HOME, and the API keys file
and the guards that protect it must all follow it: a key written to one place
while the guard watches another is readable through the file tools.
"""

import os

from agent.tools.env_config.env_config import EnvConfig
from agent.tools.utils.credentials import is_credential_path


def test_keys_are_stored_and_guarded_under_cow_home(tmp_path, monkeypatch):
    cow_dir = tmp_path / "Data" / ".cow"
    monkeypatch.setenv("COW_HOME", str(cow_dir))

    EnvConfig(config={}).execute({"action": "set", "key": "OPENAI_API_KEY", "value": "sk-test"})

    env_file = cow_dir / ".env"
    assert "OPENAI_API_KEY=sk-test" in env_file.read_text(encoding="utf-8")
    assert is_credential_path(str(env_file))
    home_env = os.path.join(os.path.expanduser("~"), ".cow", ".env")
    assert not os.path.exists(home_env)


def test_without_cow_home_keys_stay_in_the_home_folder(monkeypatch):
    monkeypatch.delenv("COW_HOME", raising=False)
    home_env = os.path.join(os.path.expanduser("~"), ".cow", ".env")

    assert is_credential_path(home_env)
