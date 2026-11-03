"""HTML extraction keeps readable text and block boundaries."""

import pytest

from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize(
    "html, expected_lines",
    [
        ("<h1>Quarterly report</h1><p>Revenue increased.</p><p>Costs fell.</p>",
         ["Quarterly report", "Revenue increased.", "Costs fell."]),
        ("<ul><li>North</li><li>South</li></ul>", ["North", "South"]),
        ("<p>Street 12<br>Suite 34<br/>Paris</p>", ["Street 12", "Suite 34", "Paris"]),
        ("<table><tr><td>Revenue</td><td>42</td></tr><tr><td>Costs</td><td>17</td></tr></table>",
         ["Revenue", "42", "Costs", "17"]),
        ('<p title="a > b">Visible paragraph.</p>', ["Visible paragraph."]),
        ("<p>Caf&#233; costs &#x20ac;42 &copy; 2026.</p>", ["Café costs €42 © 2026."]),
        ("<p>Literal &amp;lt;p&amp;gt; &lt; 42 &gt; 17.</p>", ["Literal &lt;p&gt; < 42 > 17."]),
        ("<!-- hidden > comment --><p>Visible.</p>", ["Visible."]),
        ("<div>First<section>Second<p>Third</p></section>Fourth</div>",
         ["First", "Second", "Third", "Fourth"]),
    ],
)
def test_html_preserves_readable_text(html, expected_lines):
    text = WebFetch._extract_text(html)
    assert [line for line in text.splitlines() if line] == expected_lines


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<p>Py<strong>thon</strong> is <em>useful</em>.</p>", "Python is useful."),
        ("<p>Before<script>if (a < b) {secret()}</script><style>.secret {color:red}</style> after.</p>",
         "Before after."),
        ("<P>中文 <SPAN>résumé</SPAN> 🐄</P>", "中文 résumé 🐄"),
        ("Plain text\n\nwith   spaces", "Plain text\n\nwith spaces"),
        ('<p>Read <a href="/doc?a=1&amp;b=2">the guide</a> today.</p>', "Read the guide today."),
        ('<p>Before <img src="photo.png" alt="Photo"> after.</p>', "Before after."),
        ("<p>Text <script>document.write('<style>hidden</style>')</script> stays.</p>", "Text stays."),
        ("<p>Text <style>p::after {content: '<script>hidden</script>'}</style> stays.</p>", "Text stays."),
        ("<p>Unclosed <strong>inline", "Unclosed inline"),
        ("2 < 3 and 5 > 4", "2 < 3 and 5 > 4"),
        ("<p>Before<script>unterminated secret", "Before"),
        ("<p>Before<style>unterminated secret", "Before"),
        ("<p>A &amp; B &lt; C &gt; D &quot;x&quot; &#39;y&#39; &nbsp; E</p>",
         'A & B < C > D "x" \'y\' E'),
        ("", ""),
    ],
)
def test_existing_text_controls(html, expected):
    assert WebFetch._extract_text(html) == expected


