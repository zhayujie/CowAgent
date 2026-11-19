"""Extract literal paths from the PowerShell writes covered by the shell policy."""

import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Tuple


ALIASES = {
    "ri": "remove-item",
    "cpi": "copy-item",
    "mi": "move-item",
    "ni": "new-item",
    "sc": "set-content",
    "rni": "rename-item",
    "clc": "clear-content",
    "ac": "add-content",
}

# Built-in pwsh aliases that share a name with POSIX or CMD commands. They are
# bound as cmdlets only when the active shell is known to be PowerShell; under
# bash or cmd the same names keep their native argument syntax.
POSIX_NAMED_ALIASES = {
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item",
    "rd": "remove-item", "rmdir": "remove-item",
    "cp": "copy-item", "copy": "copy-item",
    "mv": "move-item", "move": "move-item",
    "ren": "rename-item", "tee": "tee-object",
}

# Parameters that occupy a positional slot even if the caller binds it by name.
_POSITIONS = {
    "remove-item": ("path",),
    "set-content": ("path", "value"),
    "add-content": ("path", "value"),
    "clear-content": ("path",),
    "out-file": ("path", "encoding"),
    "new-item": ("path",),
    "copy-item": ("path", "destination"),
    "move-item": ("path", "destination"),
    "rename-item": ("path", "newname"),
    "tee-object": ("path",),
    "expand-archive": ("path", "destination"),
}

_COMMON_ALIASES = {
    "vb": "verbose", "db": "debug", "ea": "erroraction", "ev": "errorvariable",
    "wa": "warningaction", "wv": "warningvariable", "infa": "informationaction",
    "iv": "informationvariable", "proga": "progressaction", "ov": "outvariable",
    "ob": "outbuffer", "pv": "pipelinevariable", "wi": "whatif", "cf": "confirm",
}
_SWITCHES = frozenset({
    "append", "asbytestream", "confirm", "container", "force", "noclobber", "nonewline",
    "passthru", "recurse", "whatif", "verbose", "debug",
})
# Keep the FileSystem provider's parameter names distinct until after prefix
# resolution, even when two names ultimately bind the same path slot.
_FILE_PROVIDER = "path literalpath filter include exclude force credential"
_CONTENT = f"{_FILE_PROVIDER} value passthru nonewline encoding asbytestream stream"
_CMDLET_PARAMETERS = {
    "remove-item": f"{_FILE_PROVIDER} recurse stream",
    "set-content": _CONTENT,
    "add-content": _CONTENT,
    "clear-content": f"{_FILE_PROVIDER} stream",
    "out-file": "filepath literalpath encoding append force noclobber width nonewline inputobject",
    "new-item": "path name itemtype value force credential",
    "copy-item": f"{_FILE_PROVIDER} destination container recurse passthru fromsession tosession",
    "move-item": f"{_FILE_PROVIDER} destination passthru",
    "rename-item": "path literalpath newname force passthru credential",
    "tee-object": "inputobject filepath literalpath append encoding variable",
    "expand-archive": "path literalpath destinationpath force passthru",
}
_CMDLET_ALIASES = {
    "out-file": {"path": "filepath", "nooverwrite": "noclobber"},
    "tee-object": {"path": "filepath"},
    "new-item": {"type": "itemtype", "target": "value"},
}
_PATH_SLOTS = {"literalpath": "path", "filepath": "path", "destinationpath": "destination"}
_PARAMETER_DASHES = frozenset("-\u2013\u2014\u2015")
_LOCATION_COMMANDS = frozenset({
    "set-location", "push-location", "pop-location", "cd", "cd..", "cd\\", "cd~", "chdir", "sl", "pushd", "popd",
    "new-psdrive", "remove-psdrive", "ndr", "rdr",
})


def _parameter_names(cmdlet: str, parameters: str) -> Dict[str, str]:
    common = {alias: name for alias, name in _COMMON_ALIASES.items()
              if cmdlet != "tee-object" or name not in {"whatif", "confirm"}}
    names = {name: name for name in (*parameters.split(), *common.values())}
    names.update(common)
    if "literalpath" in names:
        names["pspath"] = "literalpath"
        if cmdlet != "expand-archive":
            names["lp"] = "literalpath"
    names.update(_CMDLET_ALIASES.get(cmdlet, {}))
    return names


