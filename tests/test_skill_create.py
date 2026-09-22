"""Creating a skill from the console: the form, and folder / archive uploads."""

import io
import json
import os
import tarfile
import zipfile
from unittest.mock import patch

import pytest


SKILL_MD = "---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\nInstructions.\n"


def _service(tmp_path):
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService

    builtin = tmp_path / "builtin"
    custom = tmp_path / "workspace" / "skills"
    builtin.mkdir(parents=True, exist_ok=True)
    custom.mkdir(parents=True, exist_ok=True)
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom)))


def _custom_dir(service):
    from pathlib import Path

    return Path(service.manager.custom_dir)


def _zip_bytes(entries):
    """A zip of ``{path: bytes}``, as a browser would upload one."""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return payload.getvalue()


def _targz_bytes(entries):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tf:
        for path, content in entries.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return payload.getvalue()


# ----------------------------------------------------------------------
# The form
# ----------------------------------------------------------------------
def test_create_writes_a_skill_the_loader_then_lists(tmp_path):
    service = _service(tmp_path)

    result = service.create({
        "name": "Weather API",
        "description": "Look up the weather. Use when asked about forecasts.",
        "body": "## Usage\n\nRun the script.",
        "files": [{"path": "scripts/fetch.sh", "content": b"#!/bin/sh\necho hi\n"}],
    })

    assert result["name"] == "weather-api"
    assert result["files"] == ["scripts/fetch.sh"]

    skill_dir = _custom_dir(service) / "weather-api"
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == (
        "---\n"
        "name: weather-api\n"
        "description: Look up the weather. Use when asked about forecasts.\n"
        "---\n"
        "\n"
        "## Usage\n\nRun the script.\n"
    )
    assert (skill_dir / "scripts" / "fetch.sh").read_bytes() == b"#!/bin/sh\necho hi\n"

    listed = {s["name"]: s for s in service.query()}
    assert listed["weather-api"]["enabled"] is True
    # The title as typed survives the reduction to a hyphen-case name.
    assert listed["weather-api"]["display_name"] == "Weather API"


def test_create_keeps_a_description_that_would_break_plain_yaml(tmp_path):
    """A description is prose: "Use when: ..." is not a mapping, and a quoted
    scalar is what keeps the loader reading it back as one string."""
    service = _service(tmp_path)

    service.create({"name": "parser", "description": 'Use when: a "quoted" case'})

    entry = service.manager.get_skill("parser")
    assert entry.skill.description == 'Use when: a "quoted" case'


def test_create_needs_a_description_the_loader_would_keep(tmp_path):
    """The loader drops a skill whose frontmatter has no description, so one
    created without it would vanish from the list it was created in."""
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="description is required"):
        service.create({"name": "nameless", "description": "  "})
    assert not (_custom_dir(service) / "nameless").exists()


def test_create_refuses_a_title_with_no_name_in_it(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="latin letters or digits"):
        service.create({"name": "翻译助手", "description": "translate things"})


def test_create_refuses_a_name_already_taken(tmp_path):
    service = _service(tmp_path)
    service.create({"name": "twice", "description": "first"})

    with pytest.raises(ValueError, match="already exists"):
        service.create({"name": "twice", "description": "second"})
    # The first skill is untouched by the refused second attempt.
    assert "first" in (_custom_dir(service) / "twice" / "SKILL.md").read_text(encoding="utf-8")


def test_create_refuses_the_name_of_a_skill_that_ships_with_the_install(tmp_path):
    """Startup copies every builtin skill over the workspace copy of the same
    name, so a skill created under one would be replaced at the next restart."""
    service = _service(tmp_path)
    builtin = tmp_path / "builtin" / "skill-creator"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(SKILL_MD.format(name="skill-creator", desc="ships"),
                                      encoding="utf-8")

    with pytest.raises(ValueError, match="built-in skill"):
        service.create({"name": "skill-creator", "description": "mine"})


def test_create_leaves_nothing_behind_when_a_bundled_file_is_refused(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="path traversal"):
        service.create({
            "name": "escapee",
            "description": "tries to write outside its own directory",
            "files": [{"path": "../../evil.py", "content": b"pwned"}],
        })

    assert not (_custom_dir(service) / "escapee").exists()
    assert not (_custom_dir(service) / "escapee.tmp").exists()
    assert not (tmp_path / "evil.py").exists()


