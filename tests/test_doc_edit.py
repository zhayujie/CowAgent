"""Viewing and editing memory files and skill definitions in the web console."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.workspace.service import WorkspaceConflictError, WorkspaceService

SKILL_MD = """---
name: {name}
description: {desc}
---

# {name}

Instructions.
"""


def _write(path, text):
    """Write LF-only bytes; Path.write_text would translate to CRLF on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _memory(root):
    from agent.memory.service import MemoryService

    return MemoryService(str(root))


def _skill_dir(root, name, desc="does a thing"):
    _write(root / name / "SKILL.md", SKILL_MD.format(name=name, desc=desc))
    return root / name / "SKILL.md"


def _skills(builtin, custom):
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService

    builtin.mkdir(parents=True, exist_ok=True)
    custom.mkdir(parents=True, exist_ok=True)
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom)))


# ----------------------------------------------------------------------
# Memory: the relative path an editor needs
# ----------------------------------------------------------------------
def test_memory_content_reports_the_path_under_the_workspace(tmp_path):
    _write(tmp_path / "MEMORY.md", "# global\n")
    _write(tmp_path / "memory" / "2026-08-26.md", "# daily\n")
    svc = _memory(tmp_path)

    assert svc.get_content("MEMORY.md")["rel_path"] == "MEMORY.md"
    assert svc.get_content("2026-08-26.md")["rel_path"] == "memory/2026-08-26.md"


def test_memory_content_reports_the_path_of_a_dream_and_an_evolution_file(tmp_path):
    _write(tmp_path / "memory" / "dreams" / "2026-08-26.md", "# dreamt\n")
    _write(tmp_path / "memory" / "evolution" / "2026-08-26.md", "# learned\n")
    svc = _memory(tmp_path)

    assert svc.get_content("2026-08-26.md", category="dream")["rel_path"] \
        == "memory/dreams/2026-08-26.md"
    assert svc.get_content("2026-08-26.md", category="evolution")["rel_path"] \
        == "memory/evolution/2026-08-26.md"


def test_memory_rel_path_is_what_the_workspace_editor_can_open(tmp_path):
    """The console hands this path straight to the workspace read/write API, so
    the two views of the same file have to agree."""
    _write(tmp_path / "memory" / "dreams" / "2026-08-26.md", "# dreamt\n")

    loaded = _memory(tmp_path).get_content("2026-08-26.md", category="dream")
    ws = WorkspaceService(str(tmp_path))

    assert ws.read_text(loaded["rel_path"])["content"] == loaded["content"]
    ws.write_text(loaded["rel_path"], "# edited\n")
    assert _memory(tmp_path).get_content("2026-08-26.md", category="dream")["content"] \
        == "# edited\n"


# ----------------------------------------------------------------------
# Skills: read
# ----------------------------------------------------------------------
def test_read_content_returns_a_workspace_skill_as_editable(tmp_path):
    _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    result = svc.read_content("note-taker")

    assert result["source"] == "custom"
    assert result["editable"] is True
    assert result["ships_with_install"] is False
    assert result["filename"] == "SKILL.md"
    assert "# note-taker" in result["content"]
    assert result["mtime"] > 0


