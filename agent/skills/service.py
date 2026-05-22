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
from typing import Dict, List, Optional
from common.log import logger
from agent.skills.types import Skill, SkillEntry
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

        skill_dir = os.path.join(self.manager.custom_dir, name)

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
                dest = os.path.join(tmp_dir, rel_path)
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
        skill_dir = os.path.join(self.manager.custom_dir, name)

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

        skill_dir = os.path.join(self.manager.custom_dir, name)
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
