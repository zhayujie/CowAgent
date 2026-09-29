"""Console skill installs: stage for preview, then commit on confirm."""

import io
import json
import zipfile

import pytest

import cli.commands.skill as skill_cmd
from channel.web.api.skills import _market_spec


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    live = tmp_path / "live" / "skills"
    live.mkdir(parents=True)
    monkeypatch.setattr(skill_cmd, "get_skills_dir", lambda agent_id=None: str(live))
    return live


def _skill_md(name, desc="does things"):
    return f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\n".encode("utf-8")


def test_skill_md_upload_is_staged_not_installed(tmp_path, live_dir):
    stage = tmp_path / "stage"
    result = skill_cmd.stage_skill_upload([("SKILL.md", _skill_md("notes"))], str(stage))

    assert result.error is None
    assert not (live_dir / "notes").exists()
    items = skill_cmd.describe_staged(str(stage))
    assert [i["name"] for i in items] == ["notes"]
    assert items[0]["description"] == "does things"
    assert items[0]["source"] == "local"
    assert items[0]["exists"] is False
    assert "# notes" in items[0]["skill_md"]


def test_folder_upload_keeps_structure_and_uses_folder_name(tmp_path, live_dir):
    stage = tmp_path / "stage"
    files = [
        ("my-skill/SKILL.md", b"# no frontmatter\n"),
        ("my-skill/scripts/run.py", b"print(1)\n"),
        ("my-skill/.DS_Store", b"junk"),
    ]
    result = skill_cmd.stage_skill_upload(files, str(stage))

    assert result.error is None
    item = skill_cmd.describe_staged(str(stage))[0]
    assert item["name"] == "my-skill"
    assert item["files"] == ["SKILL.md", "scripts/run.py"]


def test_folder_upload_rejects_path_traversal(tmp_path, live_dir):
    stage = tmp_path / "stage"
    files = [("a/SKILL.md", _skill_md("a")), ("a/../../escape.txt", b"x")]
    result = skill_cmd.stage_skill_upload(files, str(stage))

    assert result.error and "Invalid file path" in result.error
    assert not (tmp_path / "escape.txt").exists()


