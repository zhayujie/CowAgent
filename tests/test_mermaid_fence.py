# encoding:utf-8
"""Mermaid fences render as diagrams without leaving the local vendor tree."""

import os
import subprocess

WEB = os.path.join(os.path.dirname(__file__), "..", "channel", "web")
ROOT = os.path.join(os.path.dirname(__file__), "..")
STATIC = os.path.join(WEB, "static")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_closed_mermaid_fences_become_placeholders_and_open_ones_stay_code():
    script = os.path.join(WEB, "tools", "check-mermaid-fence.mjs")
    proc = subprocess.run(
        ["node", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "FENCE OK" in proc.stdout
    # jsdom lives at the path the smoke script imports. When it is present,
    # or when this runs in CI, a skipped drawing pass is a failed test.
    # A machine with neither still proves the fence rules above.
    jsdom = os.path.isfile("/tmp/mermaid-smoke/node_modules/jsdom/lib/api.js")
    require_svg = jsdom or os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
    if require_svg:
        assert "SVG OK" in proc.stdout, proc.stdout + "\n" + proc.stderr
    elif "SVG OK" not in proc.stdout:
        assert "SKIP svg" in proc.stdout


def test_mermaid_is_vendored_locally_and_loaded_lazily():
    vendor = os.path.join(STATIC, "vendor", "mermaid", "mermaid.min.js")
    assert os.path.isfile(vendor)
    assert os.path.getsize(vendor) > 1_000_000
    with open(vendor, "rb") as handle:
        handle.seek(-240, os.SEEK_END)
        tail = handle.read()
    assert b'globalThis["mermaid"]' in tail

    markdown = _read(os.path.join(STATIC, "js", "core", "markdown.js"))
    assert "securityLevel: 'strict'" in markdown
    assert "/assets/vendor/mermaid/mermaid.min.js" in markdown
    assert "cdn.jsdelivr.net" not in markdown
    assert "cdnjs.cloudflare.com" not in markdown

    css = _read(os.path.join(STATIC, "css", "markdown.css"))
    assert ".mermaid-diagram" in css
    assert "overflow-x: auto" in css

    from channel.web.core import template

    page = template.render("chat.html")
    assert page.index("js/core/mermaid-fence.js") < page.index("js/core/markdown.js")

    desktop_render = _read(os.path.join(
        ROOT, "desktop", "src", "renderer", "src", "lib", "mermaidRender.ts"))
    desktop_md = _read(os.path.join(
        ROOT, "desktop", "src", "renderer", "src", "components", "Markdown.tsx"))
    desktop_css = _read(os.path.join(ROOT, "desktop", "src", "renderer", "src", "index.css"))
    assert "securityLevel: 'strict'" in desktop_render
    assert "stripMermaidAnchorHrefs" in markdown
    assert "stripMermaidAnchorHrefs" in desktop_render
    assert "removeAttribute('href')" in markdown
    assert "removeAttribute('href')" in desktop_render
    assert "removeAttribute('xlink:href')" in markdown
    assert "removeAttribute('xlink:href')" in desktop_render
    assert "openMermaid" in desktop_md
    assert "streaming" in desktop_md
    assert ".mermaid-diagram" in desktop_css
    assert "overflow-x: auto" in desktop_css