_PARAMETER_NAMES = {cmdlet: _parameter_names(cmdlet, params) for cmdlet, params in _CMDLET_PARAMETERS.items()}


def _parameter(cmdlet: str, key: str) -> Optional[str]:
    """Resolve a name or unique prefix using only this cmdlet's parameters."""
    names = _PARAMETER_NAMES[cmdlet]
    parameter = names.get(key)
    if parameter is None and key:
        matches = {name for alias, name in names.items() if alias.startswith(key)}
        if len(matches) == 1:
            parameter = matches.pop()
    return parameter

_SINGLE_QUOTES = "'\u2018\u2019\u201a\u201b"
_DOUBLE_QUOTES = '"\u201c\u201d\u201e'
_SINGLE = rf"[{_SINGLE_QUOTES}](?:[{_SINGLE_QUOTES}]{{2}}|[^{_SINGLE_QUOTES}])*[{_SINGLE_QUOTES}]"
_DOUBLE = rf'[{_DOUBLE_QUOTES}](?:[{_DOUBLE_QUOTES}]{{2}}|`[\s\S]|[^{_DOUBLE_QUOTES}`])*[{_DOUBLE_QUOTES}]'
_BRACED_VARIABLE = r"\$\{(?:`[\s\S]|[^}`])*\}"
_FILE_TYPE = r"(?:system\.)?io\.(?:file|directory)"
_NULL_STRING_TYPE = r"(?:system\.management\.automation\.language\.)?nullstring"
_FILE_ENUM = r"(?:system\.)?io\.file(?:mode|access)"
_SPACED_TYPE = rf"(?i:\[\s*(?:{_FILE_TYPE}|{_NULL_STRING_TYPE}|{_FILE_ENUM})\s*\])"
_BARE = rf"(?:{_BRACED_VARIABLE}|{_SPACED_TYPE}|`[^\r\n]|[^\s{_SINGLE_QUOTES}{_DOUBLE_QUOTES};&|{{}}()<>,`])+"
_WORD_PARTS = re.compile(rf"(?P<single>{_SINGLE})|(?P<double>{_DOUBLE})|(?P<bare>{_BARE})")

# Retain quotes and commas until argument binding. Backslashes are preserved, and
# a quote within a bare word starts a quoted fragment of that same argument.
_TOKENS = re.compile(
    r"(?P<continuation>`\r?\n)|(?P<comment><\#[\s\S]*?\#>|\#[^\r\n]*)"
    r"|(?P<boundary>\r?\n|[;&|{}()])|(?P<redirect>(?:\d+|\*)?(?:>>?|<)(?:&\d+)?)|(?P<comma>,)"
    rf"|(?P<single>{_SINGLE})|(?P<double>{_DOUBLE})"
    rf"|(?P<word>{_BARE}(?:(?:{_SINGLE}|{_DOUBLE}){_BARE}?)*)|(?P<invalid>\S)"
)
_STATIC_TYPE = re.compile(
    rf"\[\s*(?:system\.)?io\.(?P<type>file|directory)\s*\]::(?P<method>\w*|{_SINGLE}|{_DOUBLE})$",
    re.IGNORECASE,
)
_NULL_STRING = re.compile(rf"\[\s*{_NULL_STRING_TYPE}\s*\]::value", re.IGNORECASE)
# Static members that only read. Every other [IO.File] / [IO.Directory] method
# is treated as a write to its path arguments, so a new writer fails closed.
_STATIC_READS = {
    "file": frozenset({
        "exists", "readalltext", "readallbytes", "readalllines", "readlines", "openread",
        "opentext", "getattributes", "getcreationtime", "getcreationtimeutc",
        "getlastaccesstime", "getlastaccesstimeutc", "getlastwritetime",
        "getlastwritetimeutc", "getunixfilemode", "resolvelinktarget",
    }),
    "directory": frozenset({
        "exists", "getfiles", "getdirectories", "getfilesystementries", "enumeratefiles",
        "enumeratedirectories", "enumeratefilesystementries", "getcurrentdirectory",
        "getparent", "getdirectoryroot", "getlogicaldrives", "getcreationtime",
        "getcreationtimeutc", "getlastaccesstime", "getlastaccesstimeutc",
        "getlastwritetime", "getlastwritetimeutc", "resolvelinktarget",
    }),
}
# Path arguments each writer changes; the default is the first argument.
# File.Copy only reads its source, while Move and Replace also remove theirs.
_STATIC_WRITE_ARGUMENTS = {
    ("file", "copy"): (1,),
    ("file", "move"): (0, 1),
    ("file", "replace"): (0, 1, 2),
    ("directory", "move"): (0, 1),
}

@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    start: int = 0
    end: int = 0

    def literal(self) -> Optional[str]:
        if self.kind not in {"word", "single", "double"} or self.text.startswith("@"):
            return None
        fragments = []
        for part in _WORD_PARTS.finditer(self.text):
            text = part.group()
            if part.lastgroup == "single":
                fragments.append(re.sub(rf"([{_SINGLE_QUOTES}])[{_SINGLE_QUOTES}]", r"\1", text[1:-1]))
            elif "$" in text or "`" in text:
                return None
            elif part.lastgroup == "double":
                fragments.append(re.sub(rf"([{_DOUBLE_QUOTES}])[{_DOUBLE_QUOTES}]", r"\1", text[1:-1]))
            else:
                fragments.append(text)
        return "".join(fragments)


def _argument(tokens: Sequence[_Token], index: int) -> Tuple[List[Optional[str]], int]:
    """Consume a scalar or the comma-separated elements of one argument."""
    values = []
    while index < len(tokens):
        values.append(tokens[index].literal())
        index += 1
        if index == len(tokens) or tokens[index].kind != "comma":
            break
        index += 1
    return values or [None], index


def _bind_paths(
    name: str, tokens: Sequence[_Token],
) -> Optional[Tuple[Dict[str, List[Optional[str]]], bool]]:
    named = {}
    positional = []
    index = 0
    literal_path = False
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "redirect":
            # `2>&1` duplicates a stream and has no separate target token.
            index += 1 if "&" in token.text else 2
            continue
        if token.kind not in {"word", "interpolated"} or token.text[:1] not in _PARAMETER_DASHES:
            values, index = _argument(tokens, index)
            positional.append(values)
            continue

        key, _, inline = token.text[1:].partition(":")
        key = _parameter(name, key.lower())
        literal_path |= key == "literalpath"
        key = _PATH_SLOTS.get(key, key)
        index += 1
        if key in _SWITCHES:
            continue
        # Remote Copy-Item sessions have no local filesystem path to check.
        if key is None or key in named or key in {"fromsession", "tosession"}:
            return None
        if inline:
            remaining = [_Token("word", inline), *tokens[index:]]
            values, consumed = _argument(remaining, 0)
            index += consumed - 1
        else:
            values, index = _argument(tokens, index)
        named[key] = values

    for key, values in zip((key for key in _POSITIONS[name] if key not in named), positional):
        named[key] = values
    return named, literal_path


def _provider_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    provider, separator, suffix = path.partition("::")
    if separator:
        if provider.rsplit("\\", 1)[-1].lower() != "filesystem":
            return None
        path = suffix
    return path or None


def _filesystem_path(path: Optional[str], cwd: Optional[str]) -> Optional[str]:
    path = _provider_path(path)
    if not path:
        return None
    if path == "~" or path.startswith(("~/", "~\\")):
        path = os.path.expanduser(path)
    return _absolute_path(path, cwd)


def _absolute_path(path: str, cwd: Optional[str]) -> Optional[str]:
    drive, tail = os.path.splitdrive(path)
    if drive:
        return path if tail.startswith(("/", "\\")) or drive.startswith(("//", "\\\\")) else None
    if re.match(r"^[^/\\]+:", path):
        return None  # Drive-relative or a provider drive we cannot resolve.
    if os.name != "nt" and os.path.isabs(path):
        return path
    return os.path.join(cwd, path) if cwd else None


_WILDCARDS = re.compile(r"[*?\[\x60]")


def _filesystem_paths(path: Optional[str], cwd: Optional[str], literal: bool) -> List[Optional[str]]:
    resolved = _filesystem_path(path, cwd)
    provider_path = _provider_path(path)
    if resolved is None or literal or not _WILDCARDS.search(provider_path):
        return [resolved]

    parent, pattern = os.path.split(resolved)
    # Resolve simple filename globs. Directory globs, escaped patterns and `?`
    # have provider-specific behavior, including Windows' zero-width `?`.
    if _WILDCARDS.search(os.path.dirname(provider_path)) or "`" in pattern or "?" in pattern or not pattern.isascii():
        return [None]
    if not re.fullmatch(r"(?:[^\[\]]|\[[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?\])+", pattern):
        return [None]
    match = re.compile(fnmatch.translate(pattern), re.IGNORECASE).fullmatch
    try:
        with os.scandir(parent) as entries:
            # PowerShell's provider ignores case. Include hidden files and
            # disregard filters here so they cannot hide a protected match.
            matches = [entry.path for entry in entries if match(entry.name) or not entry.name.isascii()]
    except (OSError, ValueError):
        return [None]
    return matches or [None]


def _cmdlet_targets(name: str, tokens: Sequence[_Token], cwd: Optional[str]) -> List[Optional[str]]:
    binding = _bind_paths(name, tokens)
    if binding is None:
        return [None]
    bound, literal_path = binding
    if name == "tee-object" and "path" not in bound and "variable" in bound:
        return []  # Tee-Object -Variable keeps the copy in memory.

    literal_path |= name == "new-item" and "name" not in bound
    paths = [target for path in bound.get("path", [None])
             for target in _filesystem_paths(path, cwd, literal_path)]
    if name == "new-item" and "name" in bound:
        names = bound["name"]
        child = names[0] if len(names) == 1 else None
        parents = paths if "path" in bound else [cwd]
        return [os.path.join(path, child) if path and child else None for path in parents]
    if name == "rename-item":
        names = bound.get("newname", [])
        child = names[0] if len(names) == 1 else None
        return paths + [os.path.join(os.path.dirname(path), child) if path and child else None
                        for path in paths]
    if name == "expand-archive":
        if "destination" in bound:
            return [_filesystem_path(path, cwd) for path in bound["destination"]]
        return [_filesystem_path(os.path.splitext(os.path.basename(path))[0], cwd) if path else None
                for path in paths]
    if name not in {"copy-item", "move-item"}:
        return paths

    destinations = [_filesystem_path(path, cwd) for path in bound.get("destination", ["."])]
    targets = list(destinations)
    for destination in destinations:
        if destination and os.path.isdir(destination):
            targets.extend(os.path.join(destination, os.path.basename(os.path.normpath(path)))
                           if path else None for path in paths)
    if name == "move-item":
        targets.extend(paths)
    return targets


def write_targets(
    command: str, cwd: str, powershell: bool = False,
) -> Tuple[Optional[str], Iterator[Tuple[str, List[Optional[str]]]]]:
    """Return the known location and the write targets we can classify.

    ``powershell`` says the line is known to run in pwsh: POSIX-named aliases
    such as ``rm`` and ``cp`` then bind as cmdlets, and redirect targets are
    read with PowerShell quoting. A None path could not be resolved statically.
    """
    aliases = {**ALIASES, **POSIX_NAMED_ALIASES} if powershell else ALIASES
    tokens = [_Token(match.lastgroup, match.group(), match.start(), match.end()) for match in _TOKENS.finditer(command)
              if match.lastgroup not in {"comment", "continuation"}]
    segments = [_strip_assignments(segment) for segment in _command_segments(tokens)]
    segments = [segment[1:] if segment and segment[0].text == "." else segment for segment in segments]
    static_calls = [(writer, index + 1) for index, token in enumerate(tokens) if token.kind == "word"
                    for writer in (_STATIC_TYPE.search(token.text),) if writer]
    process_cwd = cwd
    for writer, index in static_calls:
        method, _ = _static_method(writer, tokens, index)
        if writer.group("type").lower() == "directory" and (method or "").lower() == "setcurrentdirectory":
            process_cwd = None

    # A location change can run in a pipeline, argument or branch. Only use
    # absolute provider paths when we cannot prove the script's location.
    location = process_cwd
    if any(_segment_name(segment) in _LOCATION_COMMANDS for segment in segments):
        location = None

    def targets():
        for writer, index in static_calls:
            yield from _static_targets(writer, tokens, index, process_cwd)
        for segment in segments:
            name = _segment_name(segment)
            name = aliases.get(name, name)
            if name in _POSITIONS:
                yield name, _cmdlet_targets(name, segment[1:], location)
            if powershell:
                yield from _redirect_targets(segment, location)

    return location, targets()


