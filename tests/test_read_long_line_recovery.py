"""Read's oversized-line recovery command must retrieve the requested line."""
import re
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.tools.read.read import Read
from agent.tools.utils.truncate import DEFAULT_MAX_BYTES


class ReadLongLineRecoveryTests(unittest.TestCase):
    def test_recovery_reads_requested_line_and_preserves_literal_path(self):
        for name, offset in (("plain.txt", 1), ("plain.txt", 2), ("notes draft's.txt", 2), ("~/notes draft's.txt", 2)):
            with self.subTest(name=name, offset=offset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / (name[2:] if name.startswith("~/") else name)
                path.write_text("A" * (DEFAULT_MAX_BYTES + 20) + "\n" +
                                "B" * (DEFAULT_MAX_BYTES + 20) + "\n")
                with patch.dict(os.environ, {"HOME": directory, "USERPROFILE": directory}):
                    result = Read({"cwd": directory}).execute({"path": name if name.startswith("~/") else str(path), "offset": offset})
                self.assertEqual(result.status, "success", result.result)
                content = result.result["content"]
                command = re.search(r"Use bash tool to read: (.*)\]$", content).group(1)
                output = subprocess.run(command, shell=True, cwd=directory,
                                        capture_output=True, timeout=5)
                self.assertEqual(output.returncode, 0, output.stderr)
                expected = (b"A" if offset == 1 else b"B") * DEFAULT_MAX_BYTES
                self.assertEqual(output.stdout, expected)


if __name__ == "__main__":
    unittest.main()
