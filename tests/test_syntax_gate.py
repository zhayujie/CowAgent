"""
Tests for the syntax gate on write/edit.

The gate exists because the agent has no compiler or language server: without
it, a truncated or mangled write is only discovered when something later tries
to load the file. The two tiers are deliberately asymmetric and most of these
tests pin that asymmetry down - structured data blocks, source code only warns.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools.edit.edit import Edit
from agent.tools.write.write import Write
from agent.tools.utils import file_state


class _Base(unittest.TestCase):
    def setUp(self):
        file_state.reset()
        self._tmp = TemporaryDirectory()
        self.root = self._tmp.name
        self.write = Write({"cwd": self.root})
        self.edit = Edit({"cwd": self.root})

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.root, name)

    def _seed(self, name, content):
        path = self._path(name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


class TestStructuredDataBlocks(_Base):
    """JSON/YAML/TOML: half a document is never intentional, so refuse it."""

    def test_write_refuses_malformed_json(self):
        result = self.write.execute({"path": self._path("a.json"), "content": '{"a": 1,'})
        self.assertEqual(result.status, "error")
        self.assertIn("not valid JSON", str(result.result))

    def test_refused_write_does_not_touch_the_file(self):
        path = self._seed("a.json", '{"keep": true}')
        self.write.execute({"path": path, "content": '{"a": 1,'})
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"keep": True})

    def test_write_allows_valid_json(self):
        result = self.write.execute({"path": self._path("a.json"), "content": '{"a": 1}'})
        self.assertEqual(result.status, "success")

    def test_edit_refuses_an_edit_that_breaks_json(self):
        path = self._seed("a.json", '{\n  "a": 1\n}\n')
        result = self.edit.execute({"path": path, "oldText": '"a": 1', "newText": '"a": '})
        self.assertEqual(result.status, "error")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_write_refuses_malformed_yaml(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = self.write.execute({"path": self._path("a.yaml"), "content": "a: [1, 2\nb: 3\n"})
        self.assertEqual(result.status, "error")

    def test_write_refuses_malformed_toml(self):
        try:
            import tomllib  # noqa: F401
        except ImportError:
            self.skipTest("tomllib requires Python 3.11+")
        result = self.write.execute({"path": self._path("a.toml"), "content": "a = \n"})
        self.assertEqual(result.status, "error")

    def test_yaml_with_unknown_tags_is_still_accepted(self):
        # Well-formed YAML that a schema-aware loader would reject. The gate
        # judges syntax, not whether we know how to construct the value.
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = self.write.execute(
            {"path": self._path("a.yaml"), "content": "value: !CustomTag\n  k: v\n"}
        )
        self.assertEqual(result.status, "success")

    def test_already_unparseable_file_is_not_refused(self):
        # JSON with comments under a name the gate does not know: it never
        # parsed as strict JSON, so refusing the edit only locks the agent out.
        path = self._seed(".eslintrc.json", '{\n  // shared rules\n  "root": true\n}\n')
        result = self.edit.execute({"path": path, "oldText": '"root": true', "newText": '"root": false'})
        self.assertEqual(result.status, "success")


class TestJsonWithComments(_Base):
    """tsconfig.json, .vscode/*.json and devcontainer.json are JSONC: the tools
    that read them accept comments and trailing commas."""

    TSCONFIG = (
        '{\n'
        '  "$schema": "https://json.schemastore.org/tsconfig",\n'
        '  "compilerOptions": {\n'
        '    "target": "ES2022",\n'
        '\n'
        '    /* Bundler mode */\n'
        '    "moduleResolution": "bundler",\n'
        '    "paths": { "@/*": ["./src/*"] },\n'
        '  },\n'
        '  // Type-check the app sources only\n'
        '  "include": ["src"]\n'
        '}\n'
    )

    def test_edit_tsconfig_with_comments(self):
        path = self._seed("tsconfig.json", self.TSCONFIG)
        result = self.edit.execute({"path": path, "oldText": '"ES2022"', "newText": '"ES2023"'})
        self.assertEqual(result.status, "success")
        with open(path, encoding="utf-8") as f:
            self.assertIn('"ES2023"', f.read())

    def test_write_new_tsconfig_with_comments(self):
        result = self.write.execute({"path": self._path("tsconfig.app.json"), "content": self.TSCONFIG})
        self.assertEqual(result.status, "success")

    def test_vscode_settings_with_comment_and_trailing_comma(self):
        result = self.write.execute({
            "path": os.path.join(self.root, ".vscode", "settings.json"),
            "content": '{\n  "editor.formatOnSave": true, // whole workspace\n}\n',
        })
        self.assertEqual(result.status, "success")

    def test_truncated_tsconfig_is_still_refused(self):
        truncated = self.TSCONFIG.split('"paths"')[0]
        result = self.write.execute({"path": self._path("tsconfig.json"), "content": truncated})
        self.assertEqual(result.status, "error")
        self.assertIn("not valid JSON", str(result.result))

    def test_comment_is_still_refused_in_strict_json(self):
        # npm, like CowAgent loading its own config.json, rejects a comment.
        path = self._seed("package.json", '{\n  "name": "app"\n}\n')
        result = self.edit.execute(
            {"path": path, "oldText": '"name": "app"', "newText": '"name": "app" // renamed later'}
        )
        self.assertEqual(result.status, "error")


