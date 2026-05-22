"""
Knowledge service for handling knowledge base operations.

Provides a unified interface for listing, reading, and graphing knowledge files,
callable from the web console, API, or CLI.

Knowledge file layout (under workspace_root):
    knowledge/index.md
    knowledge/log.md
    knowledge/<category>/<slug>.md
"""

import os
import re
from pathlib import Path
from typing import Optional

from common.log import logger
from config import conf


class KnowledgeService:
    """
    High-level service for knowledge base queries.
    Operates directly on the filesystem.
    """

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.knowledge_dir = os.path.join(workspace_root, "knowledge")

    # ------------------------------------------------------------------
    # list — directory tree with stats
    # ------------------------------------------------------------------
    def list_tree(self) -> dict:
        """
        Return the knowledge directory tree grouped by category,
        supporting arbitrarily nested sub-directories.

        Returns::

            {
                "tree": [
                    {
                        "dir": "concepts",
                        "files": [
                            {"name": "moe.md", "title": "MoE", "size": 1234},
                        ],
                        "children": []
                    },
                    {
                        "dir": "platform",
                        "files": [],
                        "children": [
                            {
                                "dir": "analysis",
                                "files": [{"name": "perf.md", ...}],
                                "children": []
                            }
                        ]
                    },
                ],
                "stats": {"pages": 15, "size": 32768},
                "enabled": true
            }
        """
        if not os.path.isdir(self.knowledge_dir):
            return {"tree": [], "stats": {"pages": 0, "size": 0}, "enabled": conf().get("knowledge", True)}

        stats = {"pages": 0, "size": 0}
        root_files, tree = self._scan_dir(self.knowledge_dir, stats, is_root=True)

        return {
            "root_files": root_files,
            "tree": tree,
            "stats": stats,
            "enabled": conf().get("knowledge", True),
        }

    def _scan_dir(self, dir_path: str, stats: dict, is_root: bool = False) -> tuple:
        """
        Recursively scan a directory.

        :return: (files, children) where files is a list of .md file dicts
                 in this directory and children is a list of sub-directory nodes.
        """
        files = []
        children = []
        for name in sorted(os.listdir(dir_path)):
            if name.startswith("."):
                continue
            full = os.path.join(dir_path, name)
            if os.path.isdir(full):
                sub_files, sub_children = self._scan_dir(full, stats)
                children.append({"dir": name, "files": sub_files, "children": sub_children})
            elif name.endswith(".md"):
                size = os.path.getsize(full)
                if not is_root:
                    stats["pages"] += 1
                    stats["size"] += size
                title = name.replace(".md", "")
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        first_line = f.readline().strip()
                    if first_line.startswith("# "):
                        title = first_line[2:].strip()
                except Exception:
                    pass
                files.append({"name": name, "title": title, "size": size})
        return files, children

    # ------------------------------------------------------------------
    # read — single file content
    # ------------------------------------------------------------------
    def read_file(self, rel_path: str) -> dict:
        """
        Read a single knowledge markdown file.

        :param rel_path: Relative path within knowledge/, e.g. ``concepts/moe.md``
        :return: dict with ``content`` and ``path``
        :raises ValueError: if path is invalid or escapes knowledge dir
        :raises FileNotFoundError: if file does not exist
        """
        if not rel_path or ".." in rel_path:
            raise ValueError("invalid path")

        full_path = os.path.normpath(os.path.join(self.knowledge_dir, rel_path))
        allowed = os.path.normpath(self.knowledge_dir)
        if not full_path.startswith(allowed + os.sep) and full_path != allowed:
            raise ValueError("path outside knowledge dir")

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"file not found: {rel_path}")

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": rel_path}

    # ------------------------------------------------------------------
    # graph — nodes and links for visualization
    # ------------------------------------------------------------------
    def build_graph(self) -> dict:
        """
        Parse all knowledge pages and extract cross-reference links.

        Returns::

            {
                "nodes": [
                    {"id": "concepts/moe.md", "label": "MoE", "category": "concepts"},
                    ...
                ],
                "links": [
                    {"source": "concepts/moe.md", "target": "entities/deepseek.md"},
                    ...
                ]
            }
        """
        knowledge_path = Path(self.knowledge_dir)
        if not knowledge_path.is_dir():
            return {"nodes": [], "links": []}

        nodes = {}
        links = []
        link_re = re.compile(r'\[([^\]]*)\]\(([^)]+\.md)\)')

        for md_file in knowledge_path.rglob("*.md"):
            rel = str(md_file.relative_to(knowledge_path))
            if rel in ("index.md", "log.md"):
                continue
            parts = rel.split("/")
            category = parts[0] if len(parts) > 1 else "root"
            title = md_file.stem.replace("-", " ").title()
            try:
                content = md_file.read_text(encoding="utf-8")
                first_line = content.strip().split("\n")[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
                for _, link_target in link_re.findall(content):
                    resolved = (md_file.parent / link_target).resolve()
                    try:
                        target_rel = str(resolved.relative_to(knowledge_path))
                    except ValueError:
                        continue
                    if target_rel != rel:
                        links.append({"source": rel, "target": target_rel})
            except Exception:
                pass
            nodes[rel] = {"id": rel, "label": title, "category": category}

        valid_ids = set(nodes.keys())
        links = [l for l in links if l["source"] in valid_ids and l["target"] in valid_ids]
        seen = set()
        deduped = []
        for l in links:
            key = tuple(sorted([l["source"], l["target"]]))
            if key not in seen:
                seen.add(key)
                deduped.append(l)

        return {"nodes": list(nodes.values()), "links": deduped}

    # ------------------------------------------------------------------
    # dispatch — single entry point for protocol messages
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch a knowledge management action.

        :param action: ``list``, ``read``, or ``graph``
        :param payload: action-specific payload
        :return: protocol-compatible response dict
        """
        payload = payload or {}
        try:
            if action == "list":
                result = self.list_tree()
                return {"action": action, "code": 200, "message": "success", "payload": result}

            elif action == "read":
                path = payload.get("path")
                if not path:
                    return {"action": action, "code": 400, "message": "path is required", "payload": None}
                result = self.read_file(path)
                return {"action": action, "code": 200, "message": "success", "payload": result}

            elif action == "graph":
                result = self.build_graph()
                return {"action": action, "code": 200, "message": "success", "payload": result}

            else:
                return {"action": action, "code": 400, "message": f"unknown action: {action}", "payload": None}

        except ValueError as e:
            return {"action": action, "code": 403, "message": str(e), "payload": None}
        except FileNotFoundError as e:
            return {"action": action, "code": 404, "message": str(e), "payload": None}
        except Exception as e:
            logger.error(f"[KnowledgeService] dispatch error: action={action}, error={e}")
            return {"action": action, "code": 500, "message": str(e), "payload": None}
