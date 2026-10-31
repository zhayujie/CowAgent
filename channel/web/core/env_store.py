"""Write-only credentials management, with separately persisted safe previews.

    GET paths only stat .env. Discovering existing names and previews is an
    explicit sync operation. A durable dirty marker precedes every .env edit,
    so a crash between the two file replacements cannot expose an old preview
    as current. There is deliberately no two-file transaction claim.
"""

import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from agent.tools.env_config.env_config import EnvConfig
from agent.tools.env_config.storage import env_file_lock, write_private_atomic

MASK = "••••••••"
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
PREFIXES = ("sk-admin-", "sk-proj-", "tvly-", "sk-ant-", "sk-")
# Changing the process's own home would redirect subsequent requests to a
# different credentials file. These are launch settings, not API credentials.
LAUNCH_KEYS = {"HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "COW_DATA_DIR"}


class EnvStoreError(Exception):
    def __init__(self, code, status=400):
        self.code = code
        self.status = status
        super().__init__(code)


def validate_key(key):
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise EnvStoreError("invalid_key")
    if key.upper() in LAUNCH_KEYS:
        raise EnvStoreError("launch_setting")
    return key


def mask_value(value):
    # Leave at least 12 characters hidden; never infer safety from the name.
    if not value or len(value) < 20 or not value.isascii() or not re.fullmatch(r"[A-Za-z0-9_./+=:@-]+", value):
        return MASK
    prefix = next((p for p in PREFIXES if value.startswith(p)), value[:4])
    if len(value) - len(prefix) - 4 < 12:
        return MASK
    return prefix + MASK + value[-4:]


def _safe_preview(value):
    if value == MASK:
        return value
    if not isinstance(value, str) or value.count(MASK) != 1:
        return None
    prefix, suffix = value.split(MASK)
    if (prefix in PREFIXES or re.fullmatch(r"[A-Za-z0-9_./+=:@-]{4}", prefix)) and re.fullmatch(r"[A-Za-z0-9_./+=:@-]{4}", suffix):
        return value
    return None


def _stamp(path):
    try:
        s = os.stat(path)
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    except FileNotFoundError:
        return None


def _now():
    return datetime.now(timezone.utc).isoformat()


class EnvStore:
    def __init__(self, tool=None):
        self.tool = tool if tool is not None else EnvConfig()
        self.path = Path(self.tool.env_path)
        self.metadata_path = self.path.parent / "env_metadata.json"

    def _metadata(self):
        try:
            if self.metadata_path.is_symlink() or self.metadata_path.stat().st_size > 2 * 1024 * 1024:
                return {}, "corrupt"
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("variables"), dict):
                return {}, "corrupt"
            return data, None
        except FileNotFoundError:
            return {}, "missing"
        except (OSError, ValueError, TypeError, AttributeError):
            return {}, "corrupt"

    def _save_metadata(self, data):
        write_private_atomic(self.metadata_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def list(self, query=""):
        # Never call dotenv_values, open(.env), or the tool's read method here.
        data, problem = self._metadata()
        stamp = _stamp(self.path)
        current = not problem and data.get("state") == "ready" and data.get("stamp") == stamp
        items = []
        for key, entry in sorted(data.get("variables", {}).items()):
            if not KEY_RE.fullmatch(key) or not isinstance(entry, dict):
                continue
            if query.casefold() not in key.casefold():
                continue
            items.append({
                "key": key, "preview": _safe_preview(entry.get("preview")) if current else None,
                "updated_at": entry.get("updated_at") if isinstance(entry.get("updated_at"), str) else None,
                "preview_state": "current" if current and _safe_preview(entry.get("preview")) else "needs_sync",
            })
        incomplete = any(
            not KEY_RE.fullmatch(key) or not isinstance(entry, dict) or not _safe_preview(entry.get("preview"))
            for key, entry in data.get("variables", {}).items()
        )
        return {"variables": items, "needs_sync": not current or incomplete, "metadata_state": problem or ("ready" if current else "stale"),
                "file_exists": stamp is not None, "inventory_known": current}

    def get(self, key):
        validate_key(key)
        listing = self.list()
        for entry in listing["variables"]:
            if entry["key"] == key:
                return entry
        raise EnvStoreError("not_found", 404)

    def _read(self):
        if self.path.is_symlink():
            raise EnvStoreError("unsafe_file", 409)
        before = _stamp(self.path)
        if before is not None and before[2] > 2 * 1024 * 1024:
            raise EnvStoreError("file_too_large", 409)
        try:
            with self.path.open("r", encoding="utf-8", newline="") as stream:
                text = stream.read()
        except FileNotFoundError:
            text = ""
        if _stamp(self.path) != before:
            raise EnvStoreError("external_change", 409)
        bindings = list(parse_stream(io.StringIO(text)))
        # The existing python-dotenv parser preserves raw bindings (comments,
        # export, multiline strings, CRLF); no second dotenv grammar is used.
        values = {b.key: b.value for b in bindings if b.key is not None and not b.error}
        return text, bindings, values, before

    def sync(self):
        with env_file_lock(self.path):
            _, _, values, before = self._read()
            # Resolve the same expansion rules used by startup without putting
            # anything into the process environment or modifying .env.
            resolved = dotenv_values(self.path) if before is not None else {}
            if _stamp(self.path) != before:
                raise EnvStoreError("external_change", 409)
            entries = {}
            for key in values:
                if not KEY_RE.fullmatch(key):
                    continue
                entries[key] = {"preview": mask_value(resolved.get(key) or ""), "updated_at": _now()}
            self._save_metadata({"version": 1, "state": "ready", "stamp": before, "variables": entries})
            return self.list()

    def mutate(self, action, key, value=None):
        validate_key(key)
        if action not in ("create", "update", "delete"):
            raise EnvStoreError("invalid_action")
        if value is not None:
            if not isinstance(value, str) or len(value) > 8192 or any(c in value for c in ("\r", "\n", "\0")):
                raise EnvStoreError("invalid_value")
            if "•" in value or "***" in value:
                raise EnvStoreError("masked_value")
            # dotenv expands ${...} even inside single quotes. Refuse ambiguous
            # new values instead of silently changing a credential at restart.
            if "${" in value:
                raise EnvStoreError("interpolated_value")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise EnvStoreError("invalid_value") from None
        if action == "create" and not value:
            raise EnvStoreError("value_required")
        with env_file_lock(self.path):
            text, bindings, values, before = self._read()
            if os.name == "nt" and any(name != key and name.upper() == key.upper() for name in values):
                # Windows maps these names to the same process variable. Never
                # create aliases or mutate an ambiguous legacy pair as though
                # they were independent credentials.
                raise EnvStoreError("case_conflict", 409)
            if action == "create" and key in values:
                raise EnvStoreError("already_exists", 409)
            if action != "create" and key not in values:
                raise EnvStoreError("not_found", 404)
            if action == "update" and not value:
                # A blank editor is a no-op: do not replace metadata or attach
                # a fresh file stamp to a preview of an unchanged value.
                result = self.list()
                result.update(warning=None, runtime_updated=False, restart_may_be_required=False)
                return result
            old, problem = self._metadata()
            valid = not problem and old.get("state") == "ready" and old.get("stamp") == before
            changing = action in ("create", "delete") or bool(value)
            entries = {}
            for name, original in values.items():
                if not KEY_RE.fullmatch(name):
                    continue
                previous = old.get("variables", {}).get(name, {})
                if not isinstance(previous, dict):
                    previous = {}
                # Changing another variable can change ${...} expansions too.
                # Preserve their source text, but require an explicit sync
                # instead of certifying an old derived preview with a new stamp.
                preview_valid = valid and not (changing and original and "${" in original)
                entries[name] = {"preview": _safe_preview(previous.get("preview")) if preview_valid else None,
                                 "updated_at": previous.get("updated_at")}
            replacement = value
            if action == "delete":
                entries.pop(key, None)
            else:
                entry = entries.setdefault(key, {})
                if changing:
                    entry.update(preview=mask_value(replacement), updated_at=_now())
                entry["updated_at"] = _now()
            output = text
            if changing:
                newline = "\r\n" if "\r\n" in text else "\n"
                # Quote literal single-line values using python-dotenv's own
                # escaping convention. Unchanged bindings stay byte-for-byte.
                encoded = "'" + (replacement or "").replace("\\", "\\\\").replace("'", "\\'") + "'"
                line = key + "=" + encoded + newline
                parts, found = [], False
                for binding in bindings:
                    if binding.key == key and not binding.error:
                        # python-dotenv attaches preceding blank lines to the
                        # next binding. They belong to the document, not the
                        # key being replaced or deleted.
                        parts.append(re.match(r"(?:[ \t]*(?:\r\n|\n|\r))*", binding.original.string).group())
                        if action != "delete" and not found:
                            parts.append(line)
                        found = True
                    else:
                        parts.append(binding.original.string)
                if not found and action == "create":
                    if text and not text.endswith(("\n", "\r")):
                        parts.append(newline)
                    parts.append(line)
                output = "".join(parts)
            if _stamp(self.path) != before:
                raise EnvStoreError("external_change", 409)
            # Publish dirty first; a failed preflight never changes credentials.
            dirty = {"version": 1, "state": "updating", "stamp": before, "variables": entries}
            self._save_metadata(dirty)
            if _stamp(self.path) != before:
                raise EnvStoreError("external_change", 409)
            if changing:
                write_private_atomic(self.path, output)
            after = _stamp(self.path)
            if changing:
                # An editor outside our lock can replace the file immediately
                # after our swap. Verify bytes against a stable stamp before
                # certifying the new previews or publishing runtime values.
                try:
                    expected = output.encode("utf-8")
                    matches = after is not None and after[2] == len(expected)
                    if matches:
                        with self.path.open("rb") as stream:
                            matches = stream.read(len(expected) + 1) == expected
                except OSError:
                    matches = False
                if not matches or _stamp(self.path) != after:
                    raise EnvStoreError("external_change", 409)
            warning = None
            try:
                self._save_metadata(dict(dirty, state="ready", stamp=after))
            except OSError:
                # Do not roll back an already committed key. Dirty metadata
                # remains durable and all read paths hide its previews.
                warning = "metadata_pending"
            runtime_updated = False
            if changing:
                try:
                    if action == "delete":
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = replacement or ""
                    runtime_updated = True
                    # Existing skill refresh logs third-party exceptions; avoid
                    # that path here, because an exception might contain a key.
                    if self.tool.agent_bridge:
                        self.tool._reload_env()
                        self.tool.agent_bridge.refresh_all_skills()
                except Exception:
                    warning = warning or "reload_pending"
            result = self.list()
            result.update(warning=warning, runtime_updated=runtime_updated, restart_may_be_required=changing)
            return result
