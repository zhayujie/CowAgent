"""Creating a skill from the console's form.

Installing an existing skill from an upload is the add dialog's staged flow,
covered in test_skill_staging.py.
"""

import json
import os
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


def test_create_endpoint_bundles_a_picked_folder_at_the_paths_it_had(tmp_path):
    """A skill's resources come as a directory as often as they come as loose
    files, so the form's attachments travel the way an uploaded folder does:
    paired ``files`` and ``relative_paths``. Without the pairing every file
    would land flat beside SKILL.md, and a script's imports would break."""
    from channel.web.api.skills import SkillCreateHandler

    service = _service(tmp_path)
    response = _post(SkillCreateHandler, {
        "name": "Bundler",
        "description": "ships a folder of scripts",
        "files": [
            UploadedFile("run.py", b"import helpers\n"),
            UploadedFile("helpers.py", b"def go(): pass\n"),
            UploadedFile("api.md", b"# api\n"),
        ],
        "relative_paths": ["scripts/run.py", "scripts/lib/helpers.py", "references/api.md"],
    }, service)

    assert response["files"] == ["scripts/run.py", "scripts/lib/helpers.py", "references/api.md"]
    skill_dir = _custom_dir(service) / "bundler"
    assert (skill_dir / "scripts" / "lib" / "helpers.py").read_bytes() == b"def go(): pass\n"
    assert (skill_dir / "references" / "api.md").is_file()
    # The form writes SKILL.md itself, so an attachment cannot shadow it.
    assert "ships a folder of scripts" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")


def test_create_endpoint_cannot_bundle_a_file_outside_the_skill(tmp_path):
    """The relative paths come from a browser and are attacker-controlled just
    like the skill name."""
    from channel.web.api.skills import SkillCreateHandler

    service = _service(tmp_path)
    response = _post(SkillCreateHandler, {
        "name": "escapee",
        "description": "tries to write outside its own directory",
        "files": [UploadedFile("evil.py", b"pwned")],
        "relative_paths": ["../../evil.py"],
    }, service)

    assert response["status"] == "error"
    assert "path traversal" in response["message"]
    assert not (_custom_dir(service) / "escapee").exists()


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


def test_the_console_offers_the_create_form_beside_the_add_dialog():
    from channel.web.core import template
    from conftest import console_js

    # The page is assembled from templates/, so this asserts against what is served.
    html = template.render("chat.html")
    js = console_js()

    assert 'onclick="openSkillCreateDialog()"' in html
    assert 'id="skill-add-btn"' in html
    assert 'id="skill-create-overlay"' in html
    for field in ("skill-create-name", "skill-create-desc", "skill-create-body",
                  "skill-create-files", "skill-create-folder"):
        assert f'id="{field}"' in html, field
    # A folder picker needs the attribute, not just the input.
    assert 'id="skill-create-folder" type="file" class="hidden" multiple webkitdirectory' in html
    # Uploading an existing skill is the add dialog's, with a preview first; the
    # create dialog does not offer a second, unpreviewed way in.
    assert "data-skill-create-tab" not in html
    assert "switchSkillCreateMode" not in js

    assert "function openSkillCreateDialog(" in js
    assert "fetch('/api/skills/create'" in js
    # The form's attachments keep their paths, so a folder picked there installs
    # as the directory it was picked as.
    assert "form.append('relative_paths', skillAttachmentPath(file));" in js
    assert "return file.webkitRelativePath || file.name;" in js


def test_a_picked_folder_leaves_out_caches_and_hidden_entries():
    """A directory on disk carries more than what someone wrote, and the file
    tree in the skill viewer hides exactly these - so bundling them would add
    weight the console could not even show."""
    from conftest import console_js

    js = console_js()
    candidates = js[js.index("function skillUploadCandidates("):]
    candidates = candidates[:candidates.index("\n}")]

    assert "__pycache__" in candidates and "node_modules" in candidates
    assert "startsWith('.')" in candidates
    assert "skillUploadCandidates(picked)" in js


def test_both_kinds_of_attachment_pick_sit_behind_one_button():
    """A native file dialog browses for files or for a directory, never both, so
    the choice is made before it opens: one button, the two picks behind it, the
    way the composer's attach menu offers the same pair."""
    from pathlib import Path

    from channel.web.core import template
    from conftest import console_js

    html = template.render("chat.html")
    js = console_js()

    assert 'onclick="toggleSkillAttachMenu(event)"' in html
    # Borrows the composer menu's card, positioned by a class of its own.
    assert 'class="attach-menu skill-attach-menu hidden"' in html
    assert ".attach-menu.skill-attach-menu {" in (
        Path(__file__).parents[1] / "channel/web/static/css/workspace.css"
    ).read_text(encoding="utf-8")
    # A menu that only closes by picking something would sit over the fields.
    assert "function initSkillAttachMenu(" in js
    assert "hideSkillAttachMenu();" in js

    page = (Path(__file__).parents[1]
            / "desktop/src/renderer/src/pages/SkillsPage.tsx").read_text(encoding="utf-8")
    assert "setAttachOpen((v) => !v)" in page
    assert "!attachRef.current.contains(e.target as Node)" in page


def test_the_desktop_create_form_bundles_a_folder_the_same_way():
    """The desktop console posts to the same endpoint, so an attachment picked
    there has to carry its path too, or the same folder would install flat."""
    from pathlib import Path

    root = Path(__file__).parents[1] / "desktop/src/renderer/src"
    page = (root / "pages/SkillsPage.tsx").read_text(encoding="utf-8")
    client = (root / "api/client.ts").read_text(encoding="utf-8")

    assert "formData.append('relative_paths', file.webkitRelativePath || file.name)" in client
    # A folder picker needs the attribute React's typings do not carry.
    assert page.count("{...FOLDER_INPUT_PROPS}") == 1
    assert "function skillUploadCandidates(" in page
    assert "addAttachments(picked, true)" in page
    # Uploading an existing skill is SkillAddModal's staged flow alone.
    assert "uploadSkillArchive" not in client and "uploadSkillFolder" not in client


def test_the_name_preview_normalizes_the_way_the_server_does():
    """The hint under the name field promises the directory that will be
    created, so the two rules cannot drift apart."""
    from conftest import console_js

    js = console_js()
    slug = js[js.index("function skillNameSlug("):]
    slug = slug[:slug.index("\n}")]

    assert "[^a-z0-9]+" in slug and "'-'" in slug
    assert "slice(0, 64)" in slug


def test_create_and_upload_routes_are_wired_into_the_url_table():
    from channel.web import web_channel

    urls = web_channel.URLS
    assert urls[urls.index('/api/skills/create') + 1] == 'SkillCreateHandler'
    assert urls[urls.index('/api/skills/upload') + 1] == 'SkillUploadHandler'