def test_read_content_marks_a_builtin_skill_read_only(tmp_path):
    """Its file ships with the installation, so an upgrade would drop the edit."""
    _skill_dir(tmp_path / "builtin", "image-maker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    result = svc.read_content("image-maker")

    assert result["source"] == "builtin"
    assert result["editable"] is False
    assert result["ships_with_install"] is True
    # Still readable: the point is to be able to look at what a skill tells the
    # agent to do, whether or not it can be changed here.
    assert "# image-maker" in result["content"]


def test_read_content_rejects_an_unknown_skill(tmp_path):
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(FileNotFoundError):
        svc.read_content("no-such-skill")


def test_read_content_requires_a_name(tmp_path):
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(ValueError):
        svc.read_content("   ")


# ----------------------------------------------------------------------
# Skills: write
# ----------------------------------------------------------------------
def test_write_content_saves_a_workspace_skill(tmp_path):
    target = _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")
    loaded = svc.read_content("note-taker")

    result = svc.write_content(
        "note-taker",
        loaded["content"] + "\nOne more rule.\n",
        expected_mtime=loaded["mtime"],
    )

    assert target.read_text(encoding="utf-8").endswith("One more rule.\n")
    assert result["size"] == target.stat().st_size


def test_write_content_refuses_a_builtin_skill(tmp_path):
    target = _skill_dir(tmp_path / "builtin", "image-maker")
    original = target.read_bytes()
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(ValueError):
        svc.write_content("image-maker", "rewritten\n")
    assert target.read_bytes() == original


def test_write_content_reports_a_mid_edit_rewrite(tmp_path):
    """The agent can rewrite a skill while it is open in the editor."""
    import os

    target = _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")
    stale = svc.read_content("note-taker")["mtime"]
    os.utime(target, (stale + 60, stale + 60))

    with pytest.raises(WorkspaceConflictError):
        svc.write_content("note-taker", "mine\n", expected_mtime=stale)
    assert "# note-taker" in target.read_text(encoding="utf-8")

    # Without a baseline the save is a deliberate overwrite and goes through.
    svc.write_content("note-taker", "mine\n")
    assert target.read_text(encoding="utf-8") == "mine\n"


def test_write_content_cannot_escape_the_skills_directory(tmp_path):
    outside = _write(tmp_path / "outside.md", "secret\n")
    _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    # A name is only ever resolved through the loader's index, so one that was
    # never discovered has no file to point at.
    for name in ("../outside.md", "note-taker/../../outside.md", str(outside)):
        with pytest.raises((FileNotFoundError, ValueError)):
            svc.write_content(name, "tampered\n")
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_a_workspace_copy_of_a_builtin_skill_is_still_read_only(tmp_path):
    """Startup deletes and re-copies every builtin skill directory into the
    workspace (`_sync_builtin_skills` in app.py). The copy the loader resolves is
    therefore a `custom` one that the next restart replaces regardless, so
    `source` alone is the wrong thing to gate the editor on: an edit accepted
    here would vanish with nothing to say so."""
    _skill_dir(tmp_path / "builtin", "helper", desc="the shipped one")
    custom = _skill_dir(tmp_path / "custom", "helper", desc="the local one")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    loaded = svc.read_content("helper")
    assert loaded["source"] == "custom"
    assert loaded["editable"] is False
    # `source` says `custom` here, so it cannot be what the console explains the
    # refusal with - hence the separate flag.
    assert loaded["ships_with_install"] is True

    with pytest.raises(ValueError):
        svc.write_content("helper", SKILL_MD.format(name="helper", desc="edited"))
    assert "the local one" in custom.read_text(encoding="utf-8")


def test_write_content_refreshes_what_the_skill_list_shows(tmp_path):
    """Name and description come from the frontmatter the editor just changed."""
    _skill_dir(tmp_path / "custom", "note-taker", desc="old summary")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    svc.write_content("note-taker", SKILL_MD.format(name="note-taker", desc="new summary"))

    listed = {s["name"]: s for s in svc.query()}
    assert listed["note-taker"]["description"] == "new summary"


# ----------------------------------------------------------------------
# HTTP handlers
# ----------------------------------------------------------------------
def _get(handler_cls, params):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "input", return_value=web_channel.web.storage(**params)):
        return json.loads(handler_cls().GET())


def _post(handler_cls, body):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        return json.loads(handler_cls().POST())


