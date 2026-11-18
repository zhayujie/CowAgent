# encoding:utf-8
"""``Agent._estimate_text_tokens`` weighs ASCII and non-ASCII characters.

The whole history goes through it on every LLM call, so the count is done in C
(``str.encode``) instead of a per-character Python loop. These pin the result
to the per-character rule: code points up to 127 count 0.25, the rest 1.5.
"""

from agent.protocol.agent import Agent


def _per_character(text):
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return int(non_ascii * 1.5 + (len(text) - non_ascii) * 0.25) + 1


def test_empty_text_is_zero():
    assert Agent._estimate_text_tokens("") == 0
    assert Agent._estimate_text_tokens(None) == 0


def test_ascii_and_non_ascii_weights():
    assert Agent._estimate_text_tokens("abcd") == 2
    assert Agent._estimate_text_tokens("\x7f") == 1
    assert Agent._estimate_text_tokens("\x80") == 2
    assert Agent._estimate_text_tokens("中文") == 4
    # One code point outside the BMP is still one character.
    assert Agent._estimate_text_tokens("\U0001F44D") == 2


def test_matches_per_character_count():
    samples = [
        "def run(self):\n    return 1\n" * 50,
        "帮我看一下这个函数 and fix the bug 吧。\n" * 50,
        "café naïve résumé",
        "ok 👍🏽 done ✅ " * 20,
        "lone \udcff surrogate",
    ]
    for text in samples:
        assert Agent._estimate_text_tokens(text) == _per_character(text)
