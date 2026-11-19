"""Global artifact routes can serve files in configured Agent workspaces."""

from urllib.parse import urlencode

import pytest

web = pytest.importorskip("web")

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry  # noqa: E402
from channel.web.api import files  # noqa: E402
from channel.web.core import _common  # noqa: E402
from config import conf  # noqa: E402


@pytest.fixture
def registered_files(tmp_path, monkeypatch):
    default = tmp_path / "default"
    helper = tmp_path / "helper"
    disabled = tmp_path / "disabled"
    for folder in (default, helper, disabled):
        folder.mkdir()
    registry = AgentRegistry(
        [
            AgentProfile("default", "Default", str(default)),
            AgentProfile("helper", "Helper", str(helper)),
            AgentProfile("disabled", "Disabled", str(disabled), enabled=False),
        ],
        "default",
    )
    set_agent_registry(registry)
    monkeypatch.setitem(conf(), "web_password", "")
    monkeypatch.setitem(conf(), "web_file_serve_root", str(default))
    monkeypatch.setattr(_common, "_PREVIEW_SECRET", b"local-test-preview-secret")
    app = web.application(
        ("/api/file", "FileServeHandler", "/preview/(.*)", "PreviewHandler"),
        vars(files),
    )
    return app, {"default": default, "helper": helper, "disabled": disabled}


def request_file(app, path, preview):
    url = (
        _common._build_preview_url(str(path))
        if preview
        else "/api/file?" + urlencode({"path": str(path)})
    )
    return app.request(url)


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("owner", ["default", "helper", "disabled"])
def test_registered_workspace_artifact_bytes_are_readable(
    registered_files, owner, preview
):
    app, folders = registered_files
    path = folders[owner] / "report.txt"
    path.write_bytes(b"Native artifact bytes\n")
    response = request_file(app, path, preview)
    assert response.status == "200 OK"
    assert response.data == path.read_bytes()
    assert response.headers["Content-Type"] == "text/plain"


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_unregistered_paths_and_workspace_symlink_escapes_stay_denied(
    registered_files, tmp_path, alias, preview
):
    app, folders = registered_files
    unrelated = tmp_path / "helper-unregistered"
    unrelated.mkdir()
    path = unrelated / "private.txt"
    path.write_bytes(b"outside configured roots")
    if alias:
        link = folders["helper"] / "linked.txt"
        try:
            link.symlink_to(path)
        except OSError:
            pytest.skip("symlinks unavailable")
        path = link
    response = request_file(app, path, preview)
    assert response.status == "404 Not Found"
    assert b"outside configured roots" not in response.data


def test_global_file_route_still_requires_authentication(registered_files, monkeypatch):
    app, folders = registered_files
    path = folders["helper"] / "report.txt"
    path.write_bytes(b"requires login")
    monkeypatch.setitem(conf(), "web_password", "test-password")
    response = request_file(app, path, False)
    assert response.status == "401 Unauthorized"
    assert b"requires login" not in response.data


def test_preview_route_rejects_unsigned_directory_tokens(registered_files):
    app, folders = registered_files
    path = folders["helper"] / "report.txt"
    path.write_bytes(b"requires signature")
    url = _common._build_preview_url(str(path))
    token, name = url.removeprefix("/preview/").split("/", 1)
    response = app.request("/preview/" + token.rsplit(".", 1)[0] + ".invalid/" + name)
    assert response.status == "404 Not Found"
    assert b"requires signature" not in response.data
