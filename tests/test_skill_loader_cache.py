# encoding:utf-8
"""
The system prompt is rebuilt before every run, reloading every skill. Unchanged
skill files are served from a parse cache, which must never serve a stale skill.
"""
import builtins
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.skills import loader as loader_mod
from agent.skills.manager import SKILLS_CONFIG_FILE, SkillManager


def _write_skill(root: Path, name: str, description: str, body: str = "body"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n"
        f"metadata:\n  tags: [a]\n---\n{body}\n",
        encoding="utf-8",
    )


class TestSkillLoaderCache(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.builtin = self.tmp / "builtin"
        self.custom = self.tmp / "custom"
        self.builtin.mkdir()
        self.custom.mkdir()
        _write_skill(self.custom, "alpha", "first")
        _write_skill(self.custom, "beta", "second")
        loader_mod._parse_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        loader_mod._parse_cache.clear()

    def _manager(self) -> SkillManager:
        return SkillManager(builtin_dir=str(self.builtin), custom_dir=str(self.custom))

    def _skill_opens(self, fn):
        opened = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            if str(file).endswith("SKILL.md"):
                opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with unittest.mock.patch("builtins.open", counting_open):
            fn()
        return opened

    # -- the cache is used ---------------------------------------------

    def test_unchanged_skills_are_not_reread(self):
        manager = self._manager()
        opened = self._skill_opens(lambda: manager.refresh_skills(use_cache=True))
        self.assertEqual(opened, [])
        self.assertEqual(sorted(manager.skills), ["alpha", "beta"])

    def test_explicit_refresh_still_reads_from_disk(self):
        manager = self._manager()
        opened = self._skill_opens(manager.refresh_skills)
        self.assertEqual(len(opened), 2)

    # -- ...but never serves a stale skill ------------------------------

    def test_edited_skill_is_picked_up(self):
        manager = self._manager()
        _write_skill(self.custom, "alpha", "FIRST")  # same size as before
        manager.refresh_skills(use_cache=True)
        self.assertEqual(manager.skills["alpha"].skill.description, "FIRST")

    def test_edit_that_keeps_mtime_and_size_is_picked_up(self):
        manager = self._manager()
        path = self.custom / "alpha" / "SKILL.md"
        st = path.stat()
        time.sleep(0.01)
        _write_skill(self.custom, "alpha", "FIRST")
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(path.stat().st_mtime_ns, st.st_mtime_ns)
        manager.refresh_skills(use_cache=True)
        self.assertEqual(manager.skills["alpha"].skill.description, "FIRST")

    def test_added_and_removed_skills_are_picked_up(self):
        manager = self._manager()
        _write_skill(self.custom, "gamma", "third")
        shutil.rmtree(self.custom / "beta")
        manager.refresh_skills(use_cache=True)
        self.assertEqual(sorted(manager.skills), ["alpha", "gamma"])

    def test_skill_replaced_by_rename_is_picked_up(self):
        manager = self._manager()
        staged = self.tmp / "staged"
        _write_skill(staged, "alpha", "renamed-in")
        os.replace(staged / "alpha" / "SKILL.md", self.custom / "alpha" / "SKILL.md")
        manager.refresh_skills(use_cache=True)
        self.assertEqual(manager.skills["alpha"].skill.description, "renamed-in")

    def test_rollback_that_restores_the_old_mtime_is_picked_up(self):
        """Evolution rolls back with shutil.copy2, which restores the backup's
        mtime onto the same inode."""
        backup = self.tmp / "alpha.bak"
        shutil.copy2(self.custom / "alpha" / "SKILL.md", backup)
        manager = self._manager()
        time.sleep(0.01)
        _write_skill(self.custom, "alpha", "evolved")
        manager.refresh_skills(use_cache=True)
        self.assertEqual(manager.skills["alpha"].skill.description, "evolved")

        shutil.copy2(backup, self.custom / "alpha" / "SKILL.md")
        manager.refresh_skills(use_cache=True)
        self.assertEqual(manager.skills["alpha"].skill.description, "first")

    def test_entry_expires_even_when_the_metadata_never_changes(self):
        """Metadata can miss a write (a network filesystem's attribute cache);
        the TTL bounds how long such a stale skill can be served."""
        clock = [1000.0]
        frozen = lambda path: ("same",)  # noqa: E731
        with unittest.mock.patch.object(loader_mod, "_file_signature", frozen), \
                unittest.mock.patch.object(loader_mod.time, "monotonic", lambda: clock[0]):
            manager = self._manager()
            _write_skill(self.custom, "alpha", "changed")

            clock[0] += loader_mod._PARSE_CACHE_TTL - 1
            manager.refresh_skills(use_cache=True)
            self.assertEqual(manager.skills["alpha"].skill.description, "first")

            clock[0] += 2
            manager.refresh_skills(use_cache=True)
            self.assertEqual(manager.skills["alpha"].skill.description, "changed")

    def test_cache_size_is_bounded(self):
        with unittest.mock.patch.object(loader_mod, "_PARSE_CACHE_MAX_ENTRIES", 1):
            self._manager()
        self.assertLessEqual(len(loader_mod._parse_cache), 1)

    def test_managers_do_not_share_mutable_frontmatter(self):
        first = self._manager()
        first.skills["alpha"].skill.frontmatter["metadata"]["tags"].append("mutated")
        second = self._manager()
        self.assertEqual(second.skills["alpha"].skill.frontmatter["metadata"]["tags"], ["a"])

    # -- skills_config.json --------------------------------------------

    def _config_path(self) -> Path:
        return self.custom / SKILLS_CONFIG_FILE

    def test_config_is_not_rewritten_when_nothing_changed(self):
        manager = self._manager()
        with unittest.mock.patch.object(SkillManager, "_save_skills_config") as save:
            manager.refresh_skills(use_cache=True)
        save.assert_not_called()

    def test_config_is_rewritten_when_a_skill_is_added(self):
        manager = self._manager()
        _write_skill(self.custom, "gamma", "third")
        manager.refresh_skills(use_cache=True)
        saved = json.loads(self._config_path().read_text(encoding="utf-8"))
        self.assertIn("gamma", saved)

    def test_disabled_skill_stays_disabled(self):
        manager = self._manager()
        manager.set_skill_enabled("alpha", False)
        for _ in range(3):
            manager.refresh_skills(use_cache=True)
        self.assertFalse(self._manager().is_skill_enabled("alpha"))

    def test_unreadable_config_is_not_overwritten_with_defaults(self):
        manager = self._manager()
        manager.set_skill_enabled("alpha", False)
        self._config_path().write_text('{"alpha": {"enab', encoding="utf-8")

        manager.refresh_skills(use_cache=True)

        self.assertEqual(self._config_path().read_text(encoding="utf-8"), '{"alpha": {"enab')
        self.assertFalse(manager.is_skill_enabled("alpha"))

    def test_config_write_leaves_no_temporary_file(self):
        manager = self._manager()
        manager.set_skill_enabled("beta", False)
        leftovers = [p.name for p in self.custom.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
