"""Fenced code block scanning shared by the channels' markdown converters and message splitting."""

import re

_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


def _scan(text: str):
    """Yield ``(info, lines)`` for each closed fenced block, fences included,
    and ``(None, line)`` for every line outside one."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN_RE.match(lines[i])
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence_run = match.group(1)
            for j in range(i + 1, len(lines)):
                closing = lines[j].strip()
                if closing == fence_run[0] * len(closing) and len(closing) >= len(fence_run):
                    yield match.group(2), lines[i:j + 1]
                    i = j + 1
                    break
            else:
                yield None, lines[i]
                i += 1
            continue
        yield None, lines[i]
        i += 1


def replace_fenced_blocks(text: str, render) -> str:
    """Replace each closed fenced code block with ``render(info, code, block)``.

    ``info`` is the text after the opening fence, ``code`` the body with a
    trailing newline per line, and ``block`` the original lines, fences
    included. A block opens on a ``` or ~~~ line (a backtick fence's info
    string cannot contain a backtick) and closes on a line holding only a run
    of the same character that is at least as long, so ~~~ fences work and a
    ```` fence can show a ``` example. Unclosed fences are left as they are.
    """
    out = []
    for info, item in _scan(text):
        if info is None:
            out.append(item)
        else:
            code = "".join(line + "\n" for line in item[1:-1])
            out.append(render(info, code, "\n".join(item)))
    return "\n".join(out)


def transform_outside_fences(text: str, transform) -> str:
    """Apply ``transform`` to each run of text between closed fenced blocks,
    leaving the blocks themselves as written."""
    out = []
    prose = []
    for info, item in _scan(text):
        if info is None:
            prose.append(item)
            continue
        if prose:
            out.append(transform("\n".join(prose)))
            prose = []
        out.append("\n".join(item))
    if prose:
        out.append(transform("\n".join(prose)))
    return "\n".join(out)


def split_markdown(text: str, limit: int):
    """Split long text into chunks of at most ``limit`` characters, preferring
    line breaks to keep markdown structure intact.

    A cut inside a closed fenced block closes the block at the end of the
    chunk and reopens it with the same opening line, info string included,
    at the start of the next, so both parts still render as code.
    """
    if len(text) <= limit:
        yield text
        return
    head = ""  # the opening line that reopens a block at the start of a chunk
    buf = []
    size = 0
    open_block = None  # the block the buffered lines leave open
    for line, block in _lines(text, limit):
        # A line inside a block keeps room for the block's closing line.
        room = limit - len(block[1]) if block else limit
        if size + len(line) > room and buf:
            yield head + "".join(buf) + (open_block[1] if open_block else "")
            head = open_block[0] if open_block else ""
            buf, size = [], len(head)
        # Hard-split single lines that exceed the limit
        while size + len(line) > room:
            cut = room - size - (1 if block else 0)
            yield head + line[:cut] + ("\n" + block[1] if block else "")
            head = block[0] if block else ""
            line, size = line[cut:], len(head)
        buf.append(line)
        size += len(line)
        open_block = block
    if buf:
        yield head + "".join(buf)


def _lines(text: str, limit: int):
    """Yield ``(line, block)`` for each line of ``text``, line break included.

    ``block`` is the ``(opening, closing)`` line pair of the closed fenced
    block that is still open after the line, else None. A block's opening line
    comes joined to the line after it, so no chunk ends on it, and a block
    whose fence lines leave no room for code within ``limit`` is split as text.
    """
    items = list(_scan(text))
    for n, (info, item) in enumerate(items):
        end = "\n" if n < len(items) - 1 else ""
        if info is not None:
            block = (item[0] + "\n", item[-1] + end)
            if len(block[0]) + len(block[1]) + 2 <= limit:
                lines = [line + "\n" for line in item[1:-1]] + [block[1]]
                lines[0] = block[0] + lines[0]
                for line in lines[:-1]:
                    yield line, block
                yield lines[-1], None
                continue
            item = "\n".join(item)
        for line in (item + end).splitlines(keepends=True):
            yield line, None
