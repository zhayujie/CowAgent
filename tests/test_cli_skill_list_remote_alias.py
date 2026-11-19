"""`cow skill list` accepts -r as well as --remote, like the in-chat /skill list."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cli.commands.skill import skill


@pytest.mark.parametrize("flag", ["--remote", "-r"])
def test_remote_flag_lists_skill_hub(flag):
    with patch("cli.commands.skill._list_remote") as remote, \
            patch("cli.commands.skill._list_local") as local:
        result = CliRunner().invoke(skill, ["list", flag, "--page", "2"])

    assert result.exit_code == 0, result.output
    remote.assert_called_once_with(page=2)
    local.assert_not_called()


def test_without_flag_lists_local_skills():
    with patch("cli.commands.skill._list_remote") as remote, \
            patch("cli.commands.skill._list_local") as local:
        result = CliRunner().invoke(skill, ["list"])

    assert result.exit_code == 0, result.output
    local.assert_called_once_with()
    remote.assert_not_called()
