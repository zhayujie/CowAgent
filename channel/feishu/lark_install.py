"""
On-demand provisioning of the ``lark_oapi`` SDK (Feishu channel).

Why this exists
---------------
The desktop client (PyInstaller build) intentionally does **not** bundle
``lark_oapi``: the published SDK is ~122MB unpacked because it ships models for
all 59 Feishu open-platform domains, which is why the channel was dropped from
the desktop build (see zhayujie/CowAgent#2987 — "客户端没有飞书通道").

Instead the first time a user enables Feishu in desktop mode we fetch a trimmed,
pure-Python bundle (~1MB) built by ``desktop/build/build-feishu-vendor.py``,
unpack it into a writable per-user directory and put that on ``sys.path``. The
bundle is published once per SDK version and mirrored (see ``VENDOR_URLS``).

Running ``pip`` at this point is not an option: the frozen app has no real
Python interpreter — ``sys.executable`` is the bundled backend itself — so
``sys.executable -m pip`` does not behave like pip. Unpacking a prebuilt archive
needs nothing but the import machinery, which works normally in a frozen build.

For source / non-desktop installs ``lark_oapi`` comes from ``requirements.txt``
and this module simply confirms it is importable.
"""
import hashlib
import importlib
import importlib.util
import io
import logging
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

from common.deployment import is_desktop

try:
    from common.log import logger
except Exception:  # pragma: no cover - common may be unavailable in isolation
    logger = logging.getLogger("feishu_lark_install")

LARK_PKG = "lark-oapi"
LARK_MIN = "1.5.5"

# Bumped whenever a new bundle is published: "<lark version>-<bundle revision>".
VENDOR_VERSION = "1.7.1-1"

# sha256 of the published archive. The builder emits a byte-identical zip for a
# given version, so this pin is stable; it is what makes the download safe to
# trust. Leave empty only for local experiments (verification is then skipped
# with a warning).
VENDOR_SHA256 = "a96de70291e43b4829a5f717035806835f116bf4dc1d0a2d2ed551908a825381"

# Tried in order; the same mirrors the desktop installers use. Feishu is a
# China-only product, so the domestic CDN comes first. Any mirror is safe
# because the payload is checked against VENDOR_SHA256.
VENDOR_URLS = (
    "https://cdn.link-ai.tech/desktop/vendor/feishu-vendor-{version}.zip",
    "https://cdn.cowagent.ai/desktop/vendor/feishu-vendor-{version}.zip",
)

DOWNLOAD_TIMEOUT = 120

# Per-user, writable, persistent location. Mirrors the browser tool's ~/.cow
# layout so everything CowAgent owns lives under one roof.
_VENDOR_SUBDIR = os.path.join(".cow", "feishu_vendor")


def _install_error(reason: str = "") -> ImportError:
    detail = f" ({reason})" if reason else ""
    return ImportError(
        f"lark_oapi is required for the Feishu channel but is not available{detail}. "
        f"Install it with: pip install -U '{LARK_PKG}>={LARK_MIN}'"
    )


def vendor_dir() -> str:
    """Return the directory the trimmed SDK is unpacked into.

    Versioned so a newer bundle never has to overwrite a directory that a
    running process may still be importing from.
    """
    base = os.environ.get("COW_DATA_DIR") or os.path.expanduser("~")
    return os.path.join(base, _VENDOR_SUBDIR, VENDOR_VERSION)


def vendor_urls() -> list:
    """Candidate download URLs, most preferred first."""
    override = os.environ.get("COW_FEISHU_VENDOR_URL")
    if override:
        return [override]
    return [url.format(version=VENDOR_VERSION) for url in VENDOR_URLS]


def is_available() -> bool:
    """True if lark_oapi can be imported right now."""
    return importlib.util.find_spec("lark_oapi") is not None


def needs_download() -> bool:
    """True if enabling Feishu would have to fetch the bundle first.

    Lets the UI warn about the one-time wait before it happens; ``ensure``
    re-checks anyway, so a stale answer only costs a misplaced hint.
    """
    return not is_available() and not os.path.isdir(vendor_dir())


def _activate(path: str) -> bool:
    """Put an unpacked bundle on sys.path and report whether it took effect."""
    if not os.path.isdir(path):
        return False
    if path not in sys.path:
        sys.path.insert(0, path)
        # find_spec consults cached finders, which were populated before the
        # directory existed.
        importlib.invalidate_caches()
    return is_available()


def _fetch(url: str) -> bytes:
    logger.info("[FeiShu] downloading Feishu SDK bundle from %s", url)
    # The overseas mirror sits behind a CDN that answers 403 to urllib's default
    # User-Agent, so an unnamed request only ever reaches the China mirror.
    req = urllib.request.Request(url, headers={"User-Agent": "CowAgent"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        return resp.read()


def _verify(payload: bytes) -> None:
    if not VENDOR_SHA256:
        logger.warning("[FeiShu] VENDOR_SHA256 is unset; skipping integrity check")
        return
    digest = hashlib.sha256(payload).hexdigest()
    if digest != VENDOR_SHA256:
        raise ValueError(f"checksum mismatch: expected {VENDOR_SHA256}, got {digest}")


def _safe_extract(payload: bytes, dest: str) -> None:
    """Unpack the archive, refusing entries that escape ``dest``."""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            target = os.path.realpath(os.path.join(dest, name))
            if not target.startswith(os.path.realpath(dest) + os.sep):
                raise ValueError(f"refusing to extract outside the vendor dir: {name}")
        zf.extractall(dest)


def _download() -> bytes:
    """Fetch the bundle, falling back through the mirrors on failure."""
    last = None
    for url in vendor_urls():
        try:
            payload = _fetch(url)
            _verify(payload)
            return payload
        except Exception as exc:
            last = exc
            logger.warning("[FeiShu] could not fetch the bundle from %s: %s", url, exc)
    raise last


def _provision(target: str) -> None:
    """Download and unpack the bundle into ``target`` atomically."""
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    payload = _download()

    staging = tempfile.mkdtemp(prefix=".incomplete-", dir=parent)
    try:
        _safe_extract(payload, staging)
        try:
            os.rename(staging, target)
        except OSError:
            # Another process won the race, or the platform refuses to rename
            # onto an existing directory; its copy is equivalent.
            if not os.path.isdir(target):
                raise
            shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def ensure(allow_install: bool = True) -> None:
    """Make ``lark_oapi`` importable, fetching the bundle if needed.

    - Already importable (source install, or a previous download): return.
    - Desktop mode with ``allow_install``: download the trimmed bundle and add
      it to ``sys.path``.
    - Otherwise: raise ``ImportError`` with actionable guidance.
    """
    if is_available():
        return

    target = vendor_dir()
    # A previous run may have already unpacked it.
    if _activate(target):
        return

    if not allow_install:
        raise _install_error()

    # Source / non-desktop installs get it from requirements.txt.
    if not is_desktop():
        raise _install_error()

    logger.warning(
        "[FeiShu] Feishu SDK not present; fetching the bundle into %s. "
        "This happens once and needs a network connection.", target,
    )
    try:
        _provision(target)
    except Exception as exc:
        logger.error("[FeiShu] failed to provision the Feishu SDK bundle: %s", exc)
        raise _install_error(str(exc)) from exc

    if not _activate(target):
        raise _install_error("bundle unpacked but lark_oapi is still not importable")
    logger.info("[FeiShu] Feishu SDK bundle ready at %s", target)
