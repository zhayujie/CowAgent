"""Tests for the named-teams store (``agent.teams_store``).

The store persists the console's sidebar "Teams": saved rosters with a
leader, written through the web API and opened as group conversations.
These tests exercise the invariants directly against a tmp_path registry:
leader first, leader never dropped by a roster write, uniqueness, and the
full CRUD round trip.
"""

import pytest

from agent import teams_store


def test_create_requires_name_and_leader(tmp_path):
    import pytest as _pytest
    with _pytest.raises(teams_store.TeamsStoreError):
        teams_store.create_team("", "orchestrator", [], base=tmp_path)
    with _pytest.raises(teams_store.TeamsStoreError):
        teams_store.create_team("Team", "", [], base=tmp_path)


def test_create_normalizes_leader_first_and_dedupes(tmp_path):
    team = teams_store.create_team(
        "Productivity", "worker-b", ["orchestrator", "worker-b", ""],
        base=tmp_path)
    assert team["members"] == ["worker-b", "orchestrator"]
    assert team["leader"] == "worker-b"
    assert team["id"].startswith("t_")


def test_round_trip_list_get_update_delete(tmp_path):
    created = teams_store.create_team(
        "Ref check", "lead", ["a", "b"], base=tmp_path)

    teams = teams_store.list_teams(base=tmp_path)
    assert [t["id"] for t in teams] == [created["id"]]

    fetched = teams_store.get_team(created["id"], base=tmp_path)
    assert fetched["name"] == "Ref check"

    # A roster write that omits the leader keeps them (never dropped), and
    # an explicit leader moves to the front.
    updated = teams_store.update_team(
        created["id"], members=["c", "b"], base=tmp_path)
    assert updated["members"][0] == "lead"
    assert "c" in updated["members"] and "b" in updated["members"]

    renamed = teams_store.update_team(
        created["id"], name="Ref check 2", leader="b", base=tmp_path)
    assert renamed["name"] == "Ref check 2"
    assert renamed["leader"] == "b"
    assert renamed["members"][0] == "b"
    assert "lead" in renamed["members"]  # kept, demoted

    teams_store.delete_team(created["id"], base=tmp_path)
    assert teams_store.list_teams(base=tmp_path) == []
    import pytest as _pytest
    with _pytest.raises(KeyError):
        teams_store.get_team(created["id"], base=tmp_path)
    with _pytest.raises(KeyError):
        teams_store.delete_team(created["id"], base=tmp_path)


def test_unknown_update_raises_keyerror(tmp_path):
    import pytest as _pytest
    with _pytest.raises(KeyError):
        teams_store.update_team("t_missing", name="x", base=tmp_path)