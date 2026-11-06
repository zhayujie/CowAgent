"""Oversized images are compressed even where neither sips nor ImageMagick runs.

That is Windows, where a bare "convert" is System32's FAT-to-NTFS volume
converter, and the Docker image, which installs no ImageMagick. Every command
_maybe_compress launches fails here as if it were missing, so the result doesn't
depend on what the machine running the suite has installed.
"""

import base64
import io
import os
import sys

import pytest
from PIL import Image, ImageStat

from agent.tools.vision import vision as vision_module
from agent.tools.vision.vision import COMPRESS_THRESHOLD, Vision


@pytest.fixture
def launched(monkeypatch):
    commands = []

    def missing(cmd, **kwargs):
        commands.append(cmd[0])
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(vision_module.subprocess, "run", missing)
    return commands


def _send(path):
    """Return the data URL header and image bytes the vision request would carry."""
    before = path.read_bytes()
    assert len(before) > COMPRESS_THRESHOLD
    url = Vision()._build_image_content(str(path))["image_url"]["url"]
    assert path.read_bytes() == before
    header, data = url.split(",", 1)
    return header, base64.b64decode(data)


@pytest.mark.parametrize("size,expected", [
    ((4000, 300), (3072, 230)),
    ((1100, 1100), (1100, 1100)),
])
def test_oversized_png_is_sent_as_a_jpeg_under_the_threshold(tmp_path, launched, size, expected):
    path = tmp_path / "screenshot.png"
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(path)
    header, sent = _send(path)
    assert header == "data:image/jpeg;base64"
    assert len(sent) <= COMPRESS_THRESHOLD
    with Image.open(io.BytesIO(sent)) as image:
        assert image.format == "JPEG"
        assert image.size == expected


def test_rotated_photo_stays_upright(tmp_path, launched):
    # Phones save a portrait photo as landscape pixels plus an EXIF Orientation tag.
    path = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise for display
    Image.frombytes("RGB", (4000, 1000), os.urandom(4000 * 1000 * 3)).save(path, quality=95, exif=exif)
    _, sent = _send(path)
    with Image.open(io.BytesIO(sent)) as image:
        assert image.size == (768, 3072)


@pytest.mark.parametrize("mode", ["RGBA", "RGB"])
def test_transparent_areas_turn_white_not_black(tmp_path, launched, mode):
    path = tmp_path / "diagram.png"
    if mode == "RGBA":
        image = Image.frombytes("RGBA", (1100, 1100), os.urandom(1100 * 1100 * 4))
        image.paste((0, 0, 0, 0), (0, 0, 64, 64))  # fully transparent, stored as black
        image.save(path)
    else:
        # An RGB PNG whose tRNS chunk makes black transparent.
        image = Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3))
        image.paste((0, 0, 0), (0, 0, 64, 64))
        image.save(path, transparency=(0, 0, 0))
    _, sent = _send(path)
    with Image.open(io.BytesIO(sent)) as image:
        assert min(image.getpixel((32, 32))) >= 250


def test_16_bit_grayscale_is_scaled_not_clipped_to_white(tmp_path, launched):
    path = tmp_path / "scan.png"
    Image.frombytes("I;16", (1500, 1500), os.urandom(1500 * 1500 * 2)).save(path)
    _, sent = _send(path)
    with Image.open(io.BytesIO(sent)) as image:
        assert 100 < ImageStat.Stat(image.convert("L")).mean[0] < 155


def test_windows_never_launches_system32_convert(tmp_path, launched, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    path = tmp_path / "screenshot.png"
    Image.frombytes("RGB", (4000, 300), os.urandom(4000 * 300 * 3)).save(path)
    header, _ = _send(path)
    assert "convert" not in launched
    assert header == "data:image/jpeg;base64"
