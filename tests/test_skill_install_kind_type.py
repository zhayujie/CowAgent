# encoding:utf-8
"""
One malformed ``kind:`` in a skill file must not take the whole skill library
down with it.

``install:`` entries come from a hand-written SKILL.md, so ``kind:`` with
nothing after it parses as None. Calling ``.lower()`` on that raised before the
loop's own ``if not kind: continue`` could skip the entry, and because the parse
happens while every skill is being built, the failure cost the user *every*
skill rather than the one bad file. ``kind: 1`` reached the same line.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.skills.frontmatter import parse_metadata
from agent.skills.loader import SkillLoader


def _skill(root: Path, name: str, install_block: str = "") -> Path:
    """Write one SKILL.md, optionally with a metadata.install block."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = f"name: {name}\ndescription: A normal skill."
    if install_block:
        frontmatter += f"\nmetadata:\n  cowagent:\n{install_block}"
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8"
    )
    return skill_dir


class TestSkillInstallKind(unittest.TestCase):
    """A non-string or absent kind is an entry to skip, not a parse failure."""

    def _metadata(self, install_yaml: str):
        import yaml

        return parse_metadata(
            yaml.safe_load("metadata:\n  cowagent:\n    install:\n" + install_yaml)
        )

    def test_an_empty_kind_is_skipped(self):
        # `kind:` with nothing after it is the shape this has to survive.
        meta = self._metadata("      - kind:\n")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.install, [])

    def test_a_non_string_kind_is_skipped(self):
        for raw in ("      - kind: 1\n", "      - kind: 3.5\n", "      - kind: [a]\n"):
            with self.subTest(kind=raw.strip()):
                meta = self._metadata(raw)
                self.assertIsNotNone(meta)
                self.assertEqual(meta.install, [])

    def test_a_real_kind_still_parses(self):
        meta = self._metadata("      - kind: npm\n        id: left-pad\n")
        self.assertEqual(len(meta.install), 1)
        self.assertEqual(meta.install[0].kind, "npm")
        self.assertEqual(meta.install[0].id, "left-pad")

    def test_type_is_still_accepted_as_the_spelling_of_kind(self):
        meta = self._metadata("      - type: git\n")
        self.assertEqual(len(meta.install), 1)
        self.assertEqual(meta.install[0].kind, "git")

    def test_a_kind_is_lower_cased_and_trimmed(self):
        # What the original `.lower()` was there for.
        meta = self._metadata("      - kind: '  NPM  '\n")
        self.assertEqual(meta.install[0].kind, "npm")

    def test_one_bad_entry_does_not_cost_the_other_skills(self):
        root = Path(tempfile.mkdtemp(prefix="skills-kind-"))
        _skill(root, "good-one")
        _skill(root, "good-two")
        _skill(root, "bad-one", "    install:\n      - kind:\n")

        entries = SkillLoader().load_all_skills(custom_dir=str(root))

        loaded = {getattr(e, "skill", e).name for e in entries.values()}
        self.assertIn("good-one", loaded)
        self.assertIn("good-two", loaded)


if __name__ == "__main__":
    unittest.main()