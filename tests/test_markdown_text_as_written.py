"""The web console and the desktop app show Markdown text as it was written.

Both render Markdown with markdown-it, and both had its ``typographer``
option on, which rewrites text outside code: ``(c)`` became a copyright sign,
two or more dots an ellipsis, ``+-`` a plus-minus sign, ``--`` a dash and
straight quotes curly ones. So ``cd ..`` read ``cd …``, ``Article 6(1)(c)``
read ``Article 6(1)©``, and ``git commit -m "fix typo"`` was shown with curly
quotes, which bash does not take as quotes.

The console's renderer is browser JS, so these tests run it in Node: the
vendored markdown-it and core/markdown.js, loaded as chat.html loads them.
"""

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Reads a JSON list of Markdown sources on stdin and prints the console's HTML
# for each, as a JSON list.
RENDER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const page = {document: {addEventListener() {}}};
page.window = page;
vm.createContext(page);
for (const file of ['channel/web/static/vendor/markdown-it/markdown-it.min.js',
                    'channel/web/static/js/core/markdown.js']) {
  vm.runInContext(fs.readFileSync(file, 'utf8'), page, {filename: file});
}
const md = vm.runInContext('md', page);
const sources = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(sources.map((source) => md.render(source))));
"""


def _render(*sources):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    result = subprocess.run(
        [node, "-e", RENDER],
        cwd=ROOT,
        input=json.dumps(sources),
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("Option (c) is correct.", id="copyright"),
        pytest.param("Processing is lawful under Article 6(1)(c) GDPR.", id="article"),
        pytest.param("Acme(R) and Widget(TM) are trademarks.", id="trademarks"),
        pytest.param("Run cd .. and open ../config.json", id="parent-dir"),
        pytest.param("Ruby ranges like 1..10 include 10.", id="range"),
        pytest.param("The tolerance is +- 0.5 mm.", id="plus-minus"),
        pytest.param("Run git checkout -- config.json to drop the change.", id="end-of-options"),
        pytest.param("Name them a--b and a---b.", id="dashes"),
        pytest.param("Really????? Yes!!!!! Well,, maybe.", id="punctuation"),
        pytest.param('Commit with git commit -m "fix typo"', id="double-quotes"),
        pytest.param("It's a 'test'.", id="single-quotes"),
        pytest.param('他说："你好"。', id="chinese-quotes"),
        pytest.param("正在处理...", id="chinese-dots"),
    ],
)
def test_text_renders_as_written(source):
    (rendered,) = _render(source)
    paragraph = re.fullmatch(r"<p>(.*)</p>\n", rendered)
    assert paragraph, rendered
    assert html.unescape(paragraph.group(1)) == source


def test_link_text_renders_as_written():
    (rendered,) = _render("See [../docs/setup.md](../docs/setup.md).")
    assert re.search(r'<a href="\.\./docs/setup\.md"[^>]*>\.\./docs/setup\.md</a>', rendered)


def test_code_spans_are_left_as_written():
    # markdown-it never rewrote code; this pins that it still doesn't.
    (rendered,) = _render('Type `cd ..`, then `git commit -m "(c)"`.')
    assert "<code>cd ..</code>" in rendered
    assert "<code>git commit -m &quot;(c)&quot;</code>" in rendered


def test_cjk_emphasis_and_link_cut_still_apply():
    # createMd's two fixes on top of markdown-it work on the same text.
    emphasis, link = _render('这是**"引号"**——', "访问 https://example.com，然后继续")
    assert "<strong>&quot;引号&quot;</strong>" in emphasis
    assert '<a href="https://example.com"' in link
    assert "</a>，然后继续" in link


def test_desktop_renderer_leaves_the_typographer_off():
    # The desktop app renders Markdown like the console, with markdown-it 14
    # and the same options; its dependencies aren't installed in CI.
    source = (ROOT / "desktop/src/renderer/src/components/Markdown.tsx").read_text(encoding="utf-8")
    start = source.index("new MarkdownIt({")
    options = source[start:source.index("highlight(", start)]
    assert "linkify: true" in options  # the slice holds the options
    assert not re.search(r"typographer:\s*true", options)
