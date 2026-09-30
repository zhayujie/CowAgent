"""Deep Dream rewrites the user's only copy of MEMORY.md and of today's diary.

A write that fails part-way through used to leave a truncated file behind, and
the previous content was gone for good -- nothing keeps a copy of it. These
regressions interrupt the write and check that the old content survives.
"""

import io
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory.summarizer import MemoryFlushManager

OLD_MEMORY = "- the user prefers concise answers\n- the user maintains CowAgent\n"
LLM_REPLY = (
    "[MEMORY]\n- a freshly distilled fact\n\n[DREAM]\nI dreamed about truncation\n"
)


class _StubModel:
    """Returns the shape ``_extract_response_text`` accepts (OpenAI format)."""

    def __init__(self, content: str = LLM_REPLY):
        self.content = content
        self.requests = []

    def call(self, request):
        self.requests.append(request)
        return {"choices": [{"message": {"content": self.content}}]}


class _TruncatingHandle:
    """File handle that writes half the payload and then fails, like ENOSPC."""

    def __init__(self, handle):
        self._handle = handle

    def write(self, text):
        self._handle.write(text[: max(len(text) // 2, 1)])
        raise OSError(28, "No space left on device")

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._handle.__exit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._handle, name)


@pytest.fixture
def workspace(tmp_path):
    """A workspace that already holds a MEMORY.md and one daily record."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "MEMORY.md").write_text(OLD_MEMORY, encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    (tmp_path / "memory" / f"{today}.md").write_text(
        "- something happened\n", encoding="utf-8"
    )
    return tmp_path


def _break_writes(monkeypatch, root):
    """Make every write-mode open() of a ``*.md`` under *root* fail half-way.

    Both ``builtins.open`` (what this module calls) and ``io.open`` (what
    ``Path.write_text`` calls) are covered, so the same sabotage reaches either
    shape of write.
    """
    real_open = io.open
    root_prefix = str(Path(root).resolve())

    def fake_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if "w" in mode:
            path = Path(file)
            name = path.name
            if name.endswith(".md") or (name.endswith(".tmp") and ".md." in name):
                if str(path.resolve()).startswith(root_prefix):
                    return _TruncatingHandle(handle)
        return handle

    monkeypatch.setattr(io, "open", fake_open)
    monkeypatch.setattr("builtins.open", fake_open)


def test_an_interrupted_distillation_keeps_the_existing_memory(workspace, monkeypatch):
    manager = MemoryFlushManager(workspace, _StubModel())

    _break_writes(monkeypatch, workspace)
    assert manager.deep_dream(force=True) is False

    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == OLD_MEMORY
    assert list(workspace.glob("*.tmp")) == []


def test_an_interrupted_diary_write_keeps_the_previous_diary(workspace, monkeypatch):
    manager = MemoryFlushManager(workspace, _StubModel())
    diary = workspace / "memory" / "dreams" / f"{datetime.now():%Y-%m-%d}.md"
    diary.parent.mkdir(parents=True)
    diary.write_text("# Dream Diary: earlier run\n\nsomething older\n", encoding="utf-8")

    _break_writes(monkeypatch, workspace)
    with pytest.raises(OSError):
        manager._write_dream_diary("a newer dream")

    assert diary.read_text(encoding="utf-8").startswith("# Dream Diary: earlier run")
    assert list(diary.parent.glob("*.tmp")) == []


def test_a_successful_distillation_replaces_the_memory_and_writes_the_diary(workspace):
    manager = MemoryFlushManager(workspace, _StubModel())

    assert manager.deep_dream(force=True) is True

    memory_text = (workspace / "MEMORY.md").read_text(encoding="utf-8")
    assert "a freshly distilled fact" in memory_text
    assert OLD_MEMORY not in memory_text  # replaced, not appended
    assert "I dreamed about truncation" in (
        workspace / "memory" / "dreams" / f"{datetime.now():%Y-%m-%d}.md"
    ).read_text(encoding="utf-8")
    # the swap must not leave the sibling file behind
    assert list(workspace.glob("**/*.tmp")) == []


def test_a_reply_without_a_memory_section_leaves_the_memory_alone(workspace):
    manager = MemoryFlushManager(workspace, _StubModel("no sections here"))

    assert manager.deep_dream(force=True) is False

    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == OLD_MEMORY
