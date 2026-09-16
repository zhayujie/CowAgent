# encoding:utf-8
"""Guard the console's asset wiring.

The frontend is plain classic scripts with no bundler, so nothing fails at
build time: a script that is on disk but missing from the page just silently
stops existing, and one listed in the wrong place breaks at load. These are
the invariants the split relies on.
"""

import os
import re

from channel.web import template

WEB = os.path.join(os.path.dirname(__file__), "..", "channel", "web")
STATIC = os.path.join(WEB, "static")


def _page():
    return template.render("chat.html")


def _scripts(page):
    # The served page stamps each asset with its mtime, so the path is followed
    # by a ?v= query rather than the closing quote.
    return re.findall(r'<script defer src="assets/(js/[^"?]+)(?:\?[^"]*)?"', page)


def test_every_console_script_is_listed_exactly_once_and_exists():
    scripts = _scripts(_page())

    duplicated = sorted({s for s in scripts if scripts.count(s) > 1})
    assert not duplicated, duplicated

    absent = [s for s in scripts if not os.path.exists(os.path.join(STATIC, s))]
    assert not absent, absent

    on_disk = set()
    for root, _, files in os.walk(os.path.join(STATIC, "js")):
        for name in files:
            if name.endswith(".js"):
                rel = os.path.relpath(os.path.join(root, name), STATIC)
                on_disk.add(rel.replace(os.sep, "/"))

    # A file nobody loads is dead weight that still looks live in a search.
    assert not sorted(on_disk - set(scripts))


def test_every_stylesheet_is_listed_and_exists():
    sheets = re.findall(
        r'<link rel="stylesheet" href="assets/(css/[^"?]+)(?:\?[^"]*)?"', _page())
    absent = [s for s in sheets if not os.path.exists(os.path.join(STATIC, s))]
    assert not absent, absent
    assert sheets == sorted(set(sheets), key=sheets.index), "a sheet is linked twice"


def test_boot_runs_last_among_the_console_scripts_but_before_workspace():
    """boot.js is the only script with top-level work that calls into the rest,
    so everything it touches has to be declared by the time it runs.

    It stays ahead of workspace.js, which is where console.js used to sit:
    applyI18n() probes for relocalizeWorkspacePanel behind a typeof guard, and
    has always run before workspace.js defined that function.
    """
    scripts = _scripts(_page())

    boot = scripts.index("js/boot.js")
    split_out = [i for i, s in enumerate(scripts)
                 if s.startswith(("js/core/", "js/chat/", "js/views/"))]
    assert boot > max(split_out)
    assert boot < scripts.index("js/workspace.js")


def test_shared_layers_load_before_the_views_that_call_them():
    scripts = _scripts(_page())

    # core/auth.js is deliberately late; see the dedicated test below.
    last_core = max(i for i, s in enumerate(scripts)
                    if s.startswith("js/core/") and s != "js/core/auth.js")
    first_view = min(i for i, s in enumerate(scripts)
                     if s.startswith("js/views/") and s != "js/views/agents.js")
    assert last_core < first_view

    # views/doc-viewers.js calls createDocEditor() at top level.
    assert scripts.index("js/doc-editor.js") < scripts.index("js/views/doc-viewers.js")


def test_the_agent_roster_loads_before_the_chat_state_that_reads_it():
    """chat/state.js resolves sessionId while it runs, and the storage key it
    uses compares activeAgentId against defaultAgentId -- a `let` declared in
    views/agents.js.

    Load agents.js later and that binding is in its temporal dead zone, so
    chat/state.js throws partway through. Everything below the throw, which is
    sessionId and every composer element reference, is then permanently
    uninitialised: no history, no sending, no attachments. The comparison
    short-circuits on a falsy activeAgentId, so this only breaks for people who
    have selected an Agent -- it will not show up on a fresh profile.
    """
    scripts = _scripts(_page())
    assert scripts.index("js/views/agents.js") < scripts.index("js/chat/state.js")


def test_the_agent_id_fetch_wrapper_is_installed_inside_the_401_wrapper():
    """Both scripts wrap window.fetch. chat/state.js appends agent_id to the
    URL; core/auth.js inspects the URL to decide whether a 401 should bounce
    the user to the login screen. Installing the 401 wrapper second keeps it
    outermost, so it still sees the URL the caller asked for."""
    scripts = _scripts(_page())
    assert scripts.index("js/chat/state.js") < scripts.index("js/core/auth.js")


def test_the_handler_actually_serves_the_nested_script_paths():
    """The scripts used to be flat under js/; they are now in js/core/,
    js/chat/ and js/views/. Existing on disk is not the same as being
    reachable, so this goes through the handler that answers /assets/."""
    from unittest.mock import patch

    import channel.web.web_channel as web_channel

    sent = []
    with patch.object(web_channel.web, "header",
                      lambda name, value=None: sent.append((name.lower(), value))):
        handler = web_channel.AssetsHandler()
        for script in _scripts(_page()):
            del sent[:]
            body = handler.GET(script)
            assert body, script
            # application/octet-stream is what the handler falls back to, and a
            # browser will refuse to execute a script served as that.
            content_type = dict(sent).get("content-type", "")
            assert "javascript" in content_type, (script, content_type)


