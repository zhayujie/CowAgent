"""Extraction of skill archives, for packages that come from outside.

A skill package is untrusted input wherever it comes from: a hub, a URL, or a
file a browser uploaded. So before anything is written, an entry whose path
leaves the destination - ``../``, an absolute path - aborts the extraction, and
so does anything a tar can carry that is not a plain file or directory: a
symlink or hard link, which names a file the archive does not carry and would
turn the extraction into a write wherever it points, and a device, FIFO or
socket. A zip's link entries are dropped instead of refused, because ``zipfile``
cannot recreate a link in the first place.

Entry counts and the declared uncompressed size are capped as well, which is
what bounds a package before it is written; it is the size the archive declares,
not a decompression-bomb guard.
"""

import os
import stat
import tarfile
import zipfile
from io import BytesIO
from typing import Optional

# Noise the archivers add, dropped rather than refused: a Finder-made zip
# carries __MACOSX and .DS_Store entries that have nothing to do with the skill.
_JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


class ArchiveError(ValueError):
    """An archive was refused, or is not in a format we can read."""


def is_junk_entry(name: str) -> bool:
    """Whether an entry is archiver noise rather than part of the skill."""
    parts = name.replace("\\", "/").split("/")
    return any(p in _JUNK_NAMES or p == "__MACOSX" or p.startswith("._.") for p in parts)


def _check_within(root: str, name: str):
    """Refuse an entry that would be written outside ``root``.

    ``root`` is already resolved, and the join is resolved too, so a symlink
    planted by an earlier entry of the same archive cannot be used to redirect
    a later one.
    """
    resolved = os.path.realpath(os.path.join(root, name))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ArchiveError("Archive contains path traversal, aborting.")


def _check_limits(count: int, total_size: int,
                  max_files: Optional[int], max_total_size: Optional[int]):
    if max_files is not None and count > max_files:
        raise ArchiveError(f"Archive has too many entries: at most {max_files} are accepted.")
    if max_total_size is not None and total_size > max_total_size:
        raise ArchiveError("Archive contents are too large.")


def extract_zip(zf: zipfile.ZipFile, dest: str,
                max_files: Optional[int] = None,
                max_total_size: Optional[int] = None):
    """Extract a zip into ``dest``, refusing the entries described above."""
    root = os.path.realpath(dest)
    members = []
    total_size = 0
    for member in zf.infolist():
        if is_junk_entry(member.filename):
            continue
        _check_within(root, member.filename)
        # A zip records the unix mode in the top half of external_attr, which is
        # how a symlink survives a round trip through a zip at all. Dropped
        # rather than refused: ``zipfile`` does not recreate a link, it writes
        # the target path as the file's contents, so there is no link to escape
        # through - only a file that says nothing the archive actually carries.
        # Repositories do hold the odd symlink, and refusing one would mean
        # refusing to install the whole skill over it.
        if stat.S_ISLNK(member.external_attr >> 16):
            continue
        total_size += member.file_size
        members.append(member)
    _check_limits(len(members), total_size, max_files, max_total_size)
    os.makedirs(dest, exist_ok=True)
    zf.extractall(dest, members=members)


def extract_tar(tf: tarfile.TarFile, dest: str,
                max_files: Optional[int] = None,
                max_total_size: Optional[int] = None):
    """Extract a tar into ``dest``, refusing the entries described above."""
    root = os.path.realpath(dest)
    members = []
    total_size = 0
    for member in tf.getmembers():
        if is_junk_entry(member.name):
            continue
        _check_within(root, member.name)
        if member.issym() or member.islnk():
            raise ArchiveError("Archive contains a link, aborting.")
        if not (member.isfile() or member.isdir()):
            raise ArchiveError("Archive contains a special file, aborting.")
        total_size += member.size
        members.append(member)
    _check_limits(len(members), total_size, max_files, max_total_size)
    os.makedirs(dest, exist_ok=True)
    tf.extractall(dest, members=members)


def extract_archive(content: bytes, dest: str,
                    max_files: Optional[int] = None,
                    max_total_size: Optional[int] = None):
    """Extract archive bytes into ``dest``, whichever format they are in.

    The format is sniffed from the content rather than taken from the file name:
    the name is whatever the uploader called the file, and a ``.zip`` holding a
    gzipped tar is common enough to be worth reading correctly.

    :raises ArchiveError: for an unreadable or refused archive.
    """
    if zipfile.is_zipfile(BytesIO(content)):
        with zipfile.ZipFile(BytesIO(content)) as zf:
            extract_zip(zf, dest, max_files=max_files, max_total_size=max_total_size)
        return

    try:
        tf = tarfile.open(fileobj=BytesIO(content), mode="r:*")
    except tarfile.TarError:
        raise ArchiveError("Unsupported archive format: expected .zip, .tar.gz or .tgz.")
    with tf:
        extract_tar(tf, dest, max_files=max_files, max_total_size=max_total_size)
