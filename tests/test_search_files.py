import os
import time

import pytest

from common.utils import expand_path
from agent.tools.search_files.search_files import SearchFiles, REGEX_MATCH_TIMEOUT_SECONDS


def _make_tool(tmp_path, **config_overrides):
    config = {"cwd": str(tmp_path)}
    config.update(config_overrides)
    return SearchFiles(config)


def _write(tmp_path, relpath, content):
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _matches(result):
    return result.result["matches"]


def test_appears_with_a_summary_in_the_system_prompt_tooling_section():
    # Every sibling file tool (read/write/edit/ls) has a one-line summary in
    # the "Tooling" section of the system prompt the model actually reads;
    # an entry with no summary ("- search_files" and nothing after it) would
    # be inconsistent with every other tool and silently degrade tool
    # selection quality. Only checks the integration point, not the
    # function's broader behavior (no prior test coverage of builder.py
    # exists to extend here).
    from agent.prompt.builder import _build_tooling_section

    fake_tool = type("FakeTool", (), {"name": "search_files"})()
    for language in ("en", "zh"):
        lines = _build_tooling_section([fake_tool], language)
        tooling_line = next(l for l in lines if l.startswith("- search_files"))
        assert tooling_line != "- search_files", f"missing summary for language={language}"


def test_configured_timeout_survives_the_real_tool_manager_wiring(tmp_path, monkeypatch):
    # Calls the real AgentInitializer._load_tools() — it only touches
    # self.agent_bridge inside the env_config special case, which search_files
    # doesn't hit, so bridge=None/agent_bridge=None is enough to exercise the
    # actual merge logic instead of hand-copying it here.
    from config import conf
    from bridge.agent_initializer import AgentInitializer

    monkeypatch.setitem(conf(), "tools", {"search_files": {"timeout": 5}})

    initializer = AgentInitializer(bridge=None, agent_bridge=None)
    tools = initializer._load_tools(
        workspace_root=str(tmp_path), memory_manager=None, memory_tools=[], session_id="test-session"
    )
    tool = next(t for t in tools if t.name == "search_files")
    assert tool.timeout == 5


# --- input validation -------------------------------------------------

def test_pattern_required_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({})
    assert result.status == "error"
    assert "pattern" in str(result.result).lower()


def test_invalid_regex_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "("})
    assert result.status == "error"
    assert "regex" in str(result.result).lower()


def test_nonexistent_path_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "x", "path": "does_not_exist"})
    assert result.status == "error"
    assert "not found" in str(result.result).lower()


def test_path_must_be_a_directory(tmp_path):
    _write(tmp_path, "file.txt", "hello")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "hello", "path": "file.txt"})
    assert result.status == "error"
    assert "directory" in str(result.result).lower()


def test_invalid_max_results_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "x", "max_results": 0})
    assert result.status == "error"

    result = tool.execute({"pattern": "x", "max_results": "not-a-number"})
    assert result.status == "error"

    # A fractional float must be rejected outright, not silently truncated
    # by int() (int(3.7) == 3 would otherwise mask a malformed argument).
    result = tool.execute({"pattern": "x", "max_results": 3.7})
    assert result.status == "error"


def test_integer_valued_float_max_results_is_accepted(tmp_path):
    # 3.0 is fractional-free (unlike 3.7 above) and must be accepted, not
    # rejected by the same is_integer() check that catches true fractions.
    for i in range(5):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 3.0})
    assert result.status == "success"
    assert len(_matches(result)) == 3


def test_file_glob_must_be_a_string(tmp_path):
    # Previously an unhandled TypeError from fnmatch.fnmatch(), swallowed by
    # base_tool.py's bare `except Exception: logger.error(e)` (no return) into
    # a bare None the caller then crashes on — instead of a clean ToolResult.fail.
    _write(tmp_path, "a.txt", "hello\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "hello", "file_glob": 42})
    assert result.status == "error"
    assert "file_glob" in str(result.result)


# --- security & limits ---------------------------------------------------

def test_max_results_above_hard_cap_is_capped_not_rejected(tmp_path, monkeypatch):
    import agent.tools.search_files.search_files as sf_module
    monkeypatch.setattr(sf_module, "MAX_RESULTS_CAP", 3)

    for i in range(5):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 100000})
    assert result.status == "success"
    assert len(_matches(result)) == 3
    # Must not suggest "use max_results=3" when 3 is already the hard cap —
    # that would just echo back the same number and read as a no-op suggestion.
    assert "hard maximum" in result.result["notice"]
    assert "max_results=3 " not in result.result["notice"]
    assert "max_results=6" not in result.result["notice"]
    assert "3 result limit reached" in result.result["notice"]


def test_credential_directory_is_blocked(tmp_path):
    # Matches read.py's test_security_read_env_bypass.py convention: the
    # direct _is_credential_path check and the execute() end-to-end check
    # (which must reject before any filesystem walk happens, and doesn't
    # depend on ~/.cow actually existing) live in the same test.
    tool = _make_tool(tmp_path)
    cow_dir = expand_path("~/.cow")
    assert tool._is_credential_path(cow_dir) is True
    assert tool._is_credential_path(cow_dir + "/some/nested/file.db") is True
    assert tool._is_credential_path(str(tmp_path)) is False

    result = tool.execute({"pattern": ".", "path": cow_dir})
    assert result.status == "error"
    assert "Access denied" in str(result.result)


def test_credential_directory_is_pruned_mid_walk(tmp_path, monkeypatch):
    # A broad search rooted above ~/.cow (not directly targeting it) must
    # still prune it during traversal rather than walking into it. Points
    # expand_path("~/.cow") at a fake dir under tmp_path so this exercises
    # the real _is_credential_path logic without touching the real home dir.
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / ".cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=leaked\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    assert result.result["matches"] == []


def test_proc_environ_paths_are_blocked(tmp_path):
    # Mirrors read.py's own test for issue #2913: pure path-string checks,
    # no real /proc access needed since _is_credential_path only pattern-matches.
    tool = _make_tool(tmp_path)
    assert tool._is_credential_path("/proc/self/environ") is True
    assert tool._is_credential_path("/proc/thread-self/environ") is True
    assert tool._is_credential_path(f"/proc/{os.getpid()}/environ") is True
    assert tool._is_credential_path("/proc/self/status") is False
    assert tool._is_credential_path("/proc/1/cmdline") is False


def test_symlink_to_credential_file_is_skipped_not_opened(tmp_path, monkeypatch):
    # The bug this guards against: _is_credential_path was only ever called
    # on directories (traversal pruning) and the root `path` argument — never
    # on the file actually about to be opened. A symlink inside the searched
    # tree pointing at a credential file sailed straight through, since
    # open() follows symlinks. Also verifies the fix is a silent per-file
    # skip (matches == [] for that file, overall status stays "success"),
    # not an error that aborts the whole search — a broad search shouldn't
    # blow up just because it incidentally crosses one bad symlink.
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / "fake_cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "decoy.txt").symlink_to(fake_cow / "secret.env")
    (workspace / "real.txt").write_text("API_KEY=this one is fine\n", encoding="utf-8")

    tool = _make_tool(workspace)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    files = {m["file"] for m in _matches(result)}
    assert "decoy.txt" not in files
    assert "real.txt" in files


def test_symlinked_directory_pointing_at_credential_dir_is_pruned(tmp_path, monkeypatch):
    # os.walk's default followlinks=False already refuses to descend into a
    # symlinked directory regardless of our own check, so this scenario is
    # doubly protected — but that's exactly why it's worth locking in with a
    # test: it confirms the dirnames-pruning branch in _search() does what
    # its comment claims, rather than relying solely on an os.walk default
    # this code doesn't control.
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / "fake_cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "decoy_dir").symlink_to(fake_cow, target_is_directory=True)

    tool = _make_tool(workspace)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    assert result.result["matches"] == []


def test_catastrophic_backtracking_pattern_is_preempted(tmp_path):
    # (a|aa)+$ genuinely defeats the `regex` package's own backtracking
    # optimizations (unlike simpler nested-quantifier patterns it resolves
    # instantly) — verified empirically to trip its native per-call timeout.
    # stdlib re already takes ~2s on this exact input and grows exponentially
    # from there (a 40-char line takes ~22s), so it has no such bound.
    _write(tmp_path, "evil.txt", "a" * 35 + "!\n")
    tool = _make_tool(tmp_path)

    start = time.monotonic()
    result = tool.execute({"pattern": r"(a|aa)+$"})
    elapsed = time.monotonic() - start

    assert result.status == "success"
    assert elapsed < REGEX_MATCH_TIMEOUT_SECONDS + 5
    assert "took longer than" in result.result["notice"]


