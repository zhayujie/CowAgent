r"""Local skill directories written the Windows way install from disk.

``cow skill install`` takes a local directory as well as a Skill Hub name or a
repository. On Windows that directory is typed or tab-completed as ``C:\...``,
``.\...`` or ``~\...``, so those must reach the local installer instead of
being looked up on Skill Hub, and the web console must keep refusing them.
"""

import json
from unittest.mock import patch

import pytest

import cli.commands.skill as skill_cmd

WINDOWS_PATHS = [
    r"C:\Users\me\skills\notes",
    "C:/Users/me/skills/notes",
    r"d:\notes",
    r".\notes",
    r"..\skills\notes",
    r"~\skills\notes",
    r"\skills\notes",
    r"\\server\share\notes",
]


@pytest.fixture
def routes(monkeypatch):
    """Record which installer each spec reaches instead of installing it."""
    calls = []

    def recorder(route):
        return lambda spec, *args, **kwargs: calls.append((route, spec))

    for route in ("_install_local", "_install_hub", "_install_github"):
        monkeypatch.setattr(skill_cmd, route, recorder(route))
    return calls


@pytest.mark.parametrize("spec", WINDOWS_PATHS)
def test_windows_paths_go_to_the_local_installer(routes, spec):
    result = skill_cmd.install_skill(spec)

    assert result.error is None, result.error
    assert routes == [("_install_local", spec)]


@pytest.mark.parametrize("spec,route", [
    ("./notes", "_install_local"),
    ("../skills/notes", "_install_local"),
    ("/opt/skills/notes", "_install_local"),
    ("~/skills/notes", "_install_local"),
    ("pptx", "_install_hub"),
    ("clawhub:steipete/gog", "_install_hub"),
    ("larksuite/cli", "_install_github"),
    ("github:larksuite/cli", "_install_github"),
    ("https://github.com/larksuite/cli", "_install_github"),
])
def test_other_specs_keep_their_route(routes, spec, route):
    result = skill_cmd.install_skill(spec)

    assert result.error is None, result.error
    assert [name for name, _ in routes] == [route]


@pytest.mark.parametrize("spec", WINDOWS_PATHS)
def test_console_refuses_windows_paths(routes, spec):
    from channel.web.api import skills as skills_api

    for source in ("hub", "clawhub", "github"):
        with pytest.raises(ValueError, match="local paths"):
            skills_api._market_spec(source, spec)

    body = json.dumps({"action": "install", "spec": spec}).encode()
    with patch.object(skills_api, "_require_auth"), \
            patch.object(skills_api.web, "header"), \
            patch.object(skills_api.web, "data", return_value=body), \
            patch.object(skills_api, "_skill_service"):
        response = json.loads(skills_api.SkillsHandler().POST())

    assert response == {"status": "error", "message": "local paths cannot be installed from the console"}
    assert routes == []
