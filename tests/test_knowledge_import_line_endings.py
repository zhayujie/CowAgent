"""An imported document is saved with the line endings it was uploaded with."""
from agent.knowledge.service import KnowledgeService


class FakeStorage:
    def delete_by_path(self, path):
        pass


class FakeMemoryManager:
    def __init__(self):
        self.storage = FakeStorage()

    def mark_dirty(self):
        pass

    async def sync(self):
        pass


def test_import_keeps_the_uploaded_line_endings(tmp_path):
    notes = tmp_path / "knowledge" / "notes"
    notes.mkdir(parents=True)
    svc = KnowledgeService(str(tmp_path), FakeMemoryManager())
    # Notepad and VS Code on Windows save CRLF, and Git with autocrlf checks files out that way.
    crlf = b"# Pricing\r\n\r\n| Plan | Price |\r\n| --- | --- |\r\n| Free | 0 |\r\n| Pro | 20 |\r\n"
    lf = b"# Notes\n\nfirst line\nsecond line\n"

    result = svc.import_documents("notes", [
        {"filename": "pricing.md", "content": crlf},
        {"filename": "notes.txt", "content": lf},
    ])

    assert result["imported"] == 2
    # Saved in text mode, Windows stored each CRLF as CR CR LF, which every
    # reader shows as a blank line after each line.
    assert (notes / "pricing.md").read_bytes() == crlf
    assert (notes / "notes.md").read_bytes() == lf
    assert svc.read_file("notes/pricing.md")["content"] == (
        "# Pricing\n\n| Plan | Price |\n| --- | --- |\n| Free | 0 |\n| Pro | 20 |\n"
    )
