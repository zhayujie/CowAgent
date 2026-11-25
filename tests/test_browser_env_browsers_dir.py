# encoding:utf-8
"""The dir the capability probe reads is the dir Playwright launches from.

The Docker image presets PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright and bakes
Chromium in there, while the code pins ~/.cow/ms-playwright when the env var is
absent. When an explicit env var is set it has to win everywhere, otherwise
has_downloaded_chromium() reports the bundled Chromium missing even though the
launcher -- which honours the env var -- finds it and would run fine.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.browser import browser_env


def test_explicit_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path / "data"))

    assert browser_env.browsers_download_dir() == str(tmp_path)


def test_default_pins_under_data_root(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))

    assert browser_env.browsers_download_dir() == os.path.join(str(tmp_path), "ms-playwright")


def test_has_downloaded_chromium_follows_env_var(monkeypatch, tmp_path):
    browsers = tmp_path / "browsers"
    (browsers / "chromium-1169").mkdir(parents=True)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    # Point the ~/.cow default somewhere empty: the probe must not look there.
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path / "empty-data"))

    assert browser_env.has_downloaded_chromium() is True


def test_default_ignores_working_directory(monkeypatch, tmp_path):
    # `cow install-browser` may run from any directory while the service runs
    # from the project root; both must resolve the same download dir.
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.chdir(tmp_path)

    assert browser_env.browsers_download_dir() == os.path.join(project_root, "ms-playwright")