# ----------------------------------------------------------------------
# Uploads: a folder, or an archive
# ----------------------------------------------------------------------
def test_upload_installs_an_archive_holding_one_skill(tmp_path):
    service = _service(tmp_path)
    content = _zip_bytes({
        "pdf-editor/SKILL.md": SKILL_MD.format(name="pdf-editor", desc="edits PDFs"),
        "pdf-editor/scripts/rotate.py": "print('rotate')\n",
    })

    result = service.install_upload({"archive": {"filename": "pdf-editor.zip", "content": content}})

    assert result == {"installed": ["pdf-editor"], "replaced": [], "skipped": []}
    assert (_custom_dir(service) / "pdf-editor" / "scripts" / "rotate.py").is_file()
    assert service.manager.get_skill("pdf-editor") is not None


def test_upload_reads_a_tar_gz_as_well_as_a_zip(tmp_path):
    service = _service(tmp_path)
    content = _targz_bytes({
        "tarred/SKILL.md": SKILL_MD.format(name="tarred", desc="from a tarball").encode(),
    })

    result = service.install_upload({"archive": {"filename": "tarred.tar.gz", "content": content}})

    assert result["installed"] == ["tarred"]


def test_upload_installs_every_skill_in_a_collection_and_says_why_one_was_left(tmp_path):
    """One unusable skill in a batch must not cost the upload the rest of them."""
    service = _service(tmp_path)
    content = _zip_bytes({
        "pack/first/SKILL.md": SKILL_MD.format(name="first", desc="does a thing"),
        "pack/second/SKILL.md": SKILL_MD.format(name="second", desc="does another"),
        # A skill's own subdirectories are its resources, not skills.
        "pack/second/references/api.md": "# api\n",
        "pack/third/SKILL.md": "---\nname: third\n---\n\nNo description.\n",
    })

    result = service.install_upload({"archive": {"filename": "pack.zip", "content": content}})

    assert sorted(result["installed"]) == ["first", "second"]
    assert result["skipped"] == [{"name": "third", "reason": "SKILL.md carries no description"}]
    assert (_custom_dir(service) / "second" / "references" / "api.md").is_file()
    assert not (_custom_dir(service) / "third").exists()


def test_upload_installs_a_picked_folder_from_its_relative_paths(tmp_path):
    service = _service(tmp_path)

    result = service.install_upload({"files": [
        {"path": "my-skill/SKILL.md",
         "content": SKILL_MD.format(name="my-skill", desc="picked as a folder").encode()},
        {"path": "my-skill/assets/logo.svg", "content": b"<svg/>"},
    ]})

    assert result["installed"] == ["my-skill"]
    assert (_custom_dir(service) / "my-skill" / "assets" / "logo.svg").read_bytes() == b"<svg/>"


def test_upload_names_a_skill_after_the_archive_when_its_frontmatter_does_not(tmp_path):
    service = _service(tmp_path)
    content = _zip_bytes({"SKILL.md": "---\ndescription: unnamed but described\n---\n"})

    result = service.install_upload({"archive": {"filename": "Fallback Name.zip", "content": content}})

    assert result["installed"] == ["fallback-name"]


def test_upload_replaces_a_skill_of_the_same_name_and_reports_it(tmp_path):
    service = _service(tmp_path)
    service.create({"name": "updatable", "description": "the first version"})
    content = _zip_bytes({
        "updatable/SKILL.md": SKILL_MD.format(name="updatable", desc="the second version"),
    })

    result = service.install_upload({"archive": {"filename": "updatable.zip", "content": content}})

    assert result == {"installed": [], "replaced": ["updatable"], "skipped": []}
    assert service.manager.get_skill("updatable").skill.description == "the second version"


