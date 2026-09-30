"""
Skill service for handling skill CRUD operations.

This service provides a unified interface for managing skills, which can be
called from the cloud control client (LinkAI), the local web console, or any
other management entry point.
"""

import json
import os
import re
import shutil
import tempfile
from typing import List, Optional
from common.log import logger
from agent.skills.archive import extract_archive
from agent.skills.manager import SkillManager

try:
    import requests
except ImportError:
    requests = None

SKILL_FILE = "SKILL.md"

# Left out of the file tree a console shows: build output and caches are not
# part of the skill anyone wrote. Dot directories - `.git`, `.venv` - need no
# entry here; the walk skips everything hidden, which is not what anyone meant
# to edit through a list either.
_TREE_SKIP_DIRS = {"__pycache__", "node_modules", "venv"}

# A skill's name is also its directory name, the word the CLI addresses it by
# (``cow skill uninstall <name>``) and the identifier the model sees, so it is
# held to the hyphen-case convention the skill-creator guide states.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")

# A plain YAML scalar cannot start with an indicator character, and cannot carry
# ``: `` or `` #`` anywhere in it, without changing what it parses to. A
# description written by a user reaches all of those, so it gets quoted instead.
_YAML_NEEDS_QUOTING = re.compile(r"""^[\s\-?:,\[\]{}#&*!|>'"%@`]|:\s|\s#|:$|[\n\r]""")


