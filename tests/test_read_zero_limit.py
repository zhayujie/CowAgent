# encoding:utf-8
"""
Regression tests for the Read tool's handling of a non-positive ``limit``.

``limit`` is documented as "maximum number of lines to read", so a caller only
passes it to bound the amount of output. A ``limit`` of 0 produced an empty
slice, but the reader still counted itself as "user limited" and appended a
continuation hint, so ``limit=0`` answered::

    1|

    [11 more lines in file. Use offset=1 to continue.]

Following that advice - ``offset=1, limit=0`` - returned a byte-identical
string. The hint pointed at the line the read had already stopped at, so a
model that trusted it could repeat the call forever and never advance.

A negative ``limit`` was quietly wrong in the other direction: ``end_line``
went negative and ``all_lines[start:end]`` sliced from the end of the list, so
``limit=-5`` on a 12-line file happily returned 7 lines and called it a
success.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.read.read import Read

SUGGESTED_OFFSET = re.compile(r"Use offset=(\d+) to continue")


class TestReadNonPositiveLimit(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.tool = Read({"cwd": self.work})
        self.path = self._write("f.txt", "\n".join(f"line{i}" for i in range(1, 13)) + "\n")

    def _write(self, name, text):
        path = os.path.join(self.work, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    @staticmethod
    def _content(result):
        return result.result["content"] if isinstance(result.result, dict) else str(result.result)

    def _suggested_offset(self, result):
        match = SUGGESTED_OFFSET.search(self._content(result))
        return int(match.group(1)) if match else None

    def test_a_suggested_offset_must_actually_advance_the_read(self):
        """The invariant behind the bug: no hint may point at the same lines."""
        first = self.tool.execute({"path": self.path, "limit": 0})
        suggested = self._suggested_offset(first)
        self.assertIsNone(
            suggested,
            "limit=0 advertised "
            f"offset={suggested}; re-reading from it returned byte-identical "
            f"output, so the hint could never make progress: "
            f"{self._content(first)!r}",
        )

    def test_zero_limit_returns_no_content_at_all(self):
        result = self.tool.execute({"path": self.path, "limit": 0})
        self.assertEqual(result.status, "error", result.result)
        content = self._content(result)
        # Not a success with an empty body: that is indistinguishable from an
        # empty file and invites the model to keep re-asking.
        self.assertNotIn("more lines in file", content)
        self.assertNotIn("to continue", content)

    def test_zero_limit_names_the_offending_argument(self):
        result = self.tool.execute({"path": self.path, "limit": 0})
        message = self._content(result)
        self.assertIn("limit", message)
        self.assertIn("0", message)
        # Tell the model what to do instead, and that omitting limit reads on.
        self.assertIn("limit=20", message)

    def test_zero_limit_with_an_offset_is_rejected_too(self):
        result = self.tool.execute({"path": self.path, "offset": 4, "limit": 0})
        self.assertEqual(result.status, "error", result.result)
        self.assertNotIn("to continue", self._content(result))

    def test_negative_limit_is_rejected_instead_of_slicing_from_the_end(self):
        # limit=-5 used to end_line at -5, so all_lines[0:-5] returned the
        # first 7 lines of a 12-line file with a success status.
        result = self.tool.execute({"path": self.path, "limit": -5})
        self.assertEqual(result.status, "error", result.result)
        self.assertNotIn("line1|", self._content(result))

    def test_a_positive_limit_still_paginates_unchanged(self):
        result = self.tool.execute({"path": self.path, "offset": 4, "limit": 2})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "4|line4\n5|line5")
        self.assertEqual(result.result["start_line"], 4)
        self.assertEqual(result.result["output_lines"], 2)
        # The hint a normal limit is supposed to produce is untouched.
        self.assertEqual(self._suggested_offset(result), 6)
        self.assertIn("7 more lines in file", self._content(result))

    def test_a_limit_past_the_end_of_the_file_reads_to_the_end(self):
        result = self.tool.execute({"path": self.path, "offset": 10, "limit": 500})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["output_lines"], 3)
        self.assertIsNone(self._suggested_offset(result))

    def test_limit_of_one_still_returns_exactly_one_line(self):
        result = self.tool.execute({"path": self.path, "limit": 1})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "1|line1")
        self.assertEqual(self._suggested_offset(result), 2)

    def test_a_positive_limit_from_the_end_still_works(self):
        result = self.tool.execute({"path": self.path, "offset": -3, "limit": 2})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "10|line10\n11|line11")


if __name__ == "__main__":
    unittest.main()
