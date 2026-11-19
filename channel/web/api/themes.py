"""/api/themes: console themes kept in <workspace>/system/themes.

The same folder the desktop client reads, so a theme made in one shows up in
the other. Each theme is its own folder:

    <id>/
      ├── theme.json      (required)
      ├── wallpaper.jpg   (optional; used even if theme.json omits it)
      └── logo.png        (optional; used even if theme.json omits it)

Image references in theme.json are rewritten to /api/themes/asset URLs; the
console validates everything else, so a malformed theme can only lose fields.
"""

import io
import json
import os
import re
import shutil
import time
import zipfile
from urllib.parse import quote

import web

from channel.web.core._common import (
    _first_value, _multipart_lists, _read_uploaded_file_bytes_limited, _require_auth,
)
from common.log import logger

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
}
# Images picked up from a theme folder when theme.json doesn't name them.
WALLPAPER_FILES = ("wallpaper.jpg", "wallpaper.jpeg", "wallpaper.png", "wallpaper.webp")
LOGO_FILES = ("logo.png", "logo.svg", "logo.webp", "logo.jpg", "logo.jpeg")

MAX_JSON_BYTES = 256 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMPORT_BYTES = 64 * 1024 * 1024
MAX_IMPORT_FILES = 200


def themes_dir() -> str:
    from common.state_dir import themes_dir as _themes_dir
    return str(_themes_dir())


def _ensure_themes_dir() -> str:
    path = themes_dir()
    os.makedirs(path, exist_ok=True)
    return path


def _inside(folder: str, rel: str):
    """Absolute path of ``rel`` inside ``folder``, or None if it escapes."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")):
        return None
    base = os.path.realpath(folder)
    full = os.path.realpath(os.path.join(base, rel))
    return full if full.startswith(base + os.sep) else None


def _image_path(folder: str, rel: str):
    full = _inside(folder, rel)
    if not full or os.path.splitext(full)[1].lower() not in IMAGE_MIME:
        return None
    try:
        size = os.path.getsize(full)
    except OSError:
        return None
    return full if 0 < size <= MAX_IMAGE_BYTES else None


def _asset_url(folder: str, rel: str):
    full = _image_path(folder, rel)
    if not full:
        return None
    rel_path = os.path.relpath(full, os.path.realpath(folder)).replace(os.sep, "/")
    version = int(os.path.getmtime(full))
    return (f"/api/themes/asset?theme={quote(os.path.basename(folder))}"
            f"&file={quote(rel_path)}&v={version}")


def _first_asset(folder: str, names) -> str:
    for name in names:
        url = _asset_url(folder, name)
        if url:
            return url
    return ""


def _link_assets(theme: dict, folder: str) -> None:
    """Point image references at the asset endpoint; drop the ones that don't resolve."""
    # A wallpaper may sit at the top level (shared by both appearances) or
    # under light / dark.
    has_wallpaper = False
    for holder in (theme, theme.get("light"), theme.get("dark")):
        wp = holder.get("wallpaper") if isinstance(holder, dict) else None
        if isinstance(wp, dict) and isinstance(wp.get("image"), str):
            has_wallpaper = True
            url = _asset_url(folder, wp["image"])
            if url:
                wp["image"] = url
            else:
                wp.pop("image", None)
    if not has_wallpaper:
        url = _first_asset(folder, WALLPAPER_FILES)
        if url:
            theme["wallpaper"] = {"image": url, "glass": True}
    identity = theme.get("identity") if isinstance(theme.get("identity"), dict) else None
    if identity and isinstance(identity.get("logo"), str):
        url = _asset_url(folder, identity["logo"])
        if url:
            identity["logo"] = url
        else:
            identity.pop("logo", None)
    else:
        url = _first_asset(folder, LOGO_FILES)
        if url:
            theme["identity"] = {**(identity or {}), "logo": url}


def _read_theme_json(folder: str):
    path = os.path.join(folder, "theme.json")
    try:
        if os.path.getsize(path) > MAX_JSON_BYTES:
            return None
        with open(path, "r", encoding="utf-8-sig") as f:
            theme = json.load(f)
    except (OSError, ValueError):
        return None
    return theme if isinstance(theme, dict) else None