def normalize_skill_name(raw: Optional[str]) -> str:
    """Reduce a title typed into a console into a usable skill name.

    Everything outside ``[a-z0-9]`` collapses to a hyphen, so "Weather API" and
    "weather_api" both land on ``weather-api``. A title with nothing else in it
    - a purely Chinese one, say - leaves nothing to name a directory after, and
    is refused rather than silently turned into something like ``skill-1``; the
    caller keeps it as the skill's display name instead.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (raw or "").strip().lower()).strip("-")[:64].rstrip("-")
    if not _SKILL_NAME_RE.match(slug):
        raise ValueError(
            f"skill name must contain latin letters or digits: {(raw or '').strip()!r}"
        )
    return slug


def _yaml_scalar(value: str) -> str:
    """A frontmatter value, quoted when a plain scalar would not survive YAML."""
    if not value or _YAML_NEEDS_QUOTING.search(value):
        # A JSON string is a valid YAML double-quoted scalar, escapes included.
        return json.dumps(value, ensure_ascii=False)
    return value


def render_skill_md(name: str, description: str, body: str = "") -> str:
    """Build a SKILL.md from the fields a creation form collects."""
    front = f"---\nname: {_yaml_scalar(name)}\ndescription: {_yaml_scalar(description)}\n---\n"
    body = (body or "").strip()
    if not body:
        # A skill with no instructions is still a skill: the description alone
        # triggers it, and the console's editor is where the body gets written.
        return front
    return f"{front}\n{body}\n"


def _upload_rel_path(path: Optional[str]) -> str:
    """The path an uploaded file keeps inside the skill directory.

    A browser sends either a bare file name or, for a folder pick, a path
    relative to the chosen folder. Windows separators are normalised, and a
    leading drive or slash is dropped, so what is left is always relative -
    ``_safe_file_path`` then rejects anything that still escapes.
    """
    cleaned = (path or "").replace("\\", "/").strip()
    cleaned = re.sub(r"^[A-Za-z]:", "", cleaned).lstrip("/")
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    return "/".join(parts)


class SkillService:
    """
    High-level service for skill lifecycle management.
    Wraps SkillManager and provides network-aware operations such as
    downloading skill files from remote URLs.
    """

    # Ceilings on what one create or install may carry. A skill is text plus a
    # few scripts and assets, so these are generous for the real case while
    # still bounding what an upload - or a package downloaded from a hub - can
    # unpack into the workspace.
    MAX_UPLOAD_FILES = 500
    MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024
    MAX_UPLOAD_TOTAL_SIZE = 50 * 1024 * 1024

    # How deep a skill's file tree is walked. A skill is instructions plus a few
    # scripts and resources, so this is far past any real one; it is here
    # because the walk is a recursion and the directories under a skill are not
    # all of its own making.
    MAX_TREE_DEPTH = 12

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

    def _contained_skill_dir(self, base_dir: str, name: str) -> str:
        """Validate that a loaded skill's directory sits inside the skills root.

        :raises ValueError: for the root itself or anything outside it, such
            as a builtin skill resolved from the install directory.
        """
        skill_dir = os.path.realpath(base_dir)
        root = os.path.realpath(self.manager.custom_dir)
        if not skill_dir.startswith(root + os.sep):
            raise ValueError(f"skill {name!r} is not in the workspace skills directory")
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
        for item in result:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            entry = self.manager.get_skill(name) if name else None
            if entry is not None:
                item["ships_with_install"] = self._ships_with_install(entry.skill)
            else:
                item["ships_with_install"] = item.get("source") == "builtin"
            item["deletable"] = not item["ships_with_install"]
        logger.info(f"[SkillService] query: {len(result)} skills found")
        return result

    # ------------------------------------------------------------------
    # content — browse, read and edit the files a skill is made of
    # ------------------------------------------------------------------
    def list_files(self, name: str) -> dict:
        """
        The files a skill directory holds, for a console's file tree.

        A skill is a directory, not a single document: ``scripts/``,
        ``references/`` and bundled assets are as much part of it as its
        SKILL.md, and an upload or a package installs all of them. Listed depth
        first in the order a tree draws them, so the caller can render the
        nesting from ``depth`` without rebuilding the hierarchy itself.

        :return: ``{"name", "source", "ships_with_install", "files": [...],
            "truncated": bool}``, where each file carries ``path`` (relative to
            the skill directory), ``name``, ``depth``, ``is_dir``, ``kind``,
            ``text`` - whether it can be shown as text at all - ``size`` and
            ``mtime``.
        :raises FileNotFoundError: if no skill of that name is loaded.
        """
        from agent.protocol.artifact import classify_kind, is_editable

        skill = self._skill(name)
        files: List[dict] = []
        truncated = False

        def walk(directory: str, rel_prefix: str, depth: int) -> None:
            nonlocal truncated
            dirs, plain = [], []
            try:
                # Closed rather than left to the collector: an open handle on a
                # directory blocks it from being removed on Windows, which is
                # where an install replacing this very skill would then fail.
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.name.startswith(".") or entry.name in _TREE_SKIP_DIRS:
                            continue
                        # A link is not part of the skill the way a file in it
                        # is: it can point anywhere, and reading it would be
                        # refused for resolving outside the skill directory.
                        # Listing one would only offer a row that cannot open.
                        if entry.is_symlink():
                            continue
                        (dirs if entry.is_dir(follow_symlinks=False) else plain).append(entry)
            except OSError:
                return

            dirs.sort(key=lambda e: e.name.lower())
            # SKILL.md is the skill's entry point, so it leads the files it sits
            # beside rather than landing wherever the alphabet puts it.
            plain.sort(key=lambda e: (e.name != SKILL_FILE, e.name.lower()))

            for entry in dirs + plain:
                if len(files) >= self.MAX_UPLOAD_FILES:
                    truncated = True
                    return
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                kind = "directory" if is_dir else classify_kind(entry.name)
                rel = f"{rel_prefix}{entry.name}"
                files.append({
                    "path": rel,
                    "name": entry.name,
                    "depth": depth,
                    "is_dir": is_dir,
                    "kind": kind,
                    # Whether reading it as text is meaningful at all. An image
                    # or a PDF is part of the skill and belongs in the tree, but
                    # opening it in a text editor would only show mojibake.
                    "text": (not is_dir) and (is_editable(kind) or kind == "file"),
                    "size": 0 if is_dir else stat.st_size,
                    "mtime": stat.st_mtime,
                })
                if not is_dir:
                    continue
                if depth + 1 > self.MAX_TREE_DEPTH:
                    # Reported as truncated rather than walked: this is a
                    # recursion, and a skill is never legitimately this deep.
                    truncated = True
                    continue
                walk(entry.path, f"{rel}/", depth + 1)

        walk(skill.base_dir, "", 0)
        return {
            "name": skill.name,
            "source": skill.source,
            "ships_with_install": self._ships_with_install(skill),
            "files": files,
            "truncated": truncated,
        }

    def read_content(self, name: str, path: Optional[str] = None) -> dict:
        """
        Read one of a skill's files, for viewing or editing in a console.

        Every file is readable; ``editable`` is what says whether saving would
        be accepted, and is false for one that ships with the installation.

        :param name: skill name as listed by :meth:`query`
        :param path: a file within the skill directory, as listed by
            :meth:`list_files`. Defaults to the skill's own SKILL.md.
        :return: the fields of :meth:`WorkspaceService.read_text` plus the skill
            ``name``, its ``source``, the ``filename`` being shown, and
            ``ships_with_install`` to explain a refusal.
        :raises FileNotFoundError: if no skill of that name is loaded, or the
            skill holds no such file.
        """
        skill, svc, rel = self._locate(name, path)
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
                      expected_mtime: Optional[float] = None,
                      path: Optional[str] = None) -> dict:
        """
        Overwrite one of a skill's files.

        :param expected_mtime: the mtime the caller read, forwarded to
            :meth:`WorkspaceService.write_text` so a rewrite that happened
            mid-edit raises rather than being overwritten silently.
        :param path: a file within the skill directory. Defaults to SKILL.md.
        :raises ValueError: for a skill that ships with the installation, whose
            files do not survive an edit. See :meth:`_ships_with_install`.
        """
        skill, svc, rel = self._locate(name, path)
        if self._ships_with_install(skill):
            raise ValueError(f"skill ships with the installation and is read-only: {name}")

        result = svc.write_text(rel, content, expected_mtime=expected_mtime)
        # The frontmatter holds the name and description the skill list shows,
        # so an edit can change how this skill presents itself.
        self.manager.refresh_skills()
        logger.info(f"[SkillService] write_content: skill '{name}' file '{rel}' "
                    f"saved ({result['size']} bytes)")
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

    def _skill(self, name: str):
        """The loaded skill of that name.

        Skills are addressed by name because the loader is what knows where a
        name lands: a workspace skill shadows a builtin one of the same name,
        and a builtin lives outside the workspace entirely.
        """
        if not name or not name.strip():
            raise ValueError("skill name is required")
        entry = self.manager.get_skill(name)
        if entry is None:
            raise FileNotFoundError(f"skill not found: {name}")
        return entry.skill

    def _locate(self, name: str, path: Optional[str] = None):
        """
        Resolve a skill and one of its files to ``(skill, service, rel path)``.

        Rooting a :class:`WorkspaceService` at the skill's own directory keeps
        both the read and the write inside it, and reuses the containment check,
        the mtime comparison, the atomic replace and the UTF-8 and size limits
        that the workspace file editor already enforces. ``path`` is normalised
        the way an upload's paths are, and is then checked by that service
        rather than here: a ``..`` left in it resolves outside the skill
        directory and is refused.

        :param path: a file within the skill directory, or None for its SKILL.md.
        """
        from agent.workspace.service import WorkspaceService

        skill = self._skill(name)
        svc = WorkspaceService(skill.base_dir)
        rel = _upload_rel_path(path) if path else ""
        if not rel:
            rel = os.path.basename(skill.file_path)
        return skill, svc, rel

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
            archive_path = os.path.join(tmp_dir, "package")
            self._download_file(url, archive_path)

            extract_dir = os.path.join(tmp_dir, "extracted")
            with open(archive_path, "rb") as f:
                # A downloaded package is untrusted, so it goes through the same
                # refusals as an uploaded one: path traversal, links, special
                # files. Reading the format from the bytes also means a
                # ``.tar.gz`` served under a ``.zip`` name still installs.
                extract_archive(f.read(), extract_dir,
                                max_files=self.MAX_UPLOAD_FILES,
                                max_total_size=self.MAX_UPLOAD_TOTAL_SIZE)

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
    # create from a console
    # ------------------------------------------------------------------
    def create(self, payload: dict) -> dict:
        """
        Create a skill from the fields a creation form collects.

        :param payload: ``{"name", "description", "body", "files"}``, where
            ``body`` is the SKILL.md instructions below the frontmatter and
            ``files`` are resources to bundle beside it, each
            ``{"path": str, "content": bytes}``.
        :return: ``{"name": ..., "files": [paths bundled]}``
        :raises ValueError: for a name that cannot be used, a missing
            description, or a skill of that name that already exists.
        """
        title = (payload.get("name") or "").strip()
        name = normalize_skill_name(title)
        description = (payload.get("description") or "").strip()
        if not description:
            # The loader drops a skill whose frontmatter carries no description,
            # so one created without it would disappear from the very list it
            # was created in, with nothing on screen to say why.
            raise ValueError("skill description is required")

        self._reject_shipped_name(name)
        skill_dir = self._safe_skill_dir(name)
        if os.path.exists(skill_dir):
            raise ValueError(f"skill already exists: {name}")

        # Assembled beside the target and moved into place, so a failed write
        # leaves no half-written skill for the loader to pick up. The dot keeps
        # it out of the loader's way while it is being written, too: a scan that
        # lands mid-create skips it the way it skips every hidden directory.
        tmp_dir = os.path.join(os.path.dirname(skill_dir), f".{name}.tmp")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        try:
            # SKILL.md is what the form itself writes; an attachment of that
            # name would either lose the fields just filled in or shadow them.
            bundled = self._write_uploads(tmp_dir, payload.get("files") or [],
                                          skip=(SKILL_FILE,))
            with open(os.path.join(tmp_dir, SKILL_FILE), "w",
                      encoding="utf-8", newline="\n") as f:
                f.write(render_skill_md(name, description, payload.get("body")))
            os.rename(tmp_dir, skill_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        self.manager.refresh_skills()
        self._set_display_name(name, title)
        logger.info(f"[SkillService] create: skill '{name}' created "
                    f"({len(bundled)} bundled file(s))")
        return {"name": name, "files": bundled}

    def _write_uploads(self, root: str, items: List[dict],
                       skip: tuple = ()) -> List[str]:
        """
        Write uploaded files under ``root``, keeping their relative paths.

        :param skip: relative paths to leave out, matched case-insensitively.
        :return: the relative paths written, in the order they arrived.
        """
        if len(items) > self.MAX_UPLOAD_FILES:
            raise ValueError(f"too many files: at most {self.MAX_UPLOAD_FILES} are accepted")

        unwanted = {s.lower() for s in skip}
        written: List[str] = []
        total = 0
        for item in items:
            rel = _upload_rel_path(item.get("path") or item.get("filename"))
            if not rel or rel.lower() in unwanted:
                continue
            content = item.get("content") or b""
            if isinstance(content, str):
                content = content.encode("utf-8")
            if len(content) > self.MAX_UPLOAD_FILE_SIZE:
                raise ValueError(f"file too large: {rel}")
            total += len(content)
            if total > self.MAX_UPLOAD_TOTAL_SIZE:
                raise ValueError("upload too large")
            dest = self._safe_file_path(root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(content)
            written.append(rel)
        return written

    def _reject_shipped_name(self, name: str) -> None:
        """
        Refuse a name the installation itself ships.

        Startup copies every builtin skill over the workspace copy of the same
        name (``_sync_builtin_skills`` in app.py), so a skill written here under
        a builtin's name would be replaced at the next restart - silently, and
        after the user had every reason to think it was saved.
        """
        if os.path.isfile(os.path.join(self.manager.builtin_dir, name, SKILL_FILE)):
            raise ValueError(f"'{name}' is the name of a built-in skill; choose another")

    def _set_display_name(self, name: str, title: str) -> None:
        """
        Keep the title as typed, where the skill's name had to differ from it.

        The console lists ``display_name`` in preference to the name, so a title
        like "Weather API 助手" still reads as itself after being reduced to the
        ascii, hyphen-case name that a directory and the CLI need.
        """
        title = (title or "").strip()
        entry = self.manager.skills_config.get(name)
        if not entry or not title or title == name:
            return
        entry["display_name"] = title
        self.manager._save_skills_config()

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

        entry = self.manager.get_skill(name)
        if entry is not None:
            # The folder need not be named after the frontmatter ``name`` (a
            # hand-made or renamed skill), so remove it where the loader found it.
            skill_dir = self._contained_skill_dir(entry.skill.base_dir, name)
        else:
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
