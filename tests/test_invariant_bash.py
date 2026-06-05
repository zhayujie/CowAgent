import pytest
from agent.tools.bash.bash import Bash


@pytest.mark.parametrize("command", [
    "cat ~/.cow/.env",
    "cat .cow/.env",
    "less ~/.cow/.env",
    "cat /home/user/.cow/.env",
])
def test_credential_file_access_is_blocked(command):
    result = Bash().execute({"command": command})
    assert result.status == "error", f"Expected blocked result for: {command}"
    assert "Access denied" in str(result.result)


@pytest.mark.parametrize("command", [
    "ls ~/.cow/skills",
    "ls ~/.cow/",
    "echo hello",
])
def test_legitimate_cow_directory_access_is_not_blocked(command):
    result = Bash().execute({"command": command})
    assert "Access denied" not in str(result.result)