def load_themes() -> list:
    """Every theme in the themes folder, image references linked."""
    root = _ensure_themes_dir()
    themes = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        # Hidden folders are never themes (e.g. an in-progress import).
        if name.startswith(".") or not os.path.isdir(folder):
            continue
        theme = _read_theme_json(folder)
        if theme is None:
            continue
        if not isinstance(theme.get("id"), str) or not theme["id"].strip():
            theme["id"] = name
        _link_assets(theme, folder)
        themes.append(theme)
    return themes


# ---- Import -------------------------------------------------------------------
# A theme can be imported from a .zip, a dropped folder, or its theme.json. The
# package must hold theme.json at its root or inside a single top-level folder.
# Only theme.json and images are kept; anything else (including hidden files
# and macOS __MACOSX metadata) is skipped.

class ThemeImportError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_rel(raw: str):
    """Normalized package-relative path, or None when unsafe or hidden."""
    parts = [p for p in str(raw or "").replace("\\", "/").split("/") if p and p != "."]
    if not parts or str(raw).startswith(("/", "\\")):
        return None
    if any(p == ".." or p.startswith(".") or p == "__MACOSX" or ":" in p for p in parts):
        return None
    return "/".join(parts)


def _is_theme_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == "theme.json" or os.path.splitext(name)[1].lower() in IMAGE_MIME


class _Budget:
    def __init__(self):
        self.bytes = 0
        self.files = 0

    def charge(self, size: int):
        self.bytes += size
        self.files += 1
        if size > MAX_IMAGE_BYTES or self.bytes > MAX_IMPORT_BYTES or self.files > MAX_IMPORT_FILES:
            raise ThemeImportError("too_large")


def _read_zip(data: bytes) -> dict:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ThemeImportError("bad_zip")
    budget = _Budget()
    files = {}
    with archive:
        for info in archive.infolist():
            rel = _safe_rel(info.filename)
            if not rel or info.is_dir() or not _is_theme_file(rel):
                continue
            budget.charge(info.file_size)
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                raise ThemeImportError("bad_zip")
            if len(content) != info.file_size:
                raise ThemeImportError("bad_zip")
            files[rel] = content
    return files


def _root_package(files: dict) -> dict:
    """The files under the folder holding theme.json (root or one level down)."""
    if "theme.json" in files:
        return files
    roots = [k for k in files if re.match(r"^[^/]+/theme\.json$", k)]
    if len(roots) != 1:
        raise ThemeImportError("no_theme")
    prefix = roots[0][: -len("theme.json")]
    return {k[len(prefix):]: v for k, v in files.items() if k.startswith(prefix)}


def collect_upload(uploads) -> tuple:
    """(files, fallback_id) from uploaded (path, bytes) pairs."""
    if len(uploads) == 1 and uploads[0][0].lower().endswith(".zip"):
        name, data = uploads[0]
        fallback = os.path.splitext(os.path.basename(name))[0]
        files = _read_zip(data)
    else:
        budget = _Budget()
        files = {}
        for name, data in uploads:
            rel = _safe_rel(name)
            if not rel or not _is_theme_file(rel):
                continue
            budget.charge(len(data))
            files[rel] = data
        fallback = ""
    if "theme.json" not in files:
        tops = {k.split("/", 1)[0] for k in files if "/" in k}
        if len(tops) == 1:
            fallback = next(iter(tops))
    return _root_package(files), fallback


