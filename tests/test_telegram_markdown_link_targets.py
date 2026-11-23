"""Markdown link targets are literal URLs, not emphasis source."""
import pytest

from channel.telegram.telegram_markdown import to_telegram_html


@pytest.mark.parametrize("source, expected", [
    (
        "[Function](https://en.wikipedia.org/wiki/Function_(mathematics))",
        '<a href="https://en.wikipedia.org/wiki/Function_(mathematics)">Function</a>',
    ),
    ("[a](https://x.y)", '<a href="https://x.y">a</a>'),
    ("[a](https://x.y) (note)", '<a href="https://x.y">a</a> (note)'),
])
def test_link_destination_parentheses(source, expected):
    assert to_telegram_html(source) == expected


@pytest.mark.parametrize("url", [
    "https://example.invalid/__archive__/report",
    "https://example.invalid/a*b*c",
    "https://example.invalid/~~draft~~",
    "https://example.invalid/api?first=1&path=__value__",
])
def test_link_url_is_not_rewritten_as_inline_markup(url):
    expected = url.replace("&", "&amp;")
    assert to_telegram_html(f"[report]({url})") == f'<a href="{expected}">report</a>'


def test_link_label_and_surrounding_emphasis_keep_formatting():
    assert to_telegram_html("**[Read *this*](https://example.invalid/__docs__)**") == (
        '<b><a href="https://example.invalid/__docs__">Read <i>this</i></a></b>'
    )


def test_inline_code_in_link_label_still_restores():
    assert to_telegram_html("[`__name__`](https://example.invalid/__docs__)") == (
        '<a href="https://example.invalid/__docs__"><code>__name__</code></a>'
    )


def test_multiple_links_and_literal_placeholder_text_are_preserved():
    source = "\x01link0\x01 [one](https://example.invalid/__a__) and [two](https://example.invalid/__b__)"
    assert to_telegram_html(source) == (
        '\x01link0\x01 <a href="https://example.invalid/__a__">one</a> and '
        '<a href="https://example.invalid/__b__">two</a>'
    )