def test_pattern_leading_trailing_whitespace_is_not_stripped(tmp_path):
    # Leading/trailing whitespace in `pattern` is meaningful for a regex
    # ("^ " only matches lines starting with a literal space) and must not
    # be trimmed the way path-like arguments are elsewhere in this codebase.
    _write(tmp_path, "a.txt", " leading_space_line\nno_leading_space_line\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "^ "})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert "leading_space_line" in _matches(result)[0]["match"]


def test_search_stops_at_timeout_and_reports_partial_results(tmp_path):
    for i in range(3):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    # A deadline already in the past forces the very first per-file check
    # in _search() to trip immediately, before any file is opened.
    tool = _make_tool(tmp_path, timeout=-1)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 0
    assert "stopped after" in result.result["notice"]


def test_deadline_is_also_checked_inside_a_single_large_file(tmp_path, monkeypatch):
    # See _search_single_file's docstring for why this check exists. Fakes
    # time.monotonic() to advance deterministically instead of sleeping, so
    # this stays fast and doesn't depend on machine speed.
    import agent.tools.search_files.search_files as sf_module

    _write(tmp_path, "big.txt", "\n".join(f"line {i}" for i in range(20)) + "\n")
    tool = _make_tool(tmp_path, timeout=1)

    fake_now = [0.0]

    def fake_monotonic():
        fake_now[0] += 0.2
        return fake_now[0]

    monkeypatch.setattr(sf_module.time, "monotonic", fake_monotonic)

    result = tool.execute({"pattern": "nonexistent"})
    assert result.status == "success"
    assert "stopped after" in result.result["notice"]


def test_traversal_order_is_deterministic(tmp_path):
    for name in ("zzz.txt", "aaa.txt", "mmm.txt"):
        _write(tmp_path, name, "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 2})
    assert result.status == "success"
    files = [m["file"] for m in _matches(result)]
    assert files == ["aaa.txt", "mmm.txt"]


# --- happy path -----------------------------------------------------------

def test_finds_matches_with_file_and_line(tmp_path):
    _write(tmp_path, "a.py", 'def f():\n    return "TARGET_MATCH here"\n')
    _write(tmp_path, "sub/b.py", "# another TARGET_MATCH in a subdirectory\nx = 1\n")
    _write(tmp_path, "notes.txt", "irrelevant, no target word\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET_MATCH"})
    assert result.status == "success"
    assert result.result["match_count"] == 2
    assert "notice" not in result.result

    files = {m["file"] for m in _matches(result)}
    assert files == {"a.py", "sub/b.py"}

    a_match = next(m for m in _matches(result) if m["file"] == "a.py")
    assert a_match["line"] == 2
    assert "TARGET_MATCH" in a_match["match"]


def test_no_matches_returns_empty_success_not_error(tmp_path):
    _write(tmp_path, "a.txt", "nothing interesting here\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "NOPE_NOT_PRESENT"})
    assert result.status == "success"
    assert result.result["matches"] == []
    assert result.result["match_count"] == 0


def test_file_glob_filters_results(tmp_path):
    _write(tmp_path, "match.py", "TARGET\n")
    _write(tmp_path, "match.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "file_glob": "*.py"})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"match.py"}


def test_empty_file_glob_matches_everything_like_the_default(tmp_path):
    # `file_glob = args.get("file_glob", "*") or "*"` — an empty string is
    # falsy, so it falls back to "*" the same as omitting the arg entirely.
    _write(tmp_path, "match.py", "TARGET\n")
    _write(tmp_path, "match.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "file_glob": ""})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"match.py", "match.txt"}


def test_max_results_caps_output_and_surfaces_notice_to_model(tmp_path):
    for i in range(10):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 3})
    assert result.status == "success"
    assert len(_matches(result)) == 3
    assert result.result["match_count"] == 3
    # The notice must live inside `result.result` — `agent_stream.py`'s
    # `_execute_tool` only forwards `status`/`result` to the model, so
    # anything on `ToolResult.ext_data` would silently never reach the LLM.
    assert result.result["notice"] == "3 result limit reached. Use max_results=6 to see more."


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "binary.bin").write_bytes(bytes(range(256)))
    _write(tmp_path, "text.txt", "hello\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "."})
    assert result.status == "success"
    files = {m["file"] for m in _matches(result)}
    assert "binary.bin" not in files
    assert "text.txt" in files


def test_oversized_file_is_skipped_silently_with_no_count_exposed(tmp_path, monkeypatch):
    # Documents current (accepted) behavior: an oversized file is excluded
    # like a binary/unreadable one, with no skip-count surfaced anywhere in
    # the result. Not a bug — just locking in what the description already
    # promises ("automatic ... oversized-file skipping") so a future change
    # to add visibility here is a deliberate decision, not a silent regression.
    import agent.tools.search_files.search_files as sf_module
    monkeypatch.setattr(sf_module, "MAX_FILE_BYTES", 10)

    _write(tmp_path, "huge.txt", "TARGET " * 20)
    _write(tmp_path, "small.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert _matches(result)[0]["file"] == "small.txt"
    assert "skipped" not in str(result.result).lower()


def test_utf8_bom_does_not_break_line_start_anchored_patterns(tmp_path):
    # A UTF-8 BOM (common in Windows-authored files) would decode as a
    # literal U+FEFF character before line 1 under plain "utf-8", silently
    # breaking any pattern anchored to the start of the line. Matches
    # read.py's choice of "utf-8-sig" for the same reason.
    path = tmp_path / "bom.py"
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write("import os\n".encode("utf-8"))

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "^import"})
    assert result.status == "success"
    assert result.result["match_count"] == 1


def test_crlf_line_endings_do_not_leak_into_matches_or_break_dollar_anchors(tmp_path):
    # content.split("\n") alone leaves a trailing \r on every line of a
    # Windows-authored (CRLF) file — breaking $-anchored patterns and leaving
    # an invisible stray character in the returned match text.
    with open(tmp_path / "windows.txt", "wb") as f:
        f.write(b"hello world\r\nfoo\r\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "world$"})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert _matches(result)[0]["match"] == "hello world"


def test_skips_conventional_ignored_directories(tmp_path):
    _write(tmp_path, ".git/config", "TARGET\n")
    _write(tmp_path, "node_modules/pkg/index.js", "TARGET\n")
    _write(tmp_path, "src/app.py", "TARGET\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"src/app.py"}
    # match_count alone can't distinguish "genuinely nothing in the skipped
    # dirs" from "matches were there but pruned" — the notice makes that
    # ambiguity visible instead of silent.
    assert "excluded" in result.result["notice"]


def test_zero_matches_because_the_only_hit_was_in_a_pruned_directory(tmp_path):
    # The exact scenario the notice exists for: match_count == 0 here is not
    # "genuinely nothing" — it's "the only match was inside node_modules and
    # got pruned" — and only the notice tells those two cases apart.
    _write(tmp_path, "node_modules/pkg/index.js", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 0
    assert "excluded" in result.result["notice"]


def test_no_skip_list_notice_when_nothing_was_pruned(tmp_path):
    _write(tmp_path, "src/app.py", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert "notice" not in result.result


# --- path resolution (matches read/ls convention) ----------------------

def test_relative_path_resolves_under_workspace_cwd(tmp_path):
    _write(tmp_path, "sub/deep.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "path": "sub"})
    assert result.status == "success"
    assert _matches(result)[0]["file"] == "deep.txt"


def test_absolute_path_outside_workspace_is_honored(tmp_path, tmp_path_factory):
    # Matches the existing read/ls convention: absolute paths are allowed
    # to point outside the configured workspace `cwd`. Uses tmp_path_factory
    # (not tmp_path.parent, which is a shared base dir other tests may also
    # touch) so this stays isolated under parallel test execution.
    outside = tmp_path_factory.mktemp("search_files_outside")
    (outside / "f.txt").write_text("TARGET\n", encoding="utf-8")

    tool = _make_tool(tmp_path / "unrelated_workspace")
    (tmp_path / "unrelated_workspace").mkdir()
    result = tool.execute({"pattern": "TARGET", "path": str(outside)})
    assert result.status == "success"
    assert _matches(result)[0]["file"] == "f.txt"