def test_upload_keeps_the_installed_skill_when_replacing_it_fails(tmp_path):
    """The skill being replaced may be one the user wrote, so a copy that fails
    halfway - a full disk, a locked file - must not take it with it."""
    service = _service(tmp_path)
    service.create({"name": "updatable", "description": "the first version"})
    content = _zip_bytes({
        "updatable/SKILL.md": SKILL_MD.format(name="updatable", desc="the second version"),
    })

    with patch("agent.skills.service.shutil.copytree", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            service.install_upload({
                "archive": {"filename": "updatable.zip", "content": content},
            })

    service.manager.refresh_skills()
    assert service.manager.get_skill("updatable").skill.description == "the first version"
    # And nothing half-copied left behind for the next install to trip over.
    assert [p.name for p in _custom_dir(service).iterdir() if p.is_dir()] == ["updatable"]


def test_a_skill_being_written_is_hidden_from_the_loader_until_it_is_whole(tmp_path):
    """A scan that lands mid-create must not read the staging directory as a
    skill: the loader skips a hidden directory, so the staging one is hidden."""
    service = _service(tmp_path)
    staged = []

    real_rename = os.rename

    def _watch(src, dst):
        staged.append(os.path.basename(src))
        return real_rename(src, dst)

    with patch("agent.skills.service.os.rename", side_effect=_watch):
        service.create({"name": "half-written", "description": "a skill mid-write"})

    assert staged == [".half-written.tmp"]


def test_upload_refuses_an_archive_that_writes_outside_the_skills_directory(tmp_path):
    service = _service(tmp_path)
    content = _zip_bytes({"../escaped/SKILL.md": SKILL_MD.format(name="escaped", desc="d")})

    with pytest.raises(ValueError, match="path traversal"):
        service.install_upload({"archive": {"filename": "evil.zip", "content": content}})

    assert not (tmp_path / "workspace" / "escaped").exists()


def test_upload_installs_a_zip_holding_a_symlink_without_the_link(tmp_path):
    """A repository zip does hold the odd symlink. ``zipfile`` cannot recreate
    one - it would write the target path as the file's contents - so the entry is
    dropped and the skill still installs."""
    service = _service(tmp_path)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("linked/SKILL.md", SKILL_MD.format(name="linked", desc="has a link"))
        link = zipfile.ZipInfo("linked/passwd")
        link.external_attr = (0o120777 << 16)
        zf.writestr(link, "/etc/passwd")

    result = service.install_upload({
        "archive": {"filename": "linked.zip", "content": payload.getvalue()},
    })

    assert result["installed"] == ["linked"]
    assert not (_custom_dir(service) / "linked" / "passwd").exists()


def test_upload_refuses_a_tar_that_carries_a_symlink(tmp_path):
    """Unlike a zip, a tar's links are recreated on extraction, which would make
    an install a write to wherever the link points."""
    service = _service(tmp_path)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tf:
        body = SKILL_MD.format(name="linked", desc="has a link").encode()
        info = tarfile.TarInfo("linked/SKILL.md")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
        link = tarfile.TarInfo("linked/passwd")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)

    with pytest.raises(ValueError, match="contains a link"):
        service.install_upload({
            "archive": {"filename": "linked.tar.gz", "content": payload.getvalue()},
        })


def test_upload_refuses_something_that_is_not_an_archive(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="Unsupported archive format"):
        service.install_upload({"archive": {"filename": "notes.txt", "content": b"just text"}})


def test_upload_says_when_the_upload_holds_no_skill(tmp_path):
    service = _service(tmp_path)
    content = _zip_bytes({"docs/readme.md": "# not a skill\n"})

    with pytest.raises(ValueError, match="no SKILL.md"):
        service.install_upload({"archive": {"filename": "docs.zip", "content": content}})


def test_upload_leaves_a_builtin_name_to_the_builtin(tmp_path):
    service = _service(tmp_path)
    builtin = tmp_path / "builtin" / "knowledge-wiki"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(SKILL_MD.format(name="knowledge-wiki", desc="ships"),
                                      encoding="utf-8")
    content = _zip_bytes({
        "knowledge-wiki/SKILL.md": SKILL_MD.format(name="knowledge-wiki", desc="mine"),
    })

    result = service.install_upload({"archive": {"filename": "wiki.zip", "content": content}})

    assert result["installed"] == []
    assert result["skipped"][0]["name"] == "knowledge-wiki"
    assert "built-in" in result["skipped"][0]["reason"]


# ----------------------------------------------------------------------
# The console's endpoints
# ----------------------------------------------------------------------
class UploadedFile:
    def __init__(self, filename, content):
        self.filename = filename
        self.value = content


def _post(handler_cls, params, service):
    module = handler_cls.__module__
    with patch(f"{module}._require_auth"), \
         patch(f"{module}.web.header"), \
         patch(f"{module}._raw_web_input", return_value=params), \
         patch(f"{module}._skill_service", return_value=service):
        return json.loads(handler_cls().POST())


def test_create_endpoint_writes_the_form_and_its_attachments(tmp_path):
    from channel.web.api.skills import SkillCreateHandler

    service = _service(tmp_path)
    response = _post(SkillCreateHandler, {
        "name": "Web Search",
        "description": "Search the web",
        "body": "## Usage\n",
        "files": [UploadedFile("scripts/search.sh", b"echo search")],
    }, service)

    assert response == {"status": "success", "name": "web-search", "files": ["scripts/search.sh"]}
    assert (_custom_dir(service) / "web-search" / "scripts" / "search.sh").is_file()


def test_create_endpoint_ignores_a_file_field_left_empty(tmp_path):
    """A form submitted with nothing attached still sends the file field, as a
    part with no name. There is nothing to write for it."""
    from channel.web.api.skills import SkillCreateHandler

    service = _service(tmp_path)
    response = _post(SkillCreateHandler, {
        "name": "plain",
        "description": "no attachments",
        "files": [UploadedFile("", b"")],
    }, service)

    assert response == {"status": "success", "name": "plain", "files": []}
    assert [p.name for p in (_custom_dir(service) / "plain").iterdir()] == ["SKILL.md"]