def test_skill_content_handler_serves_and_saves(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    target = _skill_dir(tmp_path / "skills", "console-editable")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        loaded = _get(SkillContentHandler, {"name": "console-editable"})
        assert loaded["status"] == "success"
        assert loaded["editable"] is True

        saved = _post(SkillContentHandler, {
            "name": "console-editable",
            "content": "# rewritten\n",
            "expected_mtime": loaded["mtime"],
        })

    assert saved["status"] == "success"
    assert target.read_text(encoding="utf-8") == "# rewritten\n"


def test_skill_content_handler_reports_a_conflict_code(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    target = _skill_dir(tmp_path / "skills", "console-editable")
    original = target.read_text(encoding="utf-8")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _post(SkillContentHandler, {
            "name": "console-editable",
            "content": "mine\n",
            "expected_mtime": target.stat().st_mtime - 60,
        })

    assert response["code"] == "conflict"
    assert target.read_text(encoding="utf-8") == original


def test_skill_content_handler_requires_a_name_and_string_content(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        assert _get(SkillContentHandler, {"name": ""})["status"] == "error"
        assert _post(SkillContentHandler, {"name": "x", "content": None})["status"] == "error"


def test_memory_content_handler_includes_the_editable_path(tmp_path):
    from channel.web.web_channel import MemoryContentHandler

    _write(tmp_path / "MEMORY.md", "# global\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _get(MemoryContentHandler, {"filename": "MEMORY.md", "category": "memory"})

    assert response["status"] == "success"
    assert response["rel_path"] == "MEMORY.md"


# ----------------------------------------------------------------------
# Frontend contract
# ----------------------------------------------------------------------
def _read(rel):
    return (Path(__file__).parents[1] / rel).read_text(encoding="utf-8")


def _web(rel):
    return _read(f"channel/web/{rel}")


def test_document_editor_is_loaded_before_its_users():
    """views/doc-viewers.js builds both editors at load time, so the factory
    has to exist by then; `defer` keeps the scripts in document order."""
    html = _web("chat.html")

    assert (html.index("assets/js/doc-editor.js")
            < html.index("assets/js/views/doc-viewers.js"))
    # A cached copy of the old page would ask for a script that has since been
    # renamed, so every first-party asset has to carry a version query. The
    # stamp is the asset's own mtime, and render() leaves an asset it cannot
    # stat unstamped -- so this also fails on a reference to a file that is no
    # longer there.
    from channel.web import template
    rendered = template.render("chat.html")
    unstamped = [ref for ref in re.findall(r'assets/(?:js|css)/[^"\']+', rendered)
                 if not re.search(r"\?v=[0-9a-f]+$", ref)]
    assert not unstamped, unstamped


def test_document_editor_contract():
    editor = _web("static/js/doc-editor.js")

    assert "function createDocEditor(" in editor
    # A text area normalizes CRLF to LF in its value, so the dirty baseline has
    # to come from the mounted element rather than the response text - otherwise
    # a CRLF document looks edited the moment it opens.
    assert "baseline = mount(body, data.content).value;" in editor
    # The guard clears the editing flag before retrying, so discarding has to
    # retry through exit(); retrying through cancel() would hit its own
    # `if (!editing) return` and leave the text area on screen.
    assert "if (!guard(exit)) return;" in editor
    # An untouched document must not be rewritten, and Ctrl+S must not be able
    # to race a second write against the first one's mtime.
    assert "if (saving) return;" in editor
    assert "if (!force && !isDirty())" in editor
    assert "data.code === 'conflict'" in editor
    # Whatever was read last is what leaving the editor redraws, or a save shows
    # the copy from before the agent's rewrite.
    assert "target.content = data.content;" in editor


def test_memory_and_skill_editor_wiring():
    # The page is assembled from templates/, so assert against what is served.
    from channel.web import template
    html = template.render("chat.html")
    from conftest import console_js
    console = console_js()
    css = _web("static/css/workspace.css")

    for ident in ("memory-btn-edit", "memory-btn-save", "memory-btn-cancel",
                  "skills-panel-viewer", "skill-viewer-content", "skill-viewer-title",
                  "skill-viewer-readonly", "skill-btn-edit", "skill-btn-save",
                  "skill-btn-cancel"):
        assert f'id="{ident}"' in html, ident
    assert 'onclick="memoryEditor.start()"' in html
    assert 'onclick="skillEditor.start()"' in html
    assert 'onclick="closeSkillViewer()"' in html

    assert "const memoryEditor = createDocEditor({" in console
    assert "const skillEditor = createDocEditor({" in console
    assert "textarea.doc-editor" in css

    # Memory files stay in the agent's state root. Passing the chat session
    # would resolve the same relative path inside whatever project that session
    # has open, and edit or create the wrong file.
    for fn in ("docReadFile", "docWriteFile"):
        body = re.search(rf"async function {fn}\(.*?\n\}}", console, re.S).group(0)
        assert "session" not in body, fn

    # Skills are addressed by name: which file a name resolves to is the
    # loader's business, and a builtin one sits outside the workspace.
    assert "/api/skills/content?name=" in console
    assert "fetch('/api/skills/content'" in console

    # The reason shown for a read-only skill comes from the server's flag. The
    # workspace copy of a builtin reads back as `custom`, so keying off `source`
    # would explain those - the common case - as an unsupported file type.
    reason = re.search(r"function skillReadonlyReason\(.*?\n\}", console, re.S).group(0)
    assert "data.ships_with_install" in reason
    assert "data.source" not in reason

    # Leaving the page, going back to the list or closing the tab all discard an
    # open editor, so each has to ask first.
    assert "if (!docGuardUnsaved(() => navigateTo(viewId))) return;" in console
    assert "if (!memoryEditor.guard(closeMemoryViewer)) return;" in console
    assert "if (!skillEditor.guard(closeSkillViewer)) return;" in console
    assert "if (!memoryEditor.isDirty() && !skillEditor.isDirty()) return;" in console

    # Every string these views show must exist in all three locales.
    for key in ("skill_back", "skill_open_hint", "skill_load_failed",
                "skill_builtin_readonly"):
        assert console.count(f"{key}:") == 3, key


# ----------------------------------------------------------------------
# Desktop client
# ----------------------------------------------------------------------
def _desktop(rel):
    return _read(f"desktop/src/renderer/src/{rel}")


def test_desktop_doc_editor_shares_one_implementation():
    """Memory and skills differ only in how a document is addressed, so the
    editing rules live in one factory rather than a copy per page."""
    store = _desktop("store/docEditorStore.ts")

    # The same safeguards the workspace panel and the web console carry.
    assert "if (res.code === 'conflict') {" in store
    assert "if (!force && !edit.dirty) {" in store
    assert "if (!edit || edit.saving) return" in store
    # A text area reports CRLF as LF, so the baseline has to be normalized or
    # every CRLF file looks edited the moment it opens.
    assert r"res.content.replace(/\r\n/g, '\n')" in store
    # A response for a document the user has already left must not overwrite
    # what is on screen.
    assert "if (mine !== seq) return" in store

    # Built at module scope: an unsaved edit has to outlive its page being
    # unmounted by a route change, which is also what lets the guard find it.
    for rel in ("pages/MemoryPage.tsx", "pages/SkillsPage.tsx"):
        src = _desktop(rel)
        assert re.search(r"^const \w+Editor = createDocEditorStore", src, re.M), rel


def test_desktop_memory_editing_stays_in_the_state_root():
    """Memory files are anchored to the agent's state root. Passing a session
    would resolve the same relative path inside whatever project that session has
    open, and edit or create the wrong file."""
    page = _desktop("pages/MemoryPage.tsx")
    client = _desktop("api/client.ts")

    factory = re.search(r"createDocEditorStore<MemoryRef.*?\n\}\)", page, re.S).group(0)
    assert "workspaceRead(doc.relPath)" in factory
    assert "path: doc.relPath" in factory
    assert "session" not in factory

    # The path has to come from the backend: the list only knows a file's name
    # and category, while the read and write endpoints take a path.
    assert "async getMemoryDoc(" in client
    assert "meta.rel_path" in page


def test_desktop_skill_editing_is_addressed_by_name():
    """Which file a skill name resolves to is the loader's business, and a
    builtin skill's file sits outside the workspace."""
    page = _desktop("pages/SkillsPage.tsx")
    client = _desktop("api/client.ts")

    assert "/api/skills/content?name=" in client
    assert "this.request('/api/skills/content'" in client
    assert "expected_mtime: args.expectedMtime ?? null," in client

    # The reason shown for a read-only skill comes from the server's flag: the
    # workspace copy of a builtin reads back as `custom`, so keying off `source`
    # would explain those - the common case - as an unsupported file type.
    factory = re.search(r"createDocEditorStore<SkillRef.*?\n\}\)", page, re.S).group(0)
    assert "data.ships_with_install" in factory
    assert "data.source" not in factory

    # Returning to the list has to re-read it: a saved edit can change the name
    # and description the cards show, which live in the file's frontmatter.
    assert "void loadData()" in page


def test_desktop_doc_editors_are_guarded_on_the_way_out():
    """Leaving the page unmounts the text area, so every exit has to ask first -
    and ask *before* it commits, or declining cannot call it off."""
    assert "if (!(await guardDocEditors())) return" in _desktop("layout/NavRail.tsx")
    assert "if (!(await guardDocEditors())) return" in _desktop("App.tsx")

    # Back to the list, and switching the memory tab, both drop the editor too.
    assert "memoryEditor.getState().close()" in _desktop("pages/MemoryPage.tsx")
    assert "if (!(await memoryEditor.getState().guard())) return" in _desktop("pages/MemoryPage.tsx")
    assert "skillEditor.getState().close()" in _desktop("pages/SkillsPage.tsx")


def test_desktop_doc_editor_seeds_declaratively():
    """An imperative `el.value =` in a mount-only effect is not reliable under
    StrictMode's double invoke, and writing '' for a missing text area would
    empty the file."""
    editor = _desktop("components/DocEditor.tsx")

    assert "defaultValue={edit.loaded}" in editor
    assert "autoFocus" in editor
    assert "stashText(el.value)" in editor
    # Saving falls back to nothing when the text area is missing, rather than to
    # '' - which would write an empty file over the user's content.
    assert "if (el) void save(el.value)" in editor
    assert "save(ref.current?.value ?? '')" not in editor

    # Every string these pages show must exist in both locales.
    i18n = _desktop("i18n.ts")
    for key in ("doc_edit", "doc_edit_save", "skill_back", "skill_open_hint",
                "skill_builtin_readonly"):
        assert i18n.count(f"{key}:") == 2, key
