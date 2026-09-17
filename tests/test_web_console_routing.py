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

from channel.web import template

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
    table = re.search(r"\n        urls = \((.*?)\n        \)", source, re.S)
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

    with open(os.path.join(WEB, "web_channel.py"), encoding="utf-8") as f:
        source = f.read()
    root = source[source.index("class RootHandler:"):]
    assert "seeother('/')" in root[:root.index("\n\n\nclass ")]


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


def test_the_old_console_is_sent_back_to_the_root():
    """`python app.py -old` serves a snapshot that predates routing: no router,
    and its scripts referenced relatively. Under /settings/models a browser
    would look for them beside that path and render nothing, so the view paths
    -- which all reach the same handler -- have to bounce back to /."""
    from unittest.mock import patch

    import web

    import channel.web.web_channel as web_channel

    # A handler driven straight from a test has no request context. seeother
    # resolves its Location against ctx.home, and raising writes through
    # ctx.headers, so both have to stand in for what a live request carries.
    fields = ("home", "path", "headers", "status", "output")
    try:
        with patch.dict(os.environ, {"COW_LEGACY_CONSOLE": "1"}):
            for path in ("/settings/models", "/agents", "/knowledge/graph"):
                web.ctx.home = "http://testserver"
                web.ctx.path = path
                web.ctx.headers = []
                web.ctx.status = "200 OK"
                web.ctx.output = ""
                try:
                    web_channel.ChatHandler().GET()
                except web.HTTPError:
                    # Raising is how web.py hands a redirect back; the status
                    # and Location it settled on are left on the context.
                    assert web.ctx.status.startswith("303"), (path, web.ctx.status)
                    location = dict(web.ctx.headers).get("Location")
                    assert location == "http://testserver/", (path, location)
                else:
                    raise AssertionError("%s served the snapshot" % path)
    finally:
        for key in fields:
            web.ctx.pop(key, None)
