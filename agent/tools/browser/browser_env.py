"""
Browser environment detection and capability resolution.

Centralizes everything about *where* a usable browser engine comes from, so
both the runtime (browser_service) and the installer (cli/commands/install)
agree on the same decisions:

  - Whether the `playwright` Python package is importable.
  - Whether a system Chrome / Edge is installed (Playwright can drive it via
    the `channel="chrome"/"msedge"` launcher, no download needed).
  - Where Playwright's own Chromium download lives (redirected to the writable
    data dir so it survives frozen/desktop app updates).

Resolution priority (see resolve_engine):
  1. system-chrome  -> drive the user's installed Chrome / Edge (zero download)
  2. playwright-chromium -> Playwright's own Chromium, if already downloaded
  3. none -> nothing usable yet; caller should trigger onboarding
"""

import os
import sys
import shutil
from typing import Optional, Dict, Any



# Playwright browser channels we accept for the "system-chrome" mode, in
# preference order. "chrome" covers stable Google Chrome; "msedge" is the
# Chromium-based Edge shipped on every Windows 10/11.
_PREFERRED_CHANNELS = ("chrome", "msedge", "chrome-beta", "msedge-beta")


def get_data_root() -> str:
    """Writable data root (~/.cow on desktop, else CWD-based).

    Mirrors the logic in common/log.py without importing config, to avoid a
    circular import. The desktop build sets COW_DATA_DIR; source deployments
    fall back to the current working directory.
    """
    data_dir = os.environ.get("COW_DATA_DIR")
    if data_dir:
        return os.path.expanduser(data_dir)
    return os.getcwd()


def browsers_download_dir() -> str:
    """Directory Playwright downloads its Chromium into.

    We pin it under the writable data root (~/.cow/ms-playwright) rather than
    Playwright's default (~/.cache/ms-playwright or %USERPROFILE%). This keeps
    the frozen desktop build self-contained and makes the download survive app
    updates. Set as PLAYWRIGHT_BROWSERS_PATH for both install and runtime.
    """
    return os.path.join(get_data_root(), "ms-playwright")


def apply_browsers_path_env() -> None:
    """Point Playwright at our pinned download dir via env var (idempotent).

    Only set it when not already provided by the user, so power users can
    override the location. Must run before importing playwright's launcher.
    """
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_download_dir()


def is_frozen() -> bool:
    """True when running inside a PyInstaller-frozen bundle (desktop backend).

    In this mode sys.executable is the frozen exe (no pip), so the installer
    must skip `pip install` and only download the browser binary.
    """
    return bool(getattr(sys, "frozen", False))


def is_desktop() -> bool:
    """True when running as the Electron desktop client (dev or packaged).

    The desktop shell always sets COW_DESKTOP=1 (see python-manager.ts), both in
    `npm run dev` (runs app.py with the user's Python) and in the packaged build
    (frozen exe). Desktop users have no `cow` CLI, so onboarding must point them
    at the in-chat `/install-browser` command rather than a terminal command.
    """
    return os.environ.get("COW_DESKTOP") == "1"


def has_playwright_package() -> bool:
    """True if the `playwright` Python package can be imported."""
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _windows_program_dirs() -> list:
    dirs = []
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        val = os.environ.get(var)
        if val:
            dirs.append(val)
    return dirs