def test_the_old_console_flag_is_off_unless_asked_for():
    """`python app.py -old` serves the pre-split console for comparison. It
    reads the flag from the environment on every request, so the check has to
    fail closed - a stray value must not swap the console out from under a
    normal install."""
    from unittest.mock import patch

    import channel.web.web_channel as web_channel

    for value in (None, "", "0", "true", "yes"):
        env = {} if value is None else {"COW_LEGACY_CONSOLE": value}
        with patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("COW_LEGACY_CONSOLE", None)
            with patch.object(web_channel.web, "header", lambda *a, **k: None):
                html = web_channel.ChatHandler().GET()
        assert 'src="assets/js/core/i18n.js' in html, value
        assert "assets/legacy/" not in html, value


def test_asking_for_the_old_console_without_a_snapshot_says_how_to_get_one():
    """The snapshot is checked out of git rather than committed, so the common
    first run has nothing to serve. That has to explain itself instead of
    returning a blank page or a traceback."""
    from unittest.mock import patch

    import channel.web.web_channel as web_channel

    with patch("os.path.isfile", lambda p: False):
        page = web_channel._legacy_console_page("probe")

    assert "snapshot_legacy.py" in page
    assert "<!doctype html>" in page.lower()


def test_the_desktop_bundle_ships_everything_the_page_is_assembled_from():
    """The desktop client freezes the backend with PyInstaller, which ships
    only what the spec lists. chat.html is now a shell that template.py
    assembles from templates/ on every request, so a directory missing from
    the spec is not a missing file at build time -- it is a 500 from the
    console inside the shipped app, where nobody runs the test suite."""
    spec_path = os.path.join(WEB, "..", "..", "desktop", "build",
                             "cowagent-backend.spec")
    with open(spec_path, encoding="utf-8") as f:
        spec = f.read()

    # datas entries are written as rp('channel', 'web', <name>); whole
    # directories travel with everything under them.
    bundled = set(re.findall(r"rp\('channel', 'web', '([^']+)'\)", spec))

    page_source = os.path.join(WEB, "chat.html")
    with open(page_source, encoding="utf-8") as f:
        shell = f.read()

    needed = {ref.split("/")[0]
              for ref in re.findall(r"<!--#include\s+([^\s>]+?)\s*-->", shell)}
    needed.update(ref.split("/")[0]
                  for ref in re.findall(r'assets/((?:js|css)/[^"?]+)', shell))
    needed.add("chat.html")
    # assets/ is served out of static/, which is where the files actually live.
    needed = {"static" if n in ("js", "css") else n for n in needed}

    assert not needed - bundled, sorted(needed - bundled)


def test_an_assets_version_moves_with_the_file_and_not_with_the_clock():
    """The stamp used to be the wall clock, so every asset URL changed on every
    request and the browser re-fetched the whole console on every reload. The
    property that replaced it: a stamp holds still until its own file changes,
    which is also what lets the asset handler promise a versioned URL never
    goes stale."""
    first = _page()
    assert first == _page(), "rendering twice must not move any stamp"

    victim = _scripts(first)[0]
    path = os.path.join(STATIC, victim)
    before = os.stat(path)
    try:
        os.utime(path, (before.st_atime, before.st_mtime + 5))
        after = _page()
    finally:
        os.utime(path, (before.st_atime, before.st_mtime))

    moved = {ref for ref in re.findall(r'assets/(?:js|css)/[^"\']+', first)}
    moved ^= {ref for ref in re.findall(r'assets/(?:js|css)/[^"\']+', after)}
    # Exactly one URL differs: the touched file's, in its old and new form.
    assert len(moved) == 2, sorted(moved)
    assert all(ref.startswith("assets/" + victim + "?v=") for ref in moved), sorted(moved)


def test_only_stamped_assets_are_advertised_as_immutable():
    """The handler hands out a year-long, revalidation-free cache entry for
    anything is_versioned() accepts. That is only safe where render() puts an
    mtime in the URL -- a vendor bundle or the -old snapshot keeps its URL
    across edits, so promising the same would strand a browser on stale code
    with no way to ask."""
    for stamped in ("js/boot.js", "css/console.css", "js/views/chat.js"):
        assert template.is_versioned(stamped), stamped

    for unstamped in ("vendor/tailwind.js", "legacy/js/console.js",
                      "logos/openai.svg", "vendor/fonts/inter.woff2"):
        assert not template.is_versioned(unstamped), unstamped


def test_the_split_scripts_do_not_declare_the_same_global_twice():
    """Every top-level declaration lands on `window`, which is what the inline
    onclick handlers in generated markup reach. Two scripts declaring the same
    const is a SyntaxError that blanks the page."""
    pattern = re.compile(r"^(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)

    owners = {}
    clashes = []
    for script in _scripts(_page()):
        if not script.startswith(("js/core/", "js/chat/", "js/views/", "js/boot")):
            continue
        with open(os.path.join(STATIC, script), encoding="utf-8") as f:
            for name in pattern.findall(f.read()):
                first = owners.setdefault(name, script)
                if first != script:
                    clashes.append(f"{name}: {first} and {script}")

    assert not clashes, clashes
    # Guard the regex itself: if it stopped matching, the test above would pass
    # for the wrong reason.
    assert len(owners) > 600, len(owners)
