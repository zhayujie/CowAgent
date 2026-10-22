"""Image compression must preserve the displayed orientation of real EXIF images."""

import io

import pytest

from common.utils import compress_imgfile

Image = pytest.importorskip("PIL.Image")

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
    return output


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
def test_compression_preserves_exif_display_geometry_and_corners(orientation):
    source = oriented_jpeg(orientation)
    # Force real JPEG re-encoding through the public byte-budget helper.
    result = compress_imgfile(source, len(source.getvalue()) - 1)
    result.seek(0)
    with Image.open(result) as decoded:
        expected_size = (80, 120) if orientation >= 5 else (120, 80)
        assert decoded.size == expected_size
        assert corners(decoded) == DISPLAY_CORNERS[orientation]
        assert decoded.getexif().get(274, 1) == 1


def test_under_budget_image_is_returned_unchanged():
    source = oriented_jpeg(6)
    original = source.getvalue()
    assert compress_imgfile(source, len(original)) is source
    assert source.getvalue() == original
