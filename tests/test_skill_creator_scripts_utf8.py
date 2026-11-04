# encoding:utf-8
"""The skill-creator scripts read and write skill files as UTF-8.

The agent runs ``init_skill.py`` and ``quick_validate.py`` with whatever Python
is on the user's PATH. Without an encoding, ``Path.write_text`` and
``Path.read_text`` use the locale encoding, which on Windows is the ANSI code
page unless Python runs in UTF-8 mode (the default only from Python 3.15).
With cp1252, the arrows in the SKILL.md template can't be encoded, so
``init_skill.py`` stopped after writing an empty SKILL.md. With cp936 (Chinese
Windows), the template was written as GBK, which the skill loader and the read
and edit tools can't decode. ``quick_validate.py``, and ``package_skill.py``
through it, read a UTF-8 SKILL.md the same way and crashed on the Chinese
description below.

The scripts run here with UTF-8 mode and C-locale coercion off, so Windows
keeps its ANSI code page, and on Linux and macOS ``LC_ALL=C`` makes the locale
encoding ASCII.
"""

import codecs
import os
import subprocess
import sys

from agent.skills.loader import SkillLoader

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "skill-creator", "scripts",
)

CHINESE_SKILL_MD = "---\nname: weather-api\ndescription: 根据城市名查询天气\n---\n\n# Weather API\n"


def run(script, *args):
    env = dict(
        os.environ,
        PYTHONUTF8="0",
        PYTHONCOERCECLOCALE="0",
        LC_ALL="C",
        LANG="C",
        # As the bash tool sets it on Windows: the scripts print emoji.
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *args],
        capture_output=True, encoding="utf-8", env=env, timeout=120,
    )


def chinese_skill(tmp_path, bom=b""):
    skill_dir = tmp_path / "weather-api"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(bom + CHINESE_SKILL_MD.encode("utf-8"))
    return skill_dir


def test_init_skill_writes_a_utf8_skill_the_loader_reads(tmp_path):
    proc = run("init_skill.py", "weather-api", "--path", str(tmp_path))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    skill_dir = tmp_path / "weather-api"
    assert "→" in (skill_dir / "SKILL.md").read_bytes().decode("utf-8")
    for name in ("scripts/example.py", "references/api_reference.md", "assets/example_asset.txt"):
        assert (skill_dir / name).is_file(), name
    result = SkillLoader().load_skills_from_dir(str(tmp_path), source="custom")
    assert [skill.name for skill in result.skills] == ["weather-api"]
    assert not [d for d in result.diagnostics if "Failed to read" in d]


def test_quick_validate_reads_a_chinese_description(tmp_path):
    proc = run("quick_validate.py", str(chinese_skill(tmp_path)))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "Skill is valid!"


def test_quick_validate_accepts_a_bom_as_the_loader_does(tmp_path):
    proc = run("quick_validate.py", str(chinese_skill(tmp_path, bom=codecs.BOM_UTF8)))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "Skill is valid!"


def test_package_skill_validates_a_chinese_description(tmp_path):
    proc = run("package_skill.py", str(chinese_skill(tmp_path)), str(tmp_path / "dist"))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "dist" / "weather-api.skill").is_file()
