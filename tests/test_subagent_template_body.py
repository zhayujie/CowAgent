"""Template metadata delimiters must not become worker instructions."""

import pytest

from agent.subagent.templates import parse_template


@pytest.mark.parametrize(
    "header, body, newline",
    [
        ("description: Compare before --- after values.", "Return the summary.", "\n"),
        ('name: "before---after"\ndescription: Compare values.', "Return the summary.", "\n"),
        ("description: |\n  Compare before --- after values.", "Return the summary.", "\n"),
        ("description: Compare values.", "Return the summary.", "\n"),
        ("description: Compare values.", "Return summary.\n\n---\n\nKeep this rule.", "\n"),
        ("description: Compare values.", "Return the summary.", "\r\n"),
    ],
    ids=["inline-description", "quoted-name", "multiline-description", "ordinary", "body-rule", "crlf"],
)
def test_template_body_starts_after_the_complete_frontmatter(header, body, newline):
    content = ("---\n" + header + "\ntools: read\n---\n" + body).replace("\n", newline)
    template = parse_template(content, "research", "fixture")

    assert template is not None
    assert template.prompt == body.replace("\n", newline)
    assert template.tools == ["read"]
