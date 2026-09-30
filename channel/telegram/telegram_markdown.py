"""Markdown -> Telegram HTML.

Telegram's HTML parse mode understands only a small tag set (b/i/u/s/a/code/
pre/blockquote). Headings, lists, rules and tables have no tag equivalent, so
they are flattened into shapes that still read well inside a chat bubble.
"""

import html
import re

# Bot API limits. Telegram counts these after entity parsing, so measuring the
# markdown source against them errs on the safe side (tags add no length).
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

_FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_TABLE_RE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*\n?)+", re.M)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_DIVIDER_CELL_RE = re.compile(r"^:?-{2,}:?$")

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_RULE_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*&gt;\s?(.*)$")  # matched after escaping

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD_ALT_RE = re.compile(r"(?<!\w)__(.+?)__(?!\w)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
# The inner \S guards keep arithmetic like "2 * 3 * 4" from reading as emphasis.
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITALIC_ALT_RE = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")


def to_telegram_html(text: str) -> str:
    """Render markdown as the HTML subset Telegram accepts."""
    if not text:
        return ""

    # Code and tables are rendered first and parked behind placeholders so the
    # inline passes below cannot reinterpret their contents as formatting.
    parked: list[str] = []

    def park(rendered: str) -> str:
        parked.append(rendered)
        return f"\x00{len(parked) - 1}\x00"

    def fence(lang: str, code: str) -> str:
        lang = lang.strip()
        attr = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
        return park(f"<pre><code{attr}>{html.escape(code, quote=False)}</code></pre>")

    text = _replace_fenced_blocks(text, fence)
    # Whatever the line scan leaves, e.g. a fence closed on the code's own line.
    text = _FENCE_RE.sub(lambda m: fence(m.group(1) or "", m.group(2)), text)
    text = _TABLE_RE.sub(lambda m: park(_render_table(m.group(0))), text)
    text = _INLINE_CODE_RE.sub(
        lambda m: park(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text
    )

    text = html.escape(text, quote=False)
    text = "\n".join(_render_line(line) for line in text.split("\n"))
    text = _render_inline(text)

    text = _PLACEHOLDER_RE.sub(lambda m: parked[int(m.group(1))], text)
    return text.strip()


def _replace_fenced_blocks(text: str, render) -> str:
    """Replace each closed fenced code block with ``render(info, code)``.

    A block opens on a ``` or ~~~ line (a backtick fence's info string cannot
    contain a backtick) and closes on a line holding only a run of the same
    character that is at least as long, so ~~~ fences work and a ```` fence
    can show a ``` example. Unclosed fences are left as they are.
    """
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN_RE.match(lines[i])
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence_run = match.group(1)
            for j in range(i + 1, len(lines)):
                closing = lines[j].strip()
                if closing == fence_run[0] * len(closing) and len(closing) >= len(fence_run):
                    code = "".join(line + "\n" for line in lines[i + 1:j])
                    out.append(render(match.group(2), code))
                    i = j + 1
                    break
            else:
                out.append(lines[i])
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _render_table(block: str) -> str:
    """Lay a markdown table out as fixed-width text inside <pre>."""
    rows = []
    for line in block.strip().split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(_DIVIDER_CELL_RE.match(c) for c in cells if c):
            continue  # the |---|---| separator has no visual role here
        rows.append(cells)
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    sizes = [max(len(r[i]) for r in rows) for i in range(width)]
    lines = ["  ".join(c.ljust(sizes[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    return f"<pre>{html.escape(chr(10).join(lines), quote=False)}</pre>"


def _render_line(line: str) -> str:
    m = _HEADING_RE.match(line)
    if m:
        return f"<b>{m.group(1).strip()}</b>" if m.group(1).strip() else ""
    if _RULE_RE.match(line):
        return "—" * 12
    m = _QUOTE_RE.match(line)
    if m:
        return f"<blockquote>{m.group(1)}</blockquote>"
    m = _BULLET_RE.match(line)
    if m:
        return f"{m.group(1)}• {m.group(2)}"
    return line


def _render_inline(text: str) -> str:
    def link(m: re.Match) -> str:
        url = m.group(2).replace('"', "&quot;")
        return f'<a href="{url}">{m.group(1)}</a>'

    text = _LINK_RE.sub(link, text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_ALT_RE.sub(r"<b>\1</b>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_ALT_RE.sub(r"<i>\1</i>", text)
    return text
