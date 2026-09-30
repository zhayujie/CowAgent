"""Fenced code blocks in the Telegram markdown -> HTML renderer.

``to_telegram_html`` found code blocks with ``_FENCE_RE`` alone, which only
knows backtick fences and closes a block at the first ``` it meets. A ~~~
block was rendered as prose (``# setup`` in bold, ``__init__`` as bold
``init``), and a ```` fence showing a ``` example closed at the inner fence,
leaving an empty <pre> and the example leaking out as formatted text.
"""

import pytest

from channel.telegram.telegram_markdown import to_telegram_html


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "~~~python\n# setup\ndef __init__(self): pass\n~~~",
            '<pre><code class="language-python"># setup\ndef __init__(self): pass\n</code></pre>',
            id="tilde-fence",
        ),
        pytest.param(
            "````markdown\n```python\nx = 1\n```\n````\nAfter **bold**",
            '<pre><code class="language-markdown">```python\nx = 1\n```\n</code></pre>\nAfter <b>bold</b>',
            id="longer-fence-around-example",
        ),
    ],
)
def test_fenced_code_is_rendered_as_code(markdown, expected):
    assert to_telegram_html(markdown) == expected


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "```python\nx = __y__\n```",
            '<pre><code class="language-python">x = __y__\n</code></pre>',
            id="backtick-fence",
        ),
        pytest.param("```\na < b\n```", "<pre><code>a &lt; b\n</code></pre>", id="no-language"),
        pytest.param("```python\nx\n```trailing", '<pre><code class="language-python">x\n</code></pre>trailing',
                     id="fence-closed-mid-line"),
    ],
)
def test_backtick_fence_output_is_unchanged(markdown, expected):
    assert to_telegram_html(markdown) == expected
