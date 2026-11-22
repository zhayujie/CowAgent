"""Copy the agent kernel sources the mobile app embeds into one directory.

    python bundle.py <dest>

The mobile builds run this and package <dest> as the app's Python code. The
kernel is the same code a server or the desktop app runs; COW_DEPLOYMENT=mobile
selects its mobile behavior at runtime. <dest> is replaced on every run so
deleted files never linger in the app.
"""

import json
import os
import shutil
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

PACKAGES = ["agent", "bridge", "channel", "cli", "common", "models", "translate", "voice", "skills"]
FILES = ["app.py", "config.py", "config-template.json"]
# The plugin framework, and of the plugins only the one behind the chat's slash commands.
PLUGIN_FILES = ["__init__.py", "event.py", "plugin.py", "plugin_manager.py"]
PLUGIN_DIRS = ["cow_cli"]
PLUGINS_JSON = {"plugins": {"cow_cli": {"enabled": True, "priority": 1000}}}

# The mobile app ships its own UI, so the web console's static assets stay out.
SKIP_DIRS = {"__pycache__", "tests", "node_modules", ".pytest_cache"}
SKIP_PATHS = {os.path.join("channel", "web", "static")}
SKIP_SUFFIXES = (".pyc", ".pyo", ".DS_Store")


def _ignore(root: str):
    def ignore(directory, names):
        rel = os.path.relpath(directory, root)
        skipped = []
        for name in names:
            path = os.path.normpath(os.path.join(rel, name))
            if name in SKIP_DIRS or path in SKIP_PATHS or name.endswith(SKIP_SUFFIXES):
                skipped.append(name)
        return skipped
    return ignore


def bundle(dest: str) -> None:
    dest = os.path.abspath(dest)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for pkg in PACKAGES:
        shutil.copytree(os.path.join(REPO, pkg), os.path.join(dest, pkg), ignore=_ignore(REPO))
    for name in FILES:
        shutil.copy2(os.path.join(REPO, name), os.path.join(dest, name))
    os.makedirs(os.path.join(dest, "plugins"))
    for name in PLUGIN_FILES:
        shutil.copy2(os.path.join(REPO, "plugins", name), os.path.join(dest, "plugins", name))
    for name in PLUGIN_DIRS:
        shutil.copytree(os.path.join(REPO, "plugins", name), os.path.join(dest, "plugins", name), ignore=_ignore(REPO))
    with open(os.path.join(dest, "plugins", "plugins.json"), "w", encoding="utf-8") as f:
        json.dump(PLUGINS_JSON, f, indent=4)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    bundle(sys.argv[1])
