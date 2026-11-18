# encoding:utf-8
"""The bash safety scanner flags `rm` of `/` with recursive+force flags however they are spelled."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.bash.bash import Bash

DESTROY_ROOT = "This command will delete the entire filesystem"


@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm -r -f /",
    "rm -f -r /",
    "rm --recursive -f /",
    "rm --force --recursive /",
    "rm -rf --preserve-root /",
])
def test_recursive_force_root_is_flagged(command):
    assert Bash._get_safety_warning(None, command) == DESTROY_ROOT


@pytest.mark.parametrize("command", ["Stop-Computer", "Restart-Computer -Force"])
def test_powershell_power_controls_are_warned(command):
    assert Bash._get_safety_warning(None, command) == "This command will shut down or restart the system"


@pytest.mark.parametrize("command", ["rm -f /", "rm --recursive /", "rm -rf /tmp/x"])
def test_partial_flags_or_subdir_not_flagged(command):
    assert Bash._get_safety_warning(None, command) == ""