def test_zip_upload_with_several_skills(tmp_path, live_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack/skills/one/SKILL.md", _skill_md("one"))
        zf.writestr("pack/skills/two/SKILL.md", _skill_md("two"))
    stage = tmp_path / "stage"
    result = skill_cmd.stage_skill_upload([("pack.zip", buf.getvalue())], str(stage))

    assert result.error is None
    assert [i["name"] for i in skill_cmd.describe_staged(str(stage))] == ["one", "two"]


def test_unsupported_single_file_is_refused(tmp_path, live_dir):
    result = skill_cmd.stage_skill_upload([("notes.txt", b"hi")], str(tmp_path / "stage"))
    assert result.error and "Unsupported file" in result.error


def test_commit_installs_only_selected_and_flags_existing(tmp_path, live_dir):
    stage = tmp_path / "stage"
    (live_dir / "one").mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skills/one/SKILL.md", _skill_md("one"))
        zf.writestr("skills/two/SKILL.md", _skill_md("two"))
    skill_cmd.stage_skill_upload([("pack.zip", buf.getvalue())], str(stage))

    flags = {i["name"]: i["exists"] for i in skill_cmd.describe_staged(str(stage))}
    assert flags == {"one": True, "two": False}

    assert skill_cmd.commit_staged(str(stage), []) == []
    assert not (live_dir / "two").exists()

    installed = skill_cmd.commit_staged(str(stage), ["two"])
    assert installed == ["two"]
    assert (live_dir / "two" / "SKILL.md").exists()
    config = json.loads((live_dir / "skills_config.json").read_text(encoding="utf-8"))
    assert config["two"]["source"] == "local"
    assert "one" not in config


def test_stage_skill_redirects_every_write_to_the_staging_dir(tmp_path, live_dir):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_bytes(_skill_md("local-one"))

    def fake_route(name, result, agent_id=None):
        skill_cmd._install_local(str(src), result, agent_id=agent_id)

    stage = tmp_path / "stage"
    original = skill_cmd._route_install
    skill_cmd._route_install = fake_route
    try:
        result = skill_cmd.stage_skill("anything", str(stage))
    finally:
        skill_cmd._route_install = original

    assert result.installed == ["local-one"]
    assert (stage / "local-one" / "SKILL.md").exists()
    assert not (live_dir / "local-one").exists()
    assert skill_cmd._staging_dir.get() is None


@pytest.mark.parametrize("source,value,expected", [
    ("hub", "pptx", "pptx"),
    ("clawhub", "weather", "clawhub:weather"),
    ("clawhub", "clawhub:weather", "clawhub:weather"),
    ("github", "larksuite/cli", "larksuite/cli"),
    ("github", "https://github.com/larksuite/cli/tree/main/skills/lark-im",
     "https://github.com/larksuite/cli/tree/main/skills/lark-im"),
])
def test_market_spec_maps_each_source(source, value, expected):
    assert _market_spec(source, value) == expected


@pytest.mark.parametrize("source,value", [
    ("hub", "owner/repo"),
    ("hub", "/etc"),
    ("github", "~/secrets"),
    ("github", "not a repo"),
    ("clawhub", "../x"),
    ("other", "pptx"),
    ("hub", ""),
])
def test_market_spec_rejects_bad_input(source, value):
    with pytest.raises(ValueError):
        _market_spec(source, value)


def test_staging_sweeps_expired_and_orphaned_previews(tmp_path, monkeypatch):
    import os
    import tempfile
    import time
    from channel.web.api.skills import _SkillStaging

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    store = _SkillStaging()
    old = time.time() - store.TTL_SECONDS - 60

    expired_token, expired_dir = store.create("")
    store._items[expired_token]["created"] = old
    orphan = tmp_path / f"{store.DIR_PREFIX}left-by-restart"
    orphan.mkdir()
    os.utime(orphan, (old, old))
    fresh_orphan = tmp_path / f"{store.DIR_PREFIX}another-process"
    fresh_orphan.mkdir()
    live_token, live_dir = store.create("")
    os.utime(live_dir, (old, old))

    assert store.get(expired_token) is None
    assert not os.path.exists(expired_dir)
    assert not orphan.exists()
    assert fresh_orphan.exists()
    assert store.get(live_token)["dir"] == live_dir
    assert os.path.exists(live_dir)


def _post_multipart(app, url, parts):
    boundary = "----skilltest"
    body = io.BytesIO()
    for field, filename, content in parts:
        disposition = f'form-data; name="{field}"'
        if filename:
            disposition += f'; filename="{filename}"'
        body.write(f"--{boundary}\r\nContent-Disposition: {disposition}\r\n\r\n".encode())
        body.write(content + b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    data = body.getvalue()
    environ = {
        "REQUEST_METHOD": "POST", "PATH_INFO": url, "QUERY_STRING": "",
        "SERVER_NAME": "localhost", "SERVER_PORT": "80", "HTTP_HOST": "localhost",
        "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(data),
        "CONTENT_TYPE": f"multipart/form-data; boundary={boundary}",
        "CONTENT_LENGTH": str(len(data)),
    }
    chunks = app.wsgifunc()(environ, lambda status, headers: None)
    return json.loads(b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks))


def test_folder_upload_endpoint_keeps_every_repeated_part(live_dir, monkeypatch):
    import web
    import channel.web.api.skills as skills_api

    monkeypatch.setattr(skills_api, "_require_auth", lambda: None)
    app = web.application(("/api/skills/upload", "SkillUploadHandler"), vars(skills_api))
    files = [("big-skill/SKILL.md", _skill_md("big-skill"))]
    files += [(f"big-skill/refs/{i}.md", b"x") for i in range(150)]
    parts = []
    for path, content in files:
        parts.append(("files", path.rsplit("/", 1)[-1], content))
        parts.append(("paths", None, path.encode()))

    res = _post_multipart(app, "/api/skills/upload", parts)

    assert res["status"] == "success", res
    assert [(s["name"], s["file_count"]) for s in res["skills"]] == [("big-skill", 151)]
    assert list(live_dir.iterdir()) == []
    skills_api._staging.discard(res["token"])
