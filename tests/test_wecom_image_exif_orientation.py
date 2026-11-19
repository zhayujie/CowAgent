"""Re-saving a WeCom image must bake the EXIF orientation into the pixels.

``compress_imgfile`` in common/utils.py learned this in #3806, but the
wecom_bot channel kept two private re-save paths that still drop the
orientation: a phone photo re-encoded through either one loses its tag
*and* its pixels, so every viewer renders it sideways.
"""

import io

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from channel.wecom_bot import wecom_bot_channel as mod

Image = pytest.importorskip("PIL.Image")

_ensure_image_format = mod.WecomBotChannel.__wrapped__._ensure_image_format
_compress_image = mod.WecomBotChannel.__wrapped__._compress_image

COLORS = ((240, 20, 20), (20, 220, 20), (20, 20, 240), (230, 220, 20))
# Corners TL, TR, BL, BR after the EXIF display transformation, hand-derived.
DISPLAY_CORNERS = {
    1: (0, 1, 2, 3),
    2: (1, 0, 3, 2),
    3: (3, 2, 1, 0),
    4: (2, 3, 0, 1),
    5: (0, 2, 1, 3),
    6: (2, 0, 3, 1),
    7: (3, 1, 2, 0),
    8: (1, 3, 0, 2),
}


@pytest.fixture
def agent_workspace(tmp_path):
    set_agent_registry(
        AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1")
    )
    yield tmp_path
    # None, not the previous instance: an instance argument re-pins the
    # registry and would leak this workspace into the later tests.
    set_agent_registry(None)


def oriented_jpeg(orientation):
    image = Image.new("RGB", (120, 80))
    for index, color in enumerate(COLORS):
        left, top = (index % 2) * 60, (index // 2) * 40
        image.paste(color, (left, top, left + 60, top + 40))
    exif = Image.Exif()
    exif[274] = orientation
    output = io.BytesIO()
    image.save(output, "JPEG", quality=95, exif=exif)
    output.seek(0)
    return output.getvalue()


def corners(image):
    width, height = image.size
    points = (
        (width // 4, height // 4),
        (3 * width // 4, height // 4),
        (width // 4, 3 * height // 4),
        (3 * width // 4, 3 * height // 4),
    )
    return tuple(
        min(
            range(4),
            key=lambda i: sum(
                (a - b) ** 2 for a, b in zip(image.getpixel(point), COLORS[i])
            ),
        )
        for point in points
    )


@pytest.mark.parametrize("orientation", range(1, 9))
def test_compression_bakes_in_exif_display_geometry(agent_workspace, orientation):
    payload = oriented_jpeg(orientation)
    source = agent_workspace / "src.jpg"
    source.write_bytes(payload)
    # A budget one byte under the source forces a real JPEG re-encode.
    result = _compress_image(str(source), len(payload) - 1)
    assert result, "compression must produce an output file"
    with Image.open(result) as decoded:
        expected_size = (80, 120) if orientation >= 5 else (120, 80)
        assert decoded.size == expected_size
        assert corners(decoded) == DISPLAY_CORNERS[orientation]
        assert decoded.getexif().get(274, 1) == 1


@pytest.mark.parametrize("orientation", range(1, 9))
def test_format_rename_bakes_in_exif_display_geometry(agent_workspace, orientation):
    payload = oriented_jpeg(orientation)
    # A wrong extension forces the rename/copy branch, the only re-save path
    # _ensure_image_format has for an already-supported JPEG.
    source = agent_workspace / "src.dat"
    source.write_bytes(payload)
    result = _ensure_image_format(str(source))
    assert result, "rename must produce an output file"
    with Image.open(result) as decoded:
        expected_size = (80, 120) if orientation >= 5 else (120, 80)
        assert decoded.size == expected_size
        assert corners(decoded) == DISPLAY_CORNERS[orientation]
        assert decoded.getexif().get(274, 1) == 1


def test_supported_jpg_with_matching_extension_is_returned_unchanged(agent_workspace):
    payload = oriented_jpeg(6)
    source = agent_workspace / "keep.jpg"
    source.write_bytes(payload)
    assert _ensure_image_format(str(source)) == str(source)
    assert source.read_bytes() == payload
