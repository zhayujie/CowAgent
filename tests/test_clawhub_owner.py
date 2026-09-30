"""ClawHub slugs are unique per publisher, so an install can name the owner."""

import io
import zipfile

import pytest
import requests

import cli.commands.skill as skill_cmd


class _Resp:
    def __init__(self, status=200, json_data=None, content=b"", content_type="application/json"):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


def _zip(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", f"---\nname: {name}\ndescription: d\n---\n")
    return buf.getvalue()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    live = tmp_path / "skills"
    live.mkdir()
    monkeypatch.setattr(skill_cmd, "get_skills_dir", lambda agent_id=None: str(live))
    calls = {"post": [], "get": []}
    state = {"has_mirror": True, "ambiguous": True}

    def fake_post(url, json=None, timeout=None):
        calls["post"].append((url, json))
        if json and json.get("mirror"):
            return _Resp(content=_zip("gog"), content_type="application/zip")
        return _Resp(json_data={
            "source_type": "registry",
            "source_provider": "clawhub",
            "download_url": "https://registry.example/api/v1/download?slug=gog",
            "has_mirror": state["has_mirror"],
        })

    def fake_get(url, timeout=None, allow_redirects=None):
        calls["get"].append(url)
        if state["ambiguous"] and "ownerHandle=" not in url:
            return _Resp(status=409, content_type="text/plain")
        return _Resp(content=_zip("gog"), content_type="application/zip")

    monkeypatch.setattr(skill_cmd.requests, "post", fake_post)
    monkeypatch.setattr(skill_cmd.requests, "get", fake_get)
    return live, calls, state


@pytest.mark.parametrize("ref,expected", [
    ("gog", (None, "gog")),
    ("steipete/gog", ("steipete", "gog")),
    ("@steipete/gog", ("steipete", "gog")),
    ("https://clawhub.ai/steipete/skills/gog", ("steipete", "gog")),
    ("https://clawhub.ai/@steipete/skills/gog/?tab=files", ("steipete", "gog")),
])
def test_parse_clawhub_ref(ref, expected):
    assert skill_cmd.parse_clawhub_ref(ref) == expected


@pytest.mark.parametrize("ref", ["", "a/b/c", "bad owner/gog", "steipete/"])
def test_parse_clawhub_ref_rejects_bad_input(ref):
    with pytest.raises(skill_cmd.SkillInstallError):
        skill_cmd.parse_clawhub_ref(ref)


@pytest.mark.parametrize("spec", [
    "clawhub:steipete/gog",
    "https://clawhub.ai/steipete/skills/gog",
])
def test_owner_is_passed_to_the_registry_download(hub, spec):
    live, calls, _ = hub
    result = skill_cmd.install_skill(spec)

    assert result.error is None, result.error
    assert result.installed == ["gog"]
    assert calls["post"][0][1] == {"provider": "clawhub", "owner": "steipete"}
    assert calls["get"] == ["https://registry.example/api/v1/download?slug=gog&ownerHandle=steipete"]
    assert (live / "gog" / "SKILL.md").exists()


def test_ambiguous_slug_asks_for_the_owner_instead_of_using_the_mirror(hub):
    live, calls, _ = hub
    result = skill_cmd.install_skill("clawhub:gog")

    assert result.error and "clawhub:<owner>/gog" in result.error
    assert not any(body and body.get("mirror") for _, body in calls["post"])
    assert not (live / "gog").exists()


def test_owner_request_never_falls_back_to_the_slug_only_mirror(hub, monkeypatch):
    _, calls, _ = hub

    def failing_get(url, timeout=None, allow_redirects=None):
        calls["get"].append(url)
        raise requests.ConnectionError("unreachable")

    monkeypatch.setattr(skill_cmd.requests, "get", failing_get)
    result = skill_cmd.install_skill("clawhub:steipete/gog")

    assert result.error and "Failed to download from clawhub" in result.error
    assert not any(body and body.get("mirror") for _, body in calls["post"])
