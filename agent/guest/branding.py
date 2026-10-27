"""How a guest page looks: its own logo and accent color.

The logo is a file in the profile directory (``logo.png``, ``logo.jpg`` or
``logo.webp``), served to visitors as an image and nothing else. The accent
color lives in the profile config as ``branding.color``; the page derives a
full palette from it so every shade the console uses has a counterpart.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Dict, Optional, Tuple

COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")
MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_STEM = "logo"
# Raster formats only: an SVG logo could carry script.
LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def sniff_image(data: bytes) -> Optional[str]:
    """The logo extension ``data`` really is, judged by its bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def logo_path(profile_path: str) -> Optional[str]:
    for ext in LOGO_TYPES:
        path = os.path.join(profile_path, LOGO_STEM + ext)
        if os.path.isfile(path):
            return path
    return None


def logo_version(profile_path: str) -> int:
    """Changes whenever the logo does; 0 when the page uses the default."""
    path = logo_path(profile_path)
    if not path:
        return 0
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def read_logo(profile_path: str) -> Optional[Tuple[bytes, str]]:
    """The logo bytes and their content type, if the file is a real image."""
    path = logo_path(profile_path)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_LOGO_BYTES + 1)
    except OSError:
        return None
    ext = sniff_image(data)
    if ext is None or len(data) > MAX_LOGO_BYTES:
        return None
    return data, LOGO_TYPES[ext]


def save_logo(profile_path: str, data: bytes) -> None:
    """Replace the logo. Raises ValueError for anything but a small raster image."""
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("too_large")
    ext = sniff_image(data)
    if ext is None:
        raise ValueError("unsupported")
    os.makedirs(profile_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".logo-", dir=profile_path)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(profile_path, LOGO_STEM + ext))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    for other in LOGO_TYPES:
        if other != ext:
            try:
                os.remove(os.path.join(profile_path, LOGO_STEM + other))
            except FileNotFoundError:
                pass


def remove_logo(profile_path: str) -> None:
    for ext in LOGO_TYPES:
        try:
            os.remove(os.path.join(profile_path, LOGO_STEM + ext))
        except FileNotFoundError:
            pass


def _rgb(color: str) -> Tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(color: str, other: Tuple[int, int, int], amount: float) -> str:
    return _hex(a + (b - a) * amount for a, b in zip(_rgb(color), other))


# Shade -> (mix toward white, mix toward black). The chosen color is 400,
# the shade the console's own accent sits at.
_SHADES = {
    "50": (0.92, 0), "100": (0.84, 0), "200": (0.66, 0), "300": (0.38, 0),
    "400": (0, 0), "500": (0, 0.12), "600": (0, 0.28), "700": (0, 0.42),
    "800": (0, 0.55), "900": (0, 0.65),
}


def palette(color: str) -> Dict[str, str]:
    out = {}
    for shade, (white, black) in _SHADES.items():
        if white:
            out[shade] = _mix(color, (255, 255, 255), white)
        elif black:
            out[shade] = _mix(color, (0, 0, 0), black)
        else:
            out[shade] = color
    return out


def on_color(color: str) -> str:
    """Text color that stays readable on ``color``."""
    r, g, b = (c / 255 for c in _rgb(color))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#0f172a" if luminance > 0.45 else "#ffffff"
