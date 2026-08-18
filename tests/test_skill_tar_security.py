"""Security regression tests for installing skills from tar archives."""

import io
import tarfile
from unittest.mock import patch

import pytest

from cli.commands.skill import InstallResult, SkillInstallError, _install_targz_bytes


def _tar_bytes(*members):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for info, content in members:
            if content is not None:
                info.size = len(content)
            archive.addfile(info, io.BytesIO(content) if content is not None else None)
    return payload.getvalue()


def test_tar_rejects_path_with_matching_directory_prefix(tmp_path):
    entry = tarfile.TarInfo("../extracted-evil/pwned.txt")
    content = _tar_bytes((entry, b"outside extraction root"))

    with pytest.raises(SkillInstallError, match="path traversal"):
        _install_targz_bytes(
            content, "unsafe-skill", str(tmp_path / "skills"), InstallResult()
        )


def test_tar_rejects_symbolic_links(tmp_path):
    skill_file = tarfile.TarInfo("unsafe-skill/SKILL.md")
    link = tarfile.TarInfo("unsafe-skill/host-file")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    content = _tar_bytes((skill_file, b"---\nname: unsafe-skill\n---\n"), (link, None))

    with pytest.raises(SkillInstallError, match="link"):
        _install_targz_bytes(
            content, "unsafe-skill", str(tmp_path / "skills"), InstallResult()
        )


def test_tar_rejects_hard_links(tmp_path):
    skill_file = tarfile.TarInfo("unsafe-skill/SKILL.md")
    link = tarfile.TarInfo("unsafe-skill/duplicate")
    link.type = tarfile.LNKTYPE
    link.linkname = "unsafe-skill/SKILL.md"
    content = _tar_bytes((skill_file, b"---\nname: unsafe-skill\n---\n"), (link, None))

    with pytest.raises(SkillInstallError, match="link"):
        _install_targz_bytes(
            content, "unsafe-skill", str(tmp_path / "skills"), InstallResult()
        )


def test_tar_rejects_special_files(tmp_path):
    fifo = tarfile.TarInfo("unsafe-skill/input")
    fifo.type = tarfile.FIFOTYPE
    content = _tar_bytes((fifo, None))

    with pytest.raises(SkillInstallError, match="special file"):
        _install_targz_bytes(
            content, "unsafe-skill", str(tmp_path / "skills"), InstallResult()
        )


def test_tar_installs_regular_directory_and_file(tmp_path):
    directory = tarfile.TarInfo("safe-skill")
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o755
    skill_file = tarfile.TarInfo("safe-skill/SKILL.md")
    skill_file.mode = 0o644
    content = _tar_bytes(
        (directory, None),
        (skill_file, b"---\nname: safe-skill\ndescription: Safe fixture\n---\n"),
    )
    skills_dir = tmp_path / "skills"
    result = InstallResult()

    with patch("cli.commands.skill.get_skills_dir", return_value=str(skills_dir)):
        _install_targz_bytes(content, "safe-skill", str(skills_dir), result)

    assert result.installed == ["safe-skill"]
    assert (skills_dir / "safe-skill" / "SKILL.md").is_file()
