"""A path saved before an iOS app update names the old data container; it is
read at the same place in the current one."""

import os
from types import SimpleNamespace

import pytest

from common import moved_paths
from common.moved_paths import rebase_moved_path

OLD = "BD787D43-AC62-446B-BA8C-DC3ED964A0D3"
NEW = "363BD692-DD63-4F62-9D13-B6696AEA95E2"


def _container(tmp_path, uuid):
    return tmp_path / "Containers" / "Data" / "Application" / uuid


@pytest.fixture
def ios_home(tmp_path, monkeypatch):
    home = _container(tmp_path, NEW) / "Library" / "Application Support"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    moved_paths._current_container.cache_clear()
    yield home
    moved_paths._current_container.cache_clear()


def test_a_page_from_before_the_update_is_found_in_the_new_container(tmp_path, ios_home):
    page = ios_home / "cow" / "websites" / "report.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html></html>")
    old = str(_container(tmp_path, OLD) / "Library" / "Application Support" / "cow" / "websites" / "report.html")

    assert rebase_moved_path(old) == os.path.join(os.path.realpath(_container(tmp_path, NEW)), "Library",
                                                  "Application Support", "cow", "websites", "report.html")


def test_a_path_in_a_container_that_still_exists_is_left_alone(tmp_path, ios_home):
    other = _container(tmp_path, OLD) / "Documents"
    other.mkdir(parents=True)

    assert rebase_moved_path(str(other / "a.md")) == str(other / "a.md")


def test_a_path_in_the_current_container_is_left_alone(tmp_path, ios_home):
    assert rebase_moved_path(str(ios_home / "missing.md")) == str(ios_home / "missing.md")


def test_the_agent_reads_a_file_by_the_path_it_noted_before_the_update(tmp_path, ios_home):
    from agent.tools.read.read import Read

    note = ios_home / "cow" / "notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("kept across the update")
    old = str(_container(tmp_path, OLD) / "Library" / "Application Support" / "cow" / "notes.md")

    result = Read({"cwd": str(ios_home / "cow")}).execute({"path": old})

    assert result.status == "success"
    assert "kept across the update" in str(result.result)


def test_the_agent_writes_a_new_file_under_a_path_from_before_the_update(tmp_path, ios_home):
    from agent.tools.write.write import Write

    (ios_home / "cow").mkdir()
    old = str(_container(tmp_path, OLD) / "Library" / "Application Support" / "cow" / "new.md")

    result = Write({"cwd": str(ios_home / "cow")}).execute({"path": old, "content": "hi"})

    assert result.status == "success"
    assert (ios_home / "cow" / "new.md").read_text() == "hi"
    assert not _container(tmp_path, OLD).exists()


def test_an_artifact_from_before_the_update_still_opens(tmp_path, ios_home):
    from channel.web.api.artifacts import _payload

    page = ios_home / "cow" / "websites" / "report.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html></html>")
    old = str(_container(tmp_path, OLD) / "Library" / "Application Support" / "cow" / "websites" / "report.html")
    row = {
        "id": 1, "agent_id": "", "session_id": "s", "session_title": "", "turn_seq": 1,
        "session_exists": 1, "session_channel": "web", "path": old, "kind": "html", "size": 0,
        "source": "write", "created_at": 0, "updated_at": 0, "pinned_at": 0, "title": "",
    }
    profile = SimpleNamespace(name="CowAgent", workspace=str(ios_home / "cow"))

    item = _payload(row, profile, "default")

    assert item["exists"]
    assert item["preview_url"] and NEW in item["raw_url"]
    assert item["rel_path"] == os.path.join("websites", "report.html")


def test_nothing_changes_outside_an_app_container(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    moved_paths._current_container.cache_clear()
    try:
        old = str(_container(tmp_path, OLD) / "Library" / "x.html")
        assert rebase_moved_path(old) == old
    finally:
        moved_paths._current_container.cache_clear()
