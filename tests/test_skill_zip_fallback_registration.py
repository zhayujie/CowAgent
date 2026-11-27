"""A zip that is not shaped like a skill bundle must still be reported.

`_install_zip_bytes` documents three scenarios, the third being "treat the entire
archive as a single skill named `name`". The tar.gz builder implements exactly
that and then registers the result; the zip builder copied the directory and
returned, so the caller was told nothing happened while the files were already on
disk, and `skills_config.json` never learned about them.
"""
import io
import json
import os
import zipfile

import pytest

from cli.commands import skill as skill_cmd


def _zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buffer.getvalue()


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    target = tmp_path / "skills"
    target.mkdir()
    monkeypatch.setattr(skill_cmd, "get_skills_dir", lambda agent_id=None: str(target))
    return target


def _config(skills_dir):
    path = skills_dir / "skills_config.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_unshaped_bundle_is_still_registered_and_reported(skills_dir):
    result = skill_cmd.InstallResult()

    skill_cmd._install_zip_bytes(
        _zip_bytes({"notes.txt": "just some files"}),
        "bundle", str(skills_dir), result=result, source_label="url",
    )

    assert result.installed == ["bundle"], "the caller was told nothing was installed"
    assert any("Installed" in m for m in result.messages)
    assert _config(skills_dir).get("bundle", {}).get("source") == "url"


def test_the_bundle_contents_are_still_written(skills_dir):
    """Control: the copy itself already worked and must keep working."""
    skill_cmd._install_zip_bytes(
        _zip_bytes({"notes.txt": "just some files"}),
        "bundle", str(skills_dir), result=skill_cmd.InstallResult(), source_label="url",
    )

    assert (skills_dir / "bundle" / "notes.txt").read_text(encoding="utf-8") == "just some files"


def test_a_single_skill_at_the_root_is_unaffected(skills_dir):
    """Control: scenario 1 keeps naming the skill after its SKILL.md."""
    result = skill_cmd.InstallResult()

    skill_cmd._install_zip_bytes(
        _zip_bytes({"SKILL.md": "---\nname: greeter\ndescription: d\n---\n\nbody\n"}),
        "downloaded", str(skills_dir), result=result, source_label="url",
    )

    assert result.installed == ["greeter"]
    assert _config(skills_dir).get("greeter", {}).get("source") == "url"


def test_a_single_skill_in_a_wrapper_dir_is_unaffected(skills_dir):
    """Control: scenario 2's single-child case."""
    result = skill_cmd.InstallResult()

    skill_cmd._install_zip_bytes(
        _zip_bytes({"pkg/SKILL.md": "---\nname: wrapped\ndescription: d\n---\n\nbody\n"}),
        "downloaded", str(skills_dir), result=result, source_label="url",
    )

    assert result.installed == ["wrapped"]


def test_a_missing_result_still_installs(skills_dir):
    """Control: `result=None` callers (staging) must not break."""
    skill_cmd._install_zip_bytes(
        _zip_bytes({"notes.txt": "x"}), "bundle", str(skills_dir),
    )

    assert os.path.isdir(str(skills_dir / "bundle"))
    assert _config(skills_dir).get("bundle", {}).get("source") == "zip"
