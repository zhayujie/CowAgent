"""
Skill service for handling skill CRUD operations.

This service provides a unified interface for managing skills, which can be
called from the cloud control client (LinkAI), the local web console, or any
other management entry point.
"""

import os
import shutil
import zipfile
import tempfile
from typing import List, Optional
from common.log import logger
from agent.skills.manager import SkillManager

try:
    import requests
except ImportError:
    requests = None


class SkillService:
    """
    High-level service for skill lifecycle management.
    Wraps SkillManager and provides network-aware operations such as
    downloading skill files from remote URLs.
    """

    def __init__(self, skill_manager: SkillManager):
        """
        :param skill_manager: The SkillManager instance to operate on
        """
        self.manager = skill_manager

    def _safe_skill_dir(self, name: str) -> str:
        """Derive and validate the skill directory path.

        Ensures the resolved path stays within the custom_dir root,
        preventing path traversal via names like ``../escaped``.

        :raises ValueError: if the name would escape the skills root.
        """
        if not name or not name.strip():
            raise ValueError("skill name is required")
        # Reject obvious traversal components.
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            raise ValueError(f"invalid skill name (path traversal detected): {name!r}")
        skill_dir = os.path.realpath(os.path.join(self.manager.custom_dir, name))
        root = os.path.realpath(self.manager.custom_dir)
        if not skill_dir.startswith(root + os.sep) and skill_dir != root:
            raise ValueError(
                f"skill name {name!r} resolves outside the skills directory"
            )
        return skill_dir

    @staticmethod
    def _safe_file_path(root: str, rel_path: str) -> str:
        """Resolve a skill file path and validate it stays inside ``root``.

        The per-file paths in an add payload are attacker-controlled just like
        the skill name, so they need the same containment check: entries such
        as ``../../evil.py`` or ``/etc/cron.d/evil`` would otherwise write
        outside the skills directory.

        Backslashes are normalised to ``/`` first, so a Windows-style payload
        is checked the same way on POSIX, where ``\\`` is a legal filename
        character rather than a separator.

        :raises ValueError: if the resolved path would escape ``root``.
        """
        dest = os.path.realpath(os.path.join(root, rel_path.replace("\\", "/")))
        root = os.path.realpath(root)
        if not dest.startswith(root + os.sep):
            raise ValueError(
                f"invalid skill file path (path traversal detected): {rel_path!r}"
            )
        return dest

    # ------------------------------------------------------------------
    # query
    # ------------------------------------------------------------------
    def query(self) -> List[dict]:
        """
        Query all skills and return a serialisable list.
        Reads from skills_config.json (refreshes from disk if needed).

        :return: list of skill info dicts
        """
        self.manager.refresh_skills()
        config = self.manager.get_skills_config()
        result = list(config.values())
        logger.info(f"[SkillService] query: {len(result)} skills found")
        return result

    # ------------------------------------------------------------------
    # content — read and edit a skill's definition file
    # ------------------------------------------------------------------
    def read_content(self, name: str) -> dict:
        """
        Read a skill's definition file, for viewing or editing in a console.

        Every skill is readable; ``editable`` is what says whether saving would
        be accepted, and is false for one that ships with the installation.

        :param name: skill name as listed by :meth:`query`
        :return: the fields of :meth:`WorkspaceService.read_text` plus the skill
            ``name``, its ``source``, the ``filename`` being shown, and
            ``ships_with_install`` to explain a refusal.
        :raises FileNotFoundError: if no skill of that name is loaded.
        """
        skill, svc, rel = self._locate(name)
        shipped = self._ships_with_install(skill)
        result = svc.read_text(rel)
        result["name"] = skill.name
        result["source"] = skill.source
        result["filename"] = rel
        # Reported separately from `source`, which stays `custom` for the
        # workspace copy of a builtin: the console needs this to say *why* it is
        # refusing the edit, and `source` alone does not tell it.
        result["ships_with_install"] = shipped
        result["editable"] = result["editable"] and not shipped
        return result

    def write_content(self, name: str, content: str,
                      expected_mtime: Optional[float] = None) -> dict:
        """
        Overwrite a skill's definition file.

        :param expected_mtime: the mtime the caller read, forwarded to
            :meth:`WorkspaceService.write_text` so a rewrite that happened
            mid-edit raises rather than being overwritten silently.
        :raises ValueError: for a skill that ships with the installation, whose
            files do not survive an edit. See :meth:`_ships_with_install`.
        """
        skill, svc, rel = self._locate(name)
        if self._ships_with_install(skill):
            raise ValueError(f"skill ships with the installation and is read-only: {name}")

        result = svc.write_text(rel, content, expected_mtime=expected_mtime)
        # The frontmatter holds the name and description the skill list shows,
        # so an edit can change how this skill presents itself.
        self.manager.refresh_skills()
        logger.info(f"[SkillService] write_content: skill '{name}' saved ({result['size']} bytes)")
        return result

    def _ships_with_install(self, skill) -> bool:
        """
        True when this skill's files come back from the installation, so an edit
        made here would not survive.

        Deliberately not just ``source == "builtin"``. Startup copies every
        builtin skill directory into the workspace and deletes whatever was
        there first (``_sync_builtin_skills`` in app.py), so the copy the loader
        resolves is a ``custom`` one that is *still* replaced on the next start.
        Offering an editor for it would throw the edit away at the next restart,
        with nothing to say so.
        """
        if skill.source == "builtin":
            return True
        shadowed = os.path.join(self.manager.builtin_dir,
                                os.path.basename(skill.base_dir))
        return os.path.isfile(os.path.join(shadowed, "SKILL.md"))

    def _locate(self, name: str):
        """
        Resolve a skill name to ``(skill, service, path within its directory)``.

        Skills are addressed by name because the loader is what knows where a
        name lands: a workspace skill shadows a builtin one of the same name,
        and a builtin lives outside the workspace entirely. Rooting a
        :class:`WorkspaceService` at the skill's own directory then keeps both
        the read and the write inside it, and reuses the containment check, the
        mtime comparison, the atomic replace and the UTF-8 and size limits that
        the workspace file editor already enforces.
        """
        from agent.workspace.service import WorkspaceService

        if not name or not name.strip():
            raise ValueError("skill name is required")
        entry = self.manager.get_skill(name)
        if entry is None:
            raise FileNotFoundError(f"skill not found: {name}")
        skill = entry.skill
        return skill, WorkspaceService(skill.base_dir), os.path.basename(skill.file_path)

    # ------------------------------------------------------------------
    # add / install
    # ------------------------------------------------------------------
    def add(self, payload: dict) -> None:
        """
        Add (install) a skill from a remote payload.

        Supported payload types:

        1. ``type: "url"`` – download individual files::

            {
                "name": "web_search",
                "type": "url",
                "enabled": true,
                "files": [
                    {"url": "https://...", "path": "README.md"},
                    {"url": "https://...", "path": "scripts/main.py"}
                ]
            }

        2. ``type: "package"`` – download a zip archive and extract::

            {
                "name": "plugin-custom-tool",
                "type": "package",
                "category": "skills",
                "enabled": true,
                "files": [{"url": "https://cdn.example.com/skills/custom-tool.zip"}]
            }

        :param payload: skill add payload from server
        """
        name = payload.get("name")
        if not name:
            raise ValueError("skill name is required")

        payload_type = payload.get("type", "url")

        if payload_type == "package":
            self._add_package(name, payload)
        else:
            self._add_url(name, payload)

        self.manager.refresh_skills()

        category = payload.get("category")
        if category and name in self.manager.skills_config:
            self.manager.skills_config[name]["category"] = category
            self.manager._save_skills_config()

    def _add_url(self, name: str, payload: dict) -> None:
        """Install a skill by downloading individual files."""
        files = payload.get("files", [])
        if not files:
            raise ValueError("skill files list is empty")

        skill_dir = self._safe_skill_dir(name)

        tmp_dir = skill_dir + ".tmp"
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)

        try:
            for file_info in files:
                url = file_info.get("url")
                rel_path = file_info.get("path")
                if not url or not rel_path:
                    logger.warning(f"[SkillService] add: skip invalid file entry {file_info}")
                    continue
                dest = self._safe_file_path(tmp_dir, rel_path)
                self._download_file(url, dest)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        if os.path.exists(skill_dir):
            shutil.rmtree(skill_dir)
        os.rename(tmp_dir, skill_dir)

        logger.info(f"[SkillService] add: skill '{name}' installed via url ({len(files)} files)")

    def _add_package(self, name: str, payload: dict) -> None:
        """
        Install a skill by downloading a zip archive and extracting it.

        If the archive contains a single top-level directory, that directory
        is used as the skill folder directly; otherwise a new directory named
        after the skill is created to hold the extracted contents.
        """
        files = payload.get("files", [])
        if not files or not files[0].get("url"):
            raise ValueError("package url is required")

        url = files[0]["url"]
        skill_dir = self._safe_skill_dir(name)

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "package.zip")
            self._download_file(url, zip_path)

            if not zipfile.is_zipfile(zip_path):
                raise ValueError(f"downloaded file is not a valid zip archive: {url}")

            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Determine the actual content root.
            # If the zip has a single top-level directory, use its contents
            # so the skill folder is clean (no extra nesting).
            top_items = [
                item for item in os.listdir(extract_dir)
                if not item.startswith(".")
            ]
            if len(top_items) == 1:
                single = os.path.join(extract_dir, top_items[0])
                if os.path.isdir(single):
                    extract_dir = single

            if os.path.exists(skill_dir):
                shutil.rmtree(skill_dir)
            shutil.copytree(extract_dir, skill_dir)

        logger.info(f"[SkillService] add: skill '{name}' installed via package ({url})")

    # ------------------------------------------------------------------
    # open / close (enable / disable)
    # ------------------------------------------------------------------
    def open(self, payload: dict) -> None:
        """
        Enable a skill by name.

        :param payload: {"name": "skill_name"}
        """
        name = payload.get("name")
        if not name:
            raise ValueError("skill name is required")
        self.manager.set_skill_enabled(name, enabled=True)
        logger.info(f"[SkillService] open: skill '{name}' enabled")

    def close(self, payload: dict) -> None:
        """
        Disable a skill by name.

        :param payload: {"name": "skill_name"}
        """
        name = payload.get("name")
        if not name:
            raise ValueError("skill name is required")
        self.manager.set_skill_enabled(name, enabled=False)
        logger.info(f"[SkillService] close: skill '{name}' disabled")

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    def delete(self, payload: dict) -> None:
        """
        Delete a skill by removing its directory entirely.

        :param payload: {"name": "skill_name"}
        """
        name = payload.get("name")
        if not name:
            raise ValueError("skill name is required")

        skill_dir = self._safe_skill_dir(name)
        if os.path.exists(skill_dir):
            shutil.rmtree(skill_dir)
            logger.info(f"[SkillService] delete: removed directory {skill_dir}")
        else:
            logger.warning(f"[SkillService] delete: skill directory not found: {skill_dir}")

        # Refresh will remove the deleted skill from config automatically
        self.manager.refresh_skills()
        logger.info(f"[SkillService] delete: skill '{name}' deleted")

    # ------------------------------------------------------------------
    # dispatch - single entry point for protocol messages
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch a skill management action and return a protocol-compatible
        response dict.

        :param action: one of query / add / open / close / delete
        :param payload: action-specific payload (may be None for query)
        :return: dict with action, code, message, payload
        """
        payload = payload or {}
        try:
            if action == "query":
                result_payload = self.query()
                return {"action": action, "code": 200, "message": "success", "payload": result_payload}
            elif action == "add":
                self.add(payload)
            elif action == "open":
                self.open(payload)
            elif action == "close":
                self.close(payload)
            elif action == "delete":
                self.delete(payload)
            else:
                return {"action": action, "code": 400, "message": f"unknown action: {action}", "payload": None}
            return {"action": action, "code": 200, "message": "success", "payload": None}
        except Exception as e:
            logger.error(f"[SkillService] dispatch error: action={action}, error={e}")
            return {"action": action, "code": 500, "message": str(e), "payload": None}

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _download_file(url: str, dest: str):
        """
        Download a file from *url* and save to *dest*.

        :param url: remote file URL
        :param dest: local destination path
        """
        if requests is None:
            raise RuntimeError("requests library is required for downloading skill files")

        dest_dir = os.path.dirname(dest)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
        logger.debug(f"[SkillService] downloaded {url} -> {dest}")