def _command_segments(tokens: Sequence[_Token]) -> Iterator[List[_Token]]:
    """Keep grouped arguments opaque in the outer command and inspect their bodies."""
    stack: List[List[_Token]] = [[]]
    for token in tokens:
        segment = stack[-1]
        if token.kind != "boundary":
            if (token.kind in {"word", "single", "double"} and segment and segment[-1].kind == "interpolated"
                    and segment[-1].end == token.start):
                prefix = segment[-1]
                segment[-1] = _Token(prefix.kind, prefix.text, prefix.start, token.end)
            else:
                segment.append(token)
            continue
        if token.text in "({":
            kind, text = "expression", ""
            if segment and segment[-1].kind == "word" and segment[-1].end == token.start:
                prefix = segment[-1].text
                if prefix in {"$", "@"}:
                    segment.pop()
                elif token.text == "(" and prefix.endswith("$"):
                    segment.pop()
                    kind = "interpolated"
                    key, colon, value = prefix.partition(":")
                    if key[0] in _PARAMETER_DASHES and colon:
                        text = key + ":$expression"
                        if value == "$":
                            kind = "word"
            segment.append(_Token(kind, text, token.start, token.end))
            stack.append([])
        elif not token.text.strip() and segment and segment[-1].kind in {"comma", "redirect"}:
            continue
        else:
            if segment:
                yield segment
            if token.text in ")}" and len(stack) > 1:
                stack.pop()
                prefix = stack[-1][-1]
                if prefix.kind == "interpolated":
                    stack[-1][-1] = _Token(prefix.kind, prefix.text, prefix.start, token.end)
            else:
                stack[-1] = []
    for segment in reversed(stack):
        if segment:
            yield segment


def _call_arguments(tokens: Sequence[_Token], index: int) -> List[List[_Token]]:
    """Split a method call's arguments without splitting nested expressions."""
    arguments: List[List[_Token]] = [[]]
    depth = 0
    for token in tokens[index:]:
        if token.kind == "boundary" and not token.text.strip():
            continue
        if token.text in "({" and token.kind == "boundary":
            depth += 1
        elif token.text in ")}" and token.kind == "boundary":
            if not depth:
                break
            depth -= 1
        elif token.kind == "comma" and not depth:
            arguments.append([])
            continue
        arguments[-1].append(token)
    return [] if arguments == [[]] else arguments


def _string_argument(arguments: Sequence[Sequence[_Token]], index: int) -> Optional[str]:
    if index < len(arguments) and len(arguments[index]) == 1:
        token = arguments[index][0]
        if token.kind in {"single", "double"}:
            return token.literal()
    return None


def _static_method(
    writer: re.Match, tokens: Sequence[_Token], index: int,
) -> Tuple[Optional[str], int]:
    method = writer.group("method")
    if not method and index < len(tokens):
        method = tokens[index].text
        index += 1
    return _Token("word", method).literal(), index


def _enum_argument(argument: Sequence[_Token], enum: str, member: str) -> bool:
    return len(argument) == 1 and bool(re.fullmatch(
        rf"\[\s*(?:system\.)?io\.{enum}\s*\]::{member}", argument[0].text, re.IGNORECASE,
    ))


