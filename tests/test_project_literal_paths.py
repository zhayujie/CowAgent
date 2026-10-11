"""Project picker paths are filesystem identities, not text to trim."""

import json
import os
from pathlib import Path
from urllib.parse import urlencode

import pytest
import web

from agent.workspace import project_store
from channel.web.api import workspace

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Windows normalizes trailing spaces in directory names")


@pytest.fixture
def projects(tmp_path, monkeypatch):
    import common.state_dir as state_dir

    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(workspace, "_require_auth", lambda: None)
    plain = tmp_path / "project"
    spaced = tmp_path / "project "
    plain.mkdir()
    spaced.mkdir()
    (spaced / "child").mkdir()
    app = web.application(
        ("/browse", "ProjectBrowseHandler", "/manage", "ProjectManageHandler",
         "/order", "ProjectOrderHandler"), vars(workspace)
    )
    return app, str(plain), str(spaced)


def request(app, endpoint, method="GET", **body):
    response = app.request(endpoint, method=method, data=json.dumps(body))
    assert response.status == "200 OK"
    result = json.loads(response.data)
    assert result["status"] == "success", result
    return result


def test_picker_browse_preserves_selected_directory(projects):
    app, plain, spaced = projects
    # The native picker first receives exact paths from scandir, then sends
    # that selected path back when navigating into the folder.
    parent = request(app, "/browse?" + urlencode({"path": str(Path(plain).parent)}))
    selected = next(entry["path"] for entry in parent["dirs"] if entry["name"] == "project ")
    assert selected == spaced
    child = request(app, "/browse?" + urlencode({"path": selected}))
    assert child["path"] == spaced
    assert [entry["name"] for entry in child["dirs"]] == ["child"]


def test_selection_uses_exact_picker_path(projects):
    _, plain, spaced = projects
    assert project_store.set_project_dir("s1", spaced) == spaced
    assert project_store.get_project_dir("s1") == spaced
    assert project_store.get_project_map() == {"s1": spaced}
    assert project_store.list_recents() == [{"path": spaced, "name": "project "}]
    assert plain != spaced


def test_rename_keeps_sibling_project_metadata_separate(projects):
    app, plain, spaced = projects
    project_store.rename_project(plain, "Plain")
    result = request(app, "/manage", "PUT", path=spaced, name="Spaced")
    assert result["name"] == "Spaced"
    assert project_store.display_name_for(spaced) == "Spaced"
    assert project_store.display_name_for(plain) == "Plain"


def test_order_retains_both_directory_identities(projects):
    app, plain, spaced = projects
    request(app, "/order", "POST", order=[plain, spaced, project_store.DEFAULT_SPACE_KEY])
    assert project_store.get_order() == [plain, spaced, project_store.DEFAULT_SPACE_KEY]


def test_delete_forgets_only_selected_project_record(projects):
    app, plain, spaced = projects
    # Seed valid persisted bindings without going through the faulty selector.
    project_store._save({
        "sessions": {"default::plain": {"path": plain}, "default::spaced": {"path": spaced}},
        "recents": [{"path": plain}, {"path": spaced}],
        "meta": {plain: {"display_name": "Plain"}, spaced: {"display_name": "Spaced"}},
        "order": [plain, spaced],
    })
    result = request(app, "/manage", "DELETE", path=spaced)
    assert result["unbound"] == 1
    assert project_store.get_project_map() == {"plain": plain}
    assert project_store.list_recents() == [{"path": plain, "name": "Plain"}]
    assert project_store.get_order() == [plain]
    assert project_store.display_name_for(spaced) == "project "


def test_empty_selection_and_duplicate_order_controls(projects):
    app, plain, _ = projects
    project_store.set_project_dir("s1", plain)
    assert project_store.set_project_dir("s1", None) is None
    assert project_store.get_project_dir("s1") is None
    request(app, "/order", "POST", order=["", plain, plain, None, project_store.DEFAULT_SPACE_KEY])
    assert project_store.get_order() == [plain, project_store.DEFAULT_SPACE_KEY]
