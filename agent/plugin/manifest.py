"""Plugin manifest: ``plugin.yaml`` (or ``plugin.json``) at the plugin root."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_FILES = ("plugin.yaml", "plugin.yml", "plugin.json")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Permissions a plugin may declare. Shown to the owner before enabling, and
# read by the kernel: write-class permissions make the plugin's tools count as
# state-changing under the read-only permission mode, and modify hooks are
# refused unless ``hook.modify`` is declared.
KNOWN_PERMISSIONS = frozenset({
    "network",      # talks to remote services
    "fs.read",      # reads files outside its own directory
    "fs.write",     # writes files outside its own data directory
    "shell",        # runs commands or subprocesses
    "send",         # sends messages on the owner's behalf
    "hook.modify",  # rewrites messages, tool results or replies
})
WRITE_PERMISSIONS = frozenset({"fs.write", "shell", "send"})


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    id: str
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    entry: str = ""
    permissions: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)
    default_enabled: bool = False

    @property
    def title(self) -> str:
        return self.name or self.id

    @property
    def writes(self) -> bool:
        return bool(WRITE_PERMISSIONS.intersection(self.permissions))

    def config_defaults(self) -> Dict[str, Any]:
        """Declared config keys with their defaults.

        A key maps either to a plain default value or to a dict carrying
        ``default`` (plus descriptive fields such as ``title``).
        """
        out = {}
        for key, spec in self.config.items():
            if isinstance(spec, dict) and ("default" in spec or "title" in spec or "type" in spec):
                out[key] = spec.get("default")
            else:
                out[key] = spec
        return out


def find_manifest(plugin_dir: Path) -> Optional[Path]:
    for name in MANIFEST_FILES:
        path = plugin_dir / name
        if path.is_file():
            return path
    return None


def load_manifest(plugin_dir: Path) -> Manifest:
    path = find_manifest(plugin_dir)
    if path is None:
        raise ManifestError(f"no plugin.yaml in {plugin_dir}")
    try:
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix == ".json":
            data = json.loads(text)
        else:
            import yaml
            data = yaml.safe_load(text)
    except Exception as e:
        raise ManifestError(f"cannot parse {path.name}: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name} must be a mapping")

    plugin_id = str(data.get("id") or plugin_dir.name).strip().lower()
    if not ID_RE.match(plugin_id):
        raise ManifestError(
            f"invalid plugin id {plugin_id!r}: use lowercase letters, digits, '-' or '_'"
        )

    def _list(key) -> List[str]:
        value = data.get(key) or []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ManifestError(f"'{key}' must be a list")
        return [str(v).strip() for v in value if str(v).strip()]

    config = data.get("config") or {}
    if not isinstance(config, dict):
        raise ManifestError("'config' must be a mapping")

    return Manifest(
        id=plugin_id,
        name=str(data.get("name") or ""),
        version=str(data.get("version") or "0.0.0"),
        description=str(data.get("description") or ""),
        author=str(data.get("author") or ""),
        entry=str(data.get("entry") or ""),
        permissions=_list("permissions"),
        config=config,
        requires=_list("requires"),
        default_enabled=bool(data.get("default_enabled", False)),
    )