class TestHelmTemplates(_Base):
    """A Helm chart template only becomes YAML once Helm renders it."""

    DEPLOYMENT = (
        'apiVersion: apps/v1\n'
        'kind: Deployment\n'
        'metadata:\n'
        '  name: {{ include "chart.fullname" . }}\n'
        '  labels:\n'
        '    {{- include "chart.labels" . | nindent 4 }}\n'
        'spec:\n'
        '  {{- if not .Values.autoscaling.enabled }}\n'
        '  replicas: {{ .Values.replicaCount }}\n'
        '  {{- end }}\n'
        '  template:\n'
        '    spec:\n'
        '      containers:\n'
        '        - name: {{ .Chart.Name }}\n'
        '          imagePullPolicy: {{ .Values.image.pullPolicy }}\n'
    )

    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        super().setUp()

    def test_edit_helm_template(self):
        os.makedirs(self._path("templates"))
        path = self._seed(os.path.join("templates", "deployment.yaml"), self.DEPLOYMENT)
        result = self.edit.execute({
            "path": path,
            "oldText": "imagePullPolicy:",
            "newText": "terminationMessagePolicy: File\n          imagePullPolicy:",
        })
        self.assertEqual(result.status, "success")

    def test_write_new_helm_template(self):
        result = self.write.execute(
            {"path": os.path.join(self.root, "templates", "deployment.yaml"), "content": self.DEPLOYMENT}
        )
        self.assertEqual(result.status, "success")

    def test_broken_workflow_is_still_refused(self):
        # GitHub's ${{ }} and docker/metadata-action's {{is_default_branch}}
        # sit inside YAML scalars: they do not make a file a template.
        content = (
            "jobs:\n"
            "  build:\n"
            "    runs-on: ${{ matrix.os }}\n"
            "    steps:\n"
            "      - uses: docker/metadata-action@v5\n"
            "        with:\n"
            "          tags: type=raw,value=latest,enable={{is_default_branch}}\n"
            "      - run: [\n"
        )
        result = self.write.execute({"path": self._path("ci.yml"), "content": content})
        self.assertEqual(result.status, "error")


class TestSourceCodeOnlyWarns(_Base):
    """Code can legitimately be mid-construction, so never block on it."""

    def test_broken_python_is_written_but_flagged(self):
        path = self._path("a.py")
        result = self.write.execute({"path": path, "content": "def f(:\n"})
        self.assertEqual(result.status, "success")
        self.assertIn("syntax error", result.result["warning"])
        self.assertTrue(os.path.exists(path))

    def test_valid_python_says_nothing(self):
        result = self.write.execute({"path": self._path("a.py"), "content": "def f():\n    pass\n"})
        self.assertEqual(result.status, "success")
        self.assertNotIn("warning", result.result)

    def test_edit_that_breaks_python_warns(self):
        path = self._seed("a.py", "def f():\n    return 1\n")
        result = self.edit.execute({"path": path, "oldText": "return 1", "newText": "return ("})
        self.assertEqual(result.status, "success")
        self.assertIn("syntax error", result.result["warning"])

    def test_already_broken_file_stays_quiet(self):
        # Only *newly introduced* breakage is worth a word; otherwise every
        # step of a multi-edit repair would nag about damage it did not cause.
        path = self._seed("a.py", "def f(:\n    return 1\n")
        result = self.edit.execute({"path": path, "oldText": "return 1", "newText": "return 2"})
        self.assertEqual(result.status, "success")
        self.assertNotIn("warning", result.result)


class TestUncheckedTypes(_Base):
    def test_arbitrary_text_is_untouched_by_the_gate(self):
        result = self.write.execute({"path": self._path("a.md"), "content": "# hi {[(\n"})
        self.assertEqual(result.status, "success")
        self.assertNotIn("warning", result.result)


if __name__ == "__main__":
    unittest.main()
