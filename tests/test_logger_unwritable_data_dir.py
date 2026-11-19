"""An unavailable log directory must leave console logging operational."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permission bits")
def test_uncreatable_data_directory_falls_back_to_console(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    parent.chmod(0o555)
    data = parent / "data"
    env = {**os.environ, "COW_DATA_DIR": str(data), "HOME": str(tmp_path)}
    script = "from common.log import logger; logger.info('console-remains-usable')"
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=Path(__file__).resolve().parents[1], env=env,
            capture_output=True, text=True, timeout=10,
        )
    finally:
        parent.chmod(0o755)
    assert result.returncode == 0, result.stderr
    assert "file logging disabled" in result.stdout
    assert "console-remains-usable" in result.stdout
    assert not data.exists()