def test_create_endpoint_reports_a_refusal_as_a_message(tmp_path):
    from channel.web.api.skills import SkillCreateHandler

    response = _post(SkillCreateHandler, {"name": "x", "description": ""}, _service(tmp_path))

    assert response["status"] == "error"
    assert "description is required" in response["message"]


def test_upload_endpoint_installs_an_archive(tmp_path):
    from channel.web.api.skills import SkillUploadHandler

    service = _service(tmp_path)
    content = _zip_bytes({"zipped/SKILL.md": SKILL_MD.format(name="zipped", desc="from a zip")})
    response = _post(SkillUploadHandler, {"archive": UploadedFile("zipped.zip", content)}, service)

    assert response["status"] == "success"
    assert response["installed"] == ["zipped"]


def test_upload_endpoint_pairs_each_file_with_its_path(tmp_path):
    """A picked folder arrives as parallel ``files`` and ``relative_paths``
    fields, the pairing the chat upload uses; a mismatch would silently install
    the wrong tree."""
    from channel.web.api.skills import SkillUploadHandler

    service = _service(tmp_path)
    response = _post(SkillUploadHandler, {
        "files": [
            UploadedFile("SKILL.md", SKILL_MD.format(name="foldered", desc="picked").encode()),
            UploadedFile("run.sh", b"echo run"),
        ],
        "relative_paths": ["foldered/SKILL.md", "foldered/scripts/run.sh"],
    }, service)

    assert response["installed"] == ["foldered"]
    assert (_custom_dir(service) / "foldered" / "scripts" / "run.sh").is_file()


def test_upload_endpoint_refuses_a_path_for_every_file_but_one(tmp_path):
    from channel.web.api.skills import SkillUploadHandler

    response = _post(SkillUploadHandler, {
        "files": [UploadedFile("SKILL.md", b"---\n"), UploadedFile("run.sh", b"")],
        "relative_paths": ["only/SKILL.md"],
    }, _service(tmp_path))

    assert response["status"] == "error"
    assert "a path per file" in response["message"]


def test_upload_endpoint_refuses_an_oversized_body_before_reading_it(tmp_path):
    from agent.skills.service import SkillService
    from channel.web.api.skills import SkillUploadHandler

    with patch("channel.web.api.skills._require_auth"), \
         patch("channel.web.api.skills.web.header"), \
         patch("channel.web.api.skills.web.ctx") as ctx, \
         patch("channel.web.api.skills._raw_web_input") as read_body:
        ctx.env = {"CONTENT_LENGTH": str(SkillService.MAX_UPLOAD_TOTAL_SIZE + 1)}
        response = json.loads(SkillUploadHandler().POST())

    assert response == {"status": "error", "message": "upload too large"}
    read_body.assert_not_called()


def test_the_console_offers_both_ways_of_adding_a_skill():
    from channel.web.core import template
    from conftest import console_js

    # The page is assembled from templates/, so this asserts against what is served.
    html = template.render("chat.html")
    js = console_js()

    assert 'onclick="openSkillCreateDialog()"' in html
    assert 'id="skill-create-overlay"' in html
    for field in ("skill-create-name", "skill-create-desc", "skill-create-body",
                  "skill-create-files", "skill-upload-archive", "skill-upload-folder"):
        assert f'id="{field}"' in html, field
    # The folder picker needs the attribute, not just the input.
    assert 'id="skill-upload-folder" type="file" class="hidden" multiple webkitdirectory' in html

    assert "function openSkillCreateDialog(" in js
    assert "function switchSkillCreateMode(" in js
    assert "fetch('/api/skills/create'" in js or "postSkillCreate('/api/skills/create'" in js
    assert "postSkillCreate('/api/skills/upload'" in js
    # A picked folder is sent as parallel fields, the pairing the handler reads.
    assert "form.append('files', file);" in js
    assert "form.append('relative_paths', relPath);" in js


def test_the_name_preview_normalizes_the_way_the_server_does():
    """The hint under the name field promises the directory that will be
    created, so the two rules cannot drift apart."""
    from conftest import console_js

    js = console_js()
    slug = js[js.index("function skillNameSlug("):]
    slug = slug[:slug.index("\n}")]

    assert "[^a-z0-9]+" in slug and "'-'" in slug
    assert "slice(0, 64)" in slug


def test_both_upload_routes_are_wired_into_the_url_table():
    from channel.web import web_channel

    urls = web_channel.URLS
    assert urls[urls.index('/api/skills/create') + 1] == 'SkillCreateHandler'
    assert urls[urls.index('/api/skills/upload') + 1] == 'SkillUploadHandler'
