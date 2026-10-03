# encoding:utf-8
"""
Regression tests for the Read tool's offset/limit argument types.

Both are declared integers in the tool schema, but models routinely send them
as JSON strings (``"offset": "2"``). ``path`` is normalised on the way in, these
two never were: they went straight into comparisons and arithmetic, so the
call came back as a raw Python error instead of a read::

    {"offset": "2"}  -> Error reading file: '<' not supported between instances of 'str' and 'int'
    {"limit": "3"}   -> Error reading file: unsupported operand type(s) for +: 'int' and 'str'

Both spellings are ordinary model output and should read like the integers
they mean; anything genuinely non-numeric should be refused with a message the
model can act on.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.read.read import Read


class TestReadNumericArgs(unittest.TestCase):
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

    def test_string_offset_reads_the_same_lines_as_the_integer(self):
        as_string = self.tool.execute({"path": self.path, "offset": "4"})
        self.assertEqual(as_string.status, "success", as_string.result)
        self.assertTrue(as_string.result["content"].startswith("4|line4\n5|line5"))
        self.assertEqual(as_string.result["start_line"], 4)

        as_int = self.tool.execute({"path": self.path, "offset": 4})
        self.assertEqual(as_string.result["content"], as_int.result["content"])

    def test_string_limit_bounds_the_read_and_still_hints(self):
        result = self.tool.execute({"path": self.path, "limit": "3"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "1|line1\n2|line2\n3|line3")
        self.assertEqual(result.result["output_lines"], 3)
        self.assertIn("9 more lines in file", self._content(result))
        self.assertIn("Use offset=4 to continue", self._content(result))

    def test_both_arguments_as_strings(self):
        result = self.tool.execute({"path": self.path, "offset": "2", "limit": "2"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "2|line2\n3|line3")
        self.assertEqual(result.result["start_line"], 2)
        self.assertEqual(result.result["output_lines"], 2)

    def test_negative_string_offset_still_reads_from_the_end(self):
        result = self.tool.execute({"path": self.path, "offset": "-2"})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"], "11|line11\n12|line12")

    def test_padded_and_float_spellings_are_accepted(self):
        for spelling in (" 4 ", "4.0", "+4"):
            with self.subTest(spelling=spelling):
                result = self.tool.execute({"path": self.path, "offset": spelling})
                self.assertEqual(result.status, "success", result.result)
                self.assertEqual(result.result["start_line"], 4)

    def test_zero_as_a_string_is_still_refused_as_a_limit(self):
        # Coercion runs before the limit check, so the string spelling reaches
        # the same plain error the integer one does.
        result = self.tool.execute({"path": self.path, "limit": "0"})
        self.assertEqual(result.status, "error", result.result)
        self.assertIn("limit must be a positive number of lines", self._content(result))

    def test_non_numeric_offset_is_refused_with_a_readable_message(self):
        result = self.tool.execute({"path": self.path, "offset": "second"})
        self.assertEqual(result.status, "error", result.result)
        message = self._content(result)
        self.assertIn("offset", message)
        self.assertIn("second", message)
        self.assertNotIn("Error reading file:", message)
        self.assertNotIn("not supported between instances", message)
        self.assertNotIn("Traceback", message)

    def test_non_numeric_limit_is_refused_with_a_readable_message(self):
        result = self.tool.execute({"path": self.path, "limit": "ten"})
        self.assertEqual(result.status, "error", result.result)
        message = self._content(result)
        self.assertIn("limit", message)
        self.assertIn("ten", message)
        self.assertNotIn("unsupported operand type", message)

    def test_fractional_and_structured_values_are_refused(self):
        cases = [
            ({"offset": "1.5"}, "offset"),
            ({"limit": [1, 2]}, "limit"),
            ({"offset": {"line": 3}}, "offset"),
            ({"limit": True}, None),
        ]
        for args, name in cases:
            with self.subTest(args=args):
                result = self.tool.execute(dict({"path": self.path}, **args))
                self.assertEqual(result.status, "error", result.result)
                self.assertNotIn("Error reading file:", self._content(result))
                if name:
                    self.assertIn(name, self._content(result))

    def test_integer_arguments_are_untouched(self):
        result = self.tool.execute({"path": self.path, "offset": 10, "limit": 2})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["content"].split("\n\n")[0], "10|line10\n11|line11")

    def test_absent_arguments_are_untouched(self):
        result = self.tool.execute({"path": self.path})
        self.assertEqual(result.status, "success", result.result)
        self.assertEqual(result.result["total_lines"], 12)

    def test_a_missing_path_is_still_reported_before_the_arguments(self):
        result = self.tool.execute({"limit": "3"})
        self.assertEqual(result.status, "error", result.result)
        self.assertIn("path parameter is required", self._content(result))

    def test_a_missing_file_is_still_reported_before_a_bad_argument(self):
        result = self.tool.execute({"path": os.path.join(self.work, "nope.txt"), "limit": "3"})
        self.assertEqual(result.status, "error", result.result)
        self.assertIn("File not found", self._content(result))


if __name__ == "__main__":
    unittest.main()
