# encoding:utf-8
"""Guard the console's path routing.

The address bar is now part of the console's contract: a reload or a shared
link has to land on the view and tab it names. Nothing here fails at build
time, and the failure mode is quiet -- a renamed tab turns an old bookmark
into a dead route, and a tab switcher that stops reporting leaves the URL
pointing somewhere the user is not.

These tests pin the wiring: that the router's vocabulary matches the page's,
and that the backend serves what the router hands out. What the router *does*
once it runs -- which entries land on the history stack -- is checked by
``channel/web/tools/check-router.mjs``.
"""

import os
import re

from channel.web.core import template

WEB = os.path.join(os.path.dirname(__file__), "..", "channel", "web")
STATIC = os.path.join(WEB, "static")


def _js(rel_path):
    with open(os.path.join(STATIC, "js", rel_path), encoding="utf-8") as f:
        return f.read()


def _route_tabs():
    """The tab vocabulary the router accepts, read from its own source."""
    block = re.search(r"const ROUTE_TABS = \{(.*?)\n\};", _js("core/router.js"), re.S)
    assert block, "ROUTE_TABS is no longer where the tests can read it"
    return {view: re.findall(r"'([^']+)'", tabs)
            for view, tabs in re.findall(r"(\w+):\s*\[([^\]]+)\]", block.group(1))}


def _route_paths():
    """view id -> the path segment it is reached at, read from the router."""
    block = re.search(r"const ROUTE_PATHS = \{(.*?)\n\};", _js("core/router.js"), re.S)
    assert block, "ROUTE_PATHS is no longer where the tests can read it"
    return dict(re.findall(r"(\w+):\s*'([^']*)'", block.group(1)))


def _route_default_tabs():
    """view id -> the tab it opens on, which is left out of the path."""
    block = re.search(r"const ROUTE_DEFAULT_TABS = \{(.*?)\n\};",
                      _js("core/router.js"), re.S)
    assert block, "ROUTE_DEFAULT_TABS is no longer where the tests can read it"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


def _route_tab_aliases():
    """view id -> {tab element id: the segment it is routed under}."""
    block = re.search(r"const ROUTE_TAB_PATHS = \{(.*?)\n\};",
                      _js("core/router.js"), re.S)
    assert block, "ROUTE_TAB_PATHS is no longer where the tests can read it"
    return {view: dict(re.findall(r"(\w+):\s*'([^']+)'", pairs))
            for view, pairs in re.findall(r"(\w+):\s*\{([^}]*)\}", block.group(1))}


def test_the_routable_tabs_are_the_tabs_the_page_actually_has():
    """A route names a tab by the id its element carries. Rename the element
    and every link to that tab dies silently -- the router drops the unknown
    name and lands the user on the view's default tab instead."""
    routable = _route_tabs()
    assert routable, "no routable tabs parsed"

    page = template.render("chat.html")
    for view, tabs in routable.items():
        present = set(re.findall(r'id="%s-tab-([a-z]+)"' % view, page))
        assert present == set(tabs), (view, sorted(present), sorted(tabs))


def test_every_routable_tab_switch_reports_itself_to_the_router():
    """The switchers are reached from onclick handlers in the markup, not
    through the router, so each has to say where it went. One that stops
    reporting leaves the address bar naming the tab the user just left."""
    sources = {
        "config": "views/config.js",
        "memory": "views/memory.js",
        "tasks": "views/tasks.js",
        "knowledge": "views/knowledge.js",
    }
    for view, rel_path in sources.items():
        assert view in _route_tabs(), view
        assert "routeNoteTab('%s'" % view in _js(rel_path), rel_path


def test_every_tabbed_view_declares_the_tab_it_opens_on():
    """The default tab is what a bare /tasks means, so the router has to know
    it for every tabbed view. A view missing from the table would keep writing
    its default tab into the path, which is the /tasks/tasks this replaced, and
    Back out of a sibling tab would no longer restore it."""
    defaults = _route_default_tabs()
    assert set(defaults) == set(_route_tabs())
    for view, tab in defaults.items():
        assert tab in _route_tabs()[view], (view, tab)


def test_routed_tab_names_are_the_names_the_ui_uses():
    """A tab element id is internal; the path is not. Where the two disagree
    the router carries an alias, and the alias has to name a real tab or the
    path it writes would be a dead route."""
    tabs = _route_tabs()
    for view, aliases in _route_tab_aliases().items():
        assert view in tabs, view
        for tab, segment in aliases.items():
            assert tab in tabs[view], (view, tab)
            # An alias that collides with a sibling's id would make the path
            # ambiguous: _tabId resolves the alias first, so the sibling would
            # become unreachable.
            assert segment not in tabs[view], (view, segment)

    # The one that forced the mechanism: the tab is labelled Self-Evolution,
    # so it routes as /memory/evolution rather than under its element id.
    assert _route_tab_aliases()["memory"]["dreams"] == "evolution"
    assert 'data-i18n="memory_tab_dreams"' in template.render("chat.html")