def detect_system_chrome() -> Optional[Dict[str, str]]:
    """Locate an installed Chromium-based browser Playwright can drive.

    Returns a dict {"channel": <playwright channel>, "path": <exe path>} for
    the first match, or None. The `channel` is what we hand to Playwright's
    launcher; `path` is only informational (Playwright resolves the channel on
    its own, but we keep the path for logging / onboarding messages).
    """
    candidates = []

    if sys.platform == "darwin":
        candidates = [
            ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ("msedge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ("chrome-beta", "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"),
        ]
    elif sys.platform == "win32":
        prog_dirs = _windows_program_dirs()
        for base in prog_dirs:
            candidates.append(("chrome", os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")))
            candidates.append(("msedge", os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")))
    else:
        # Linux: rely on PATH lookups for the common binaries.
        path_lookups = [
            ("chrome", "google-chrome"),
            ("chrome", "google-chrome-stable"),
            ("chrome", "chromium"),
            ("chrome", "chromium-browser"),
            ("msedge", "microsoft-edge"),
        ]
        for channel, binary in path_lookups:
            found = shutil.which(binary)
            if found:
                return {"channel": channel, "path": found}

    for channel, path in candidates:
        if path and os.path.exists(path):
            return {"channel": channel, "path": path}

    return None


def has_downloaded_chromium() -> bool:
    """True if Playwright already has a Chromium download available.

    We check our pinned download dir for a chromium-* folder. This is a
    lightweight heuristic (avoids importing/launching Playwright just to probe)
    and matches how Playwright lays browsers out on disk.
    """
    download_dir = browsers_download_dir()
    if not os.path.isdir(download_dir):
        return False
    try:
        for name in os.listdir(download_dir):
            # Playwright names its browser dirs like "chromium-1140",
            # "chromium_headless_shell-1140".
            if name.startswith("chromium"):
                return True
    except OSError:
        pass
    return False


def resolve_engine(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Decide which browser engine to use, given config and environment.

    Returns a dict describing the launch strategy:
        {
            "mode": "system-chrome" | "playwright-chromium" | "none",
            "channel": Optional[str],   # for system-chrome
            "path": Optional[str],      # for system-chrome (informational)
            "has_playwright": bool,
            "reason": str,              # human-readable, for logging / onboarding
        }

    Config keys under tools.browser that influence this:
      - engine: "auto" (default) | "system-chrome" | "chromium"
          Force a specific engine. "auto" prefers system Chrome, then falls
          back to a downloaded Chromium.
      - prefer_system_browser: bool (default True). When False under "auto",
          skip system Chrome and go straight to Playwright's Chromium.
    """
    config = config or {}
    apply_browsers_path_env()

    has_pw = has_playwright_package()
    engine_pref = str(config.get("engine", "auto")).strip().lower()
    prefer_system = config.get("prefer_system_browser", True)

    if not has_pw:
        return {
            "mode": "none",
            "channel": None,
            "path": None,
            "has_playwright": False,
            "reason": "playwright package not available",
        }

    system = None
    if engine_pref in ("auto", "system-chrome") and prefer_system:
        system = detect_system_chrome()

    if engine_pref == "system-chrome":
        # Explicitly requested: use system Chrome if found, else report none.
        if system:
            return {
                "mode": "system-chrome",
                "channel": system["channel"],
                "path": system["path"],
                "has_playwright": True,
                "reason": f"using system browser ({system['channel']})",
            }
        return {
            "mode": "none",
            "channel": None,
            "path": None,
            "has_playwright": True,
            "reason": "engine=system-chrome but no Chrome/Edge found",
        }

    if engine_pref == "chromium":
        # Explicitly requested Playwright's own Chromium.
        if has_downloaded_chromium():
            return {
                "mode": "playwright-chromium",
                "channel": None,
                "path": None,
                "has_playwright": True,
                "reason": "using downloaded Playwright Chromium",
            }
        return {
            "mode": "none",
            "channel": None,
            "path": None,
            "has_playwright": True,
            "reason": "engine=chromium but Chromium not downloaded yet",
        }

    # auto: system Chrome first, then downloaded Chromium.
    if system:
        return {
            "mode": "system-chrome",
            "channel": system["channel"],
            "path": system["path"],
            "has_playwright": True,
            "reason": f"auto: using system browser ({system['channel']})",
        }
    if has_downloaded_chromium():
        return {
            "mode": "playwright-chromium",
            "channel": None,
            "path": None,
            "has_playwright": True,
            "reason": "auto: using downloaded Playwright Chromium",
        }

    return {
        "mode": "none",
        "channel": None,
        "path": None,
        "has_playwright": True,
        "reason": "no system Chrome/Edge and no downloaded Chromium",
    }


def capability_summary(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """High-level browser capability status, for onboarding / diagnostics.

    Combines resolve_engine with raw detection flags so the UI / tool layer can
    craft a helpful message (e.g. "Chrome detected, click to enable" vs
    "no browser, will download ~150MB").
    """
    engine = resolve_engine(config)
    system = detect_system_chrome()
    return {
        "ready": engine["mode"] != "none",
        "engine": engine,
        "has_playwright": engine["has_playwright"],
        "has_system_chrome": system is not None,
        "system_chrome": system,
        "has_downloaded_chromium": has_downloaded_chromium(),
        "is_frozen": is_frozen(),
        "is_desktop": is_desktop(),
        "browsers_dir": browsers_download_dir(),
    }
