"""The file system as a visitor sees it.

A visitor never sees a real path. Everything is addressed through a few
virtual mounts:

    /work              this session's own directory, the only writable place
    /work/uploads      files the visitor uploaded
    /data/<name>       each reference directory the owner configured (read-only)
    /skills/<name>     the directory of each skill the profile may use (read-only)

``PathGuard.resolve`` maps a virtual path to a real one and refuses anything
that ends up outside the mount it named: ``..`` segments, symlinks pointing
elsewhere, hard links (which could alias a file outside), writes to read-only
mounts, and private locations the owner may have pointed a mount near. It
fails closed: a path it cannot place is an error, never a pass.

``to_virtual`` goes the other way for text a tool produced, so the absolute
location of the owner's files never reaches the model or the visitor.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from dataclasses import dataclass
from typing import Dict, List, Optional

from agent.guest.policy import in_no_entry, is_within, path_key

WORK = "/work"


class GuestPathError(Exception):
    """A path the visitor may not use. The message is written for the model."""


@dataclass
class Mount:
    vpath: str
    real: str
    writable: bool = False
    check_private: bool = False
    raw: str = ""
    note: str = ""

    @property
    def is_file(self) -> bool:
        return os.path.isfile(self.real)


def _safe_name(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "data"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    taken.add(candidate)
    return candidate


class PathGuard:
    def __init__(self, mounts: List[Mount]):
        self.mounts = sorted(mounts, key=lambda m: len(m.vpath), reverse=True)
        self._keys = {m.vpath: path_key(m.real) for m in self.mounts}
        self._replacements = []
        for m in self.mounts:
            for variant in {m.real, m.raw} - {""}:
                self._replacements.append((variant, m.vpath))
        self._replacements.sort(key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def build(
        cls,
        work_dir: str,
        references: Optional[List[Dict[str, str]]] = None,
        skill_dirs: Optional[Dict[str, str]] = None,
    ) -> "PathGuard":
        mounts = [Mount(WORK, os.path.realpath(work_dir), writable=True, raw=os.path.abspath(work_dir))]
        taken: set = set()
        for ref in references or []:
            path = ref["path"]
            if not os.path.exists(path):
                continue
            name = _safe_name(os.path.basename(path.rstrip("/\\")), taken)
            mounts.append(Mount(
                f"/data/{name}", os.path.realpath(path), check_private=True, raw=os.path.abspath(path),
                note=ref.get("note") or "",
            ))
        taken = set()
        for skill_name, skill_dir in (skill_dirs or {}).items():
            if not os.path.isdir(skill_dir):
                continue
            name = _safe_name(skill_name, taken)
            mounts.append(Mount(f"/skills/{name}", os.path.realpath(skill_dir), raw=os.path.abspath(skill_dir)))
        return cls(mounts)

    @property
    def work_dir(self) -> str:
        return next(m.real for m in self.mounts if m.vpath == WORK)

    def describe(self) -> List[Dict[str, object]]:
        return [{"path": m.vpath, "writable": m.writable, "note": m.note}
                for m in sorted(self.mounts, key=lambda m: m.vpath)]

    def _available(self) -> str:
        names = sorted({m.vpath if not m.vpath.startswith(("/data/", "/skills/")) else m.vpath.rsplit("/", 1)[0]
                        for m in self.mounts})
        return ", ".join(names)

    def to_vpath(self, path: str) -> str:
        """Normalize a visitor-supplied path to an absolute virtual path."""
        if not isinstance(path, str) or not path.strip():
            raise GuestPathError("A path is required.")
        text = path.strip().replace("\\", "/")
        if text.startswith("~") or re.match(r"^[A-Za-z]:", text):
            raise GuestPathError(f"Path not available: {path}. Use paths under {self._available()}.")
        if not text.startswith("/"):
            text = f"{WORK}/{text}"
        text = re.sub(r"^/+", "/", text)
        return posixpath.normpath(text)

    def resolve(self, path: str, write: bool = False) -> str:
        vpath = self.to_vpath(path)
        mount = None
        for m in self.mounts:
            if vpath == m.vpath or vpath.startswith(m.vpath + "/"):
                mount = m
                break
        if mount is None:
            raise GuestPathError(f"Path not available: {path}. Use paths under {self._available()}.")
        if write and not mount.writable:
            raise GuestPathError(f"{mount.vpath} is read-only. Write files under {WORK} instead.")
        rel = vpath[len(mount.vpath):].lstrip("/")
        if rel and mount.is_file:
            raise GuestPathError(f"Path not available: {path}.")
        candidate = os.path.join(mount.real, *rel.split("/")) if rel else mount.real
        real = os.path.realpath(candidate)
        if not is_within(path_key(real), self._keys[mount.vpath]):
            raise GuestPathError(f"Path not available: {path} points outside {mount.vpath}.")
        if mount.check_private and in_no_entry(real):
            raise GuestPathError(f"Path not available: {path}.")
        try:
            st = os.lstat(real)
        except OSError:
            st = None
        if st is not None and stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            raise GuestPathError(f"Path not available: {path} is a hard link.")
        return real

    def virtual_of(self, real: str) -> Optional[str]:
        key = path_key(real)
        for m in self.mounts:
            root = self._keys[m.vpath]
            if is_within(key, root):
                rel = os.path.relpath(os.path.realpath(real), m.real)
                if rel == ".":
                    return m.vpath
                return posixpath.join(m.vpath, rel.replace(os.sep, "/"))
        return None

    def to_virtual(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        for real, vpath in self._replacements:
            if real in text:
                text = text.replace(real + os.sep, vpath + "/").replace(real, vpath)
        return text

    def work_usage_bytes(self) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self.work_dir):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
        return total