def test_the_backend_accepts_the_aliased_tab_segments():
    """A shared /memory/evolution link arrives at the backend, which matches
    tab segments by pattern rather than by name -- an alias the pattern does
    not cover would 404 before the router ever saw it."""
    served = re.search(r"\(\?:/(\[[^\]]+\]\+)\)\?/\?", _backend_urls())
    assert served, "the tab-segment pattern is no longer where tests can read it"
    pattern = re.compile("^%s$" % served.group(1))

    for view, aliases in _route_tab_aliases().items():
        for segment in aliases.values():
            assert pattern.match(segment), (view, segment)


def test_a_guarded_navigation_keeps_the_tab_it_was_asked_for():
    """navigateTo refuses while a document editor holds unsaved changes and
    retries through a callback once the user discards them. The retry has to
    carry the tab, or a routed navigation that hits the guard quietly lands on
    the view's default tab instead of the one the URL named."""
    nav = _js("core/nav.js")
    assert "docGuardUnsaved(() => navigateTo(viewId, tab))" in nav


def test_the_router_loads_after_the_navigation_it_drives():
    """router.js calls navigateTo and validates against VIEW_META, both of
    which live in nav.js."""
    page = template.render("chat.html")
    scripts = re.findall(r'<script defer src="/assets/(js/[^"?]+)(?:\?[^"]*)?"', page)

    assert scripts.count("js/core/router.js") == 1, scripts
    assert scripts.index("js/core/nav.js") < scripts.index("js/core/router.js")


def _backend_urls():
    with open(os.path.join(WEB, "web_channel.py"), encoding="utf-8") as f:
        source = f.read()
    table = re.search(r"\nURLS = \((.*?)\n\)", source, re.S)
    assert table, "the URL table is no longer where the tests can read it"
    return table.group(1)


def test_the_backend_serves_every_path_the_router_hands_out():
    """The router writes these paths into the address bar, so a reload or a
    shared link arrives at the backend asking for one. A path the URL table
    does not serve is a 404 on an address the console itself produced."""
    served = re.search(r"'/\(\?:([a-z|]+)\)'", _backend_urls())
    assert served, "the view-route pattern is no longer where the tests can read it"
    served = set(served.group(1).split("|"))

    handed_out = {path for path in _route_paths().values() if path}
    assert handed_out == served, (sorted(handed_out), sorted(served))


def test_no_view_path_shadows_an_api_route():
    """web.py takes the first match in the table, so a view named after an
    existing endpoint would not break visibly -- it would quietly serve HTML
    where the console expects JSON, or never reach the view at all. /settings
    exists for exactly this reason: /config is the config API."""
    urls = _backend_urls()
    endpoints = set(re.findall(r"^\s*'(/[^']*)',\s*'\w+Handler'", urls, re.M))

    for path in _route_paths().values():
        if not path:
            continue
        assert "/" + path not in endpoints, path

    # The collision that forced the naming, pinned so it cannot quietly return.
    assert "/config" in endpoints
    assert _route_paths()["config"] == "settings"


def test_the_console_answers_at_the_root():
    """The console is the app at /, not a page at /chat with state after it.
    /chat stays as a redirect: it is what older bookmarks, and the startup
    banner of a running instance, still point at."""
    urls = _backend_urls()
    assert re.search(r"'/',\s*'ChatHandler'", urls)
    assert re.search(r"'/chat',\s*'RootHandler'", urls)

    # web.py takes the first match, so a second /chat entry is unreachable --
    # it looks like it serves the page and does nothing at all.
    assert len(re.findall(r"^\s*'/chat',", urls, re.M)) == 1, urls

    with open(os.path.join(WEB, "api", "pages.py"), encoding="utf-8") as f:
        source = f.read()
    root = source[source.index("class RootHandler:"):]
    root = root[:root.index("\n\n\nclass ")]
    assert "'Location': '/'" in root
    # web.seeother() would send an absolute http:// URL behind an HTTPS proxy.
    assert "raise web.seeother" not in root


def test_chat_redirect_keeps_the_scheme_behind_an_https_proxy():
    # A subprocess, because other test modules stub the web package in-process.
    import subprocess
    import sys

    script = (
        "import io\n"
        "from channel.web import web_channel\n"
        "app = web_channel.build_app()\n"
        "env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/chat', 'QUERY_STRING': '',\n"
        "       'HTTP_HOST': 'cow.example.com', 'HTTP_X_FORWARDED_PROTO': 'https',\n"
        "       'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(b''),\n"
        "       'SERVER_NAME': 'cow.example.com', 'SERVER_PORT': '80'}\n"
        "seen = {}\n"
        "def start_response(status, headers, exc_info=None):\n"
        "    seen['status'] = status; seen['headers'] = dict(headers)\n"
        "b''.join(app.wsgifunc()(env, start_response))\n"
        "print(seen['status'].split()[0], seen['headers']['Location'])\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "303 /"


def test_the_first_route_is_applied_only_once_auth_has_settled():
    """Routing at load time would switch views behind the login overlay, so
    the first apply hangs off initApp() -- the one function all three paths
    into the app go through. The router itself must only listen at load time."""
    auth = _js("core/auth.js")
    init = auth[auth.index("function initApp()"):]
    init = init[:init.index("\n}")]
    assert "routeApply()" in init

    router = _js("core/router.js")
    assert "addEventListener('popstate', routeApply)" in router
    # A bare call at the top level would run before auth.
    assert not re.search(r"^routeApply\(\)", router, re.M)