def _sanitize_id(raw: str) -> str:
    """Theme ids double as folder names, so strip characters no OS accepts there."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", str(raw or ""))
    return re.sub(r"^[\s.-]+", "", cleaned)[:64].strip()


def _find_user_theme(theme_id: str):
    root = themes_dir()
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in names:
        folder = os.path.join(root, name)
        if name.startswith(".") or not os.path.isdir(folder):
            continue
        theme = _read_theme_json(folder)
        if theme is not None and (theme.get("id") or name) == theme_id:
            return folder
    return None


def import_theme(files: dict, fallback_id: str, overwrite: bool, reserved) -> dict:
    """Validate and install a theme. Ids taken by built-ins get a numeric
    suffix; an existing theme with the same id is only replaced when
    ``overwrite`` is set (else ``exists`` is returned so the UI can ask)."""
    raw = files.get("theme.json")
    if raw is None:
        raise ThemeImportError("no_theme")
    try:
        theme = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ThemeImportError("bad_json")
    if not isinstance(theme, dict):
        raise ThemeImportError("bad_json")

    raw_id = theme["id"] if isinstance(theme.get("id"), str) and theme["id"].strip() else fallback_id
    base_id = _sanitize_id(raw_id) or f"theme-{int(time.time())}"
    theme_id = base_id
    n = 2
    while theme_id in reserved:
        theme_id = f"{base_id}-{n}"
        n += 1
    name = theme["name"] if isinstance(theme.get("name"), str) and theme["name"].strip() else theme_id

    existing = _find_user_theme(theme_id)
    if existing and not overwrite:
        return {"status": "exists", "id": theme_id, "name": name}

    root = _ensure_themes_dir()
    staging = os.path.join(root, f".import-{os.getpid()}-{int(time.time() * 1000)}")
    try:
        for rel, data in files.items():
            out = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if rel == "theme.json" and theme.get("id") != theme_id:
                data = json.dumps({**theme, "id": theme_id}, ensure_ascii=False, indent=2).encode("utf-8")
            with open(out, "wb") as f:
                f.write(data)
        if existing:
            shutil.rmtree(existing, ignore_errors=True)
        target = os.path.join(root, theme_id)
        if os.path.exists(target):
            target = f"{target}-{int(time.time())}"
        os.rename(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"status": "ok", "id": theme_id, "name": name}


class ThemesHandler:
    """GET /api/themes -> {themes, dir}."""

    def GET(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            return json.dumps({"status": "success", "themes": load_themes(), "dir": themes_dir()},
                              ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[WebChannel] Theme list error: {e}")
            return json.dumps({"status": "success", "themes": [], "dir": themes_dir()})


class ThemeAssetHandler:
    """GET /api/themes/asset?theme=<folder>&file=<path> -> the image."""

    def GET(self):
        _require_auth()
        params = web.input(theme="", file="")
        folder = _inside(themes_dir(), params.theme) if "/" not in params.theme else None
        path = _image_path(folder, params.file) if folder and not params.theme.startswith(".") else None
        if not path:
            raise web.notfound()
        with open(path, "rb") as f:
            data = f.read()
        web.header('Content-Type', IMAGE_MIME[os.path.splitext(path)[1].lower()])
        # SVGs can carry script; keep them inert when opened directly.
        web.header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'")
        web.header('X-Content-Type-Options', 'nosniff')
        web.header('Cache-Control', 'private, max-age=86400')
        return data


class ThemeImportHandler:
    """POST /api/themes/import (multipart: files[], paths[], overwrite, reserved)."""

    def POST(self):
        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            content_length = int(getattr(web.ctx, "env", {}).get("CONTENT_LENGTH") or 0)
            if content_length > MAX_IMPORT_BYTES + 1024 * 1024:
                return json.dumps({"status": "error", "code": "too_large"})
            params = _multipart_lists(MAX_IMPORT_FILES * 2 + 16)
            uploaded = params.get("files") or []
            # Folder drops carry each file's path in a parallel field:
            # multipart filenames lose directory components.
            paths = params.get("paths") or []
            uploads = []
            for index, file_obj in enumerate(uploaded):
                if file_obj is None or isinstance(file_obj, str):
                    continue
                rel = paths[index] if index < len(paths) and isinstance(paths[index], str) else ""
                rel = rel or getattr(file_obj, "filename", "") or ""
                uploads.append((rel, _read_uploaded_file_bytes_limited(file_obj, MAX_IMPORT_BYTES)))
            if not uploads:
                return json.dumps({"status": "error", "code": "no_theme"})
            reserved = {"default"}
            try:
                reserved.update(str(r) for r in json.loads(_first_value(params, "reserved", "[]") or "[]"))
            except (TypeError, ValueError):
                pass
            overwrite = str(_first_value(params, "overwrite", "")).lower() in ("1", "true")
            files, fallback = collect_upload(uploads)
            return json.dumps(import_theme(files, fallback, overwrite, reserved), ensure_ascii=False)
        except ThemeImportError as e:
            return json.dumps({"status": "error", "code": e.code})
        except ValueError as e:
            if "too large" in str(e):
                return json.dumps({"status": "error", "code": "too_large"})
            logger.warning(f"[WebChannel] Theme import failed: {e}")
            return json.dumps({"status": "error", "code": "failed"})
        except Exception as e:
            logger.warning(f"[WebChannel] Theme import failed: {e}")
            return json.dumps({"status": "error", "code": "failed"})