def _static_targets(
    writer: re.Match, tokens: Sequence[_Token], index: int, cwd: Optional[str],
) -> Iterator[Tuple[str, List[Optional[str]]]]:
    kind = writer.group("type").lower()
    method, index = _static_method(writer, tokens, index)
    if index >= len(tokens) or tokens[index].text != "(":
        return  # A method reference, not a call.
    label = f"[IO.{'File' if kind == 'file' else 'Directory'}]"
    if not method:
        yield label, [None]
        return
    lookup = method.lower()
    if lookup.endswith("async"):
        lookup = lookup[:-len("async")]
    if lookup in _STATIC_READS[kind]:
        return

    arguments = _call_arguments(tokens, index + 1)
    if kind == "directory" and lookup == "setcurrentdirectory":
        return  # Changes the process location without writing a file.
    if ((kind, lookup) == ("file", "open") and len(arguments) in {3, 4}
            and _enum_argument(arguments[1], "filemode", "open")
            and _enum_argument(arguments[2], "fileaccess", "read")):
        return
    positions = _STATIC_WRITE_ARGUMENTS.get((kind, lookup), (0,))
    if (kind, lookup) == ("file", "replace") and len(arguments) > 2:
        backup = arguments[2]
        if len(backup) == 1 and backup[0].kind == "word" and _NULL_STRING.fullmatch(backup[0].text):
            positions = (0, 1)  # The intrinsic null string disables the backup file.
    paths = [_string_argument(arguments, i) for i in positions]
    yield f"{label}::{method}", [_absolute_path(path, cwd) if path else None for path in paths]


_VARIABLE = rf"(?:\[[^\]]+\])*(?:{_BRACED_VARIABLE}|\$[\w:.\[\]]+)"
_ASSIGN_OPERATOR = r"(?:[-+*/%]|\?\?)?="
_ASSIGNMENT_HEAD = re.compile(rf"(?P<variable>{_VARIABLE})(?P<operator>{_ASSIGN_OPERATOR})?(?P<rest>.*)")
_ASSIGNMENT_TAIL = re.compile(rf"{_ASSIGN_OPERATOR}(?P<rest>.*)")


def _strip_assignments(tokens: Sequence[_Token]) -> List[_Token]:
    """Drop ``$x =`` prefixes so ``$null = New-Item ...`` is seen as New-Item."""
    tokens = list(tokens)
    while tokens and tokens[0].kind == "word":
        head = _ASSIGNMENT_HEAD.fullmatch(tokens[0].text)
        if not head:
            break
        if head.group("operator"):  # `$x=...` or `$x= ...`
            rest = head.group("rest")
            tokens = ([_Token("word", rest)] if rest else []) + tokens[1:]
            continue
        if head.group("rest") or len(tokens) < 2 or tokens[1].kind != "word":
            break
        tail = _ASSIGNMENT_TAIL.fullmatch(tokens[1].text)
        if not tail:
            break
        rest = tail.group("rest")  # `$x = ...` or `$x =...`
        tokens = ([_Token("word", rest)] if rest else []) + tokens[2:]
    return tokens


def _segment_name(tokens: Sequence[_Token]) -> str:
    head = (tokens[0].literal() or "").lower() if tokens else ""
    return head if head in _LOCATION_COMMANDS else head.rsplit("\\", 1)[-1]


def _redirect_targets(tokens: Sequence[_Token], cwd: Optional[str]) -> Iterator[Tuple[str, List[Optional[str]]]]:
    for index, token in enumerate(tokens):
        if token.kind != "redirect" or ">" not in token.text or "&" in token.text:
            continue
        target = tokens[index + 1] if index + 1 < len(tokens) else None
        if target is not None and target.text.lower() == "$null":
            continue
        path = target.literal() if target is not None else None
        paths = _filesystem_paths(path, cwd, literal=False)
        # Native stdout redirection can also address the literal name.
        literal = _filesystem_path(path, cwd)
        if literal not in paths:
            paths.append(literal)
        yield "redirect", paths