@pytest.mark.parametrize(
    "html, expected",
    [
        pytest.param(
            '<p>Put   this in <code>config.yaml</code>:</p><pre><code class="language-yaml">'
            "server:\n  port: 8080\n  tls:\n    enabled: true\n</code></pre><p>Then restart.</p>",
            "Put this in config.yaml:\n\nserver:\n  port: 8080\n  tls:\n    enabled: true\n\nThen restart.",
            id="yaml",
        ),
        pytest.param(
            '<div class="highlight"><pre><span></span><span class="k">def</span> <span class="nf">main</span>'
            '<span class="p">():</span>\n    <span class="k">if</span> <span class="n">ready</span>'
            '<span class="p">():</span>\n        <span class="n">serve</span><span class="p">()</span>\n</pre></div>',
            "def main():\n    if ready():\n        serve()",
            id="pygments",
        ),
        pytest.param(
            "<pre>x = 1        # one\nlonger = 22  # two\n\n\nprint(x)</pre>",
            "x = 1        # one\nlonger = 22  # two\n\n\nprint(x)",
            id="alignment-and-blank-lines",
        ),
        pytest.param("<pre>build:\n\tgo build ./...\n</pre>", "build:\n\tgo build ./...", id="tabs"),
        pytest.param(
            # Docusaurus: a block per line, each ended by <br/>.
            '<pre><code><div class="token-line"><span>export default {</span><br/></div>'
            '<div class="token-line"><span>  title: "Docs",</span><br/></div>'
            '<div class="token-line"><span></span><br/></div>'
            '<div class="token-line"><span>};</span><br/></div></code></pre>',
            'export default {\n  title: "Docs",\n\n};',
            id="block-and-br-per-line",
        ),
        pytest.param(
            # Expressive Code (Starlight): a block per line; an empty line holds a newline.
            '<pre><code><div class="ec-line"><div class="code">items:</div></div>'
            '<div class="ec-line"><div class="code"><span class="indent">  </span>- one</div></div>'
            '<div class="ec-line"><div class="code">\n</div></div>'
            '<div class="ec-line"><div class="code"><span class="indent">  </span>- two</div></div></code></pre>',
            "items:\n  - one\n\n  - two",
            id="block-per-line",
        ),
        pytest.param(
            "<pre>\r\n    first();\r\n    second();\r\n</pre>",
            "    first();\n    second();",
            id="newline-after-pre-and-crlf",
        ),
        pytest.param(
            "<pre>if (a &lt; b &amp;&amp; c) {\n    s = &quot;&amp;lt;&quot;;\n}</pre>",
            'if (a < b && c) {\n    s = "&lt;";\n}',
            id="entities",
        ),
        pytest.param(
            "<pre>  a = 1<script>track('<pre>')</script>\n  b = 2</pre>",
            "  a = 1\n  b = 2",
            id="script-inside-pre",
        ),
        pytest.param("<p>Run:</p><pre>  make\n    install", "Run:\n\n  make\n    install", id="unclosed"),
        pytest.param(
            # NUL characters are dropped from page text, so it can't stand in for a <pre> block.
            "<pre>  first</pre><p>a\0b</p><pre>  second</pre>",
            "  first\n\nab\n\n  second",
            id="nul-in-text",
        ),
        pytest.param("<p>A</p><pre>\n</pre><p>B</p>", "A\n\nB", id="empty"),
    ],
)
def test_pre_keeps_code_as_written(html, expected):
    assert WebFetch._extract_text(html) == expected


@pytest.mark.parametrize(
    "html, base_url, expected",
    [
        pytest.param('<p>Before <img src="https://cdn.example.com/a.png" alt="Overview"> after.</p>', "",
                     "Before ![Overview](https://cdn.example.com/a.png) after.", id="absolute"),
        pytest.param('<p><img src="/img/b.png" alt="Flow"></p>', "https://blog.example.com/post.html?lang=en",
                     "![Flow](https://blog.example.com/img/b.png)", id="relative-resolved"),
        pytest.param('<img src="data:image/gif;base64,R0lG" data-src="https://cdn.example.com/lazy.png">', "",
                     "![](https://cdn.example.com/lazy.png)", id="lazy-loaded"),
        pytest.param('<img src="https://t.example.com/p.gif" width="1" height="1"><p>Text</p>', "",
                     "Text", id="tracking-pixel"),
        pytest.param('<img src="https://cdn.example.com/a.png"><img src="https://cdn.example.com/a.png"/>', "",
                     "![](https://cdn.example.com/a.png)", id="deduplicated"),
        pytest.param('<img src="https://cdn.example.com/my pic (1).png" alt="A [b]\nc">', "",
                     "![A b c](https://cdn.example.com/my%20pic%20%281%29.png)", id="escaped"),
        pytest.param('<img src="javascript:alert(1)"><img src="/x.png">', "",
                     "", id="unsafe-or-unresolved"),
        pytest.param('<pre><img src="https://cdn.example.com/a.png">code</pre>', "",
                     "code", id="inside-pre"),
    ],
)
def test_images_become_markdown(html, base_url, expected):
    assert WebFetch._extract_text(html, base_url) == expected
