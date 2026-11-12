"""Helpers for choosing the native Feishu delivery format for text replies."""

import json
import re
from typing import Callable, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from common.markdown_fence import transform_outside_fences

_BLOCK_MARKDOWN = re.compile(
    r"(?m)^\s{0,3}(?:#{1,6}\s|>\s|[-*+]\s|\d+[.)]\s|```|~~~)"
)
_INLINE_MARKDOWN = re.compile(r"(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^]\n]+\]\([^)\n]+\))")
_TABLE_SEPARATOR = re.compile(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]+)\)")
# An inline code span on one line: a backtick run closed by the next run of the
# same length.
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 3
_MAX_REMOTE_IMAGE_BYTES = 10 * 1024 * 1024


def contains_markdown(text: str) -> bool:
    """Return whether *text* contains syntax that benefits from card Markdown."""
    if not text:
        return False
    return bool(
        _BLOCK_MARKDOWN.search(text)
        or _INLINE_MARKDOWN.search(text)
        or _TABLE_SEPARATOR.search(text)
    )


def build_markdown_card(text: str) -> dict:
    """Build an inline Card 2.0 payload with one Markdown element."""
    return {
        "schema": "2.0",
        "config": {},
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": text,
                }
            ]
        },
    }


def build_text_delivery(text: str) -> Tuple[str, str]:
    """Return the Feishu ``msg_type`` and serialized content for a text reply."""
    if contains_markdown(text):
        return "interactive", json.dumps(build_markdown_card(text), ensure_ascii=False)
    return "text", json.dumps({"text": text}, ensure_ascii=False)


def _outside_code(text: str, transform: Callable[[str], str]) -> str:
    """Apply *transform* to the parts of Markdown *text* outside code blocks
    and inline code spans."""

    def prose(chunk: str) -> str:
        parts = []
        last = 0
        for span in _CODE_SPAN.finditer(chunk):
            parts.append(transform(chunk[last:span.start()]))
            parts.append(span.group(0))
            last = span.end()
        parts.append(transform(chunk[last:]))
        return "".join(parts)

    return transform_outside_fences(text, prose)


def resolve_markdown_images(
    text: str,
    uploader: Callable[[str], Optional[str]],
    max_images: int = 5,
) -> str:
    """Replace remote Markdown image URLs with Feishu image keys.

    Images written inside code blocks or inline code are examples, not images
    to show, so they are left as written and never fetched.
    """
    cache = {}
    uploaded = 0

    def replace(match):
        nonlocal uploaded
        alt = match.group(1).strip() or "image"
        target = match.group(2).strip()
        if target.startswith("img_"):
            return match.group(0)
        if urlparse(target).scheme not in ("http", "https"):
            return match.group(0)

        if target not in cache:
            if uploaded >= max_images:
                cache[target] = None
            else:
                uploaded += 1
                try:
                    cache[target] = uploader(target)
                except Exception:
                    cache[target] = None

        image_key = cache[target]
        if image_key:
            return "![{}]({})".format(alt, image_key)
        return "[Image unavailable: {}]".format(alt)

    return _outside_code(text or "", lambda chunk: _MARKDOWN_IMAGE.sub(replace, chunk))


def validate_public_image_url(url: str) -> None:
    """Reject non-HTTP and non-public image targets before downloading.

    This check is unconditional: image URLs come from the model's Markdown
    reply, while the instance-wide ``web_security_ssrf_protection`` switch
    is off by default. Delegate to the shared guard instead of keeping a
    local copy of the public-IP rule -- the previous copy drifted out of
    sync when the shared rule started rejecting the 100.64.0.0/10 shared
    address space (which hosts Alibaba Cloud's 100.100.100.200 metadata
    endpoint).
    """
    # Imported here so the channel import chain stays free of the tool layer.
    from agent.tools.utils.url_safety import strict_url_guard, validate_url_safe

    with strict_url_guard():
        validate_url_safe(url)


def download_public_image(
    url: str,
    get=requests.get,
    max_bytes: int = _MAX_REMOTE_IMAGE_BYTES,
) -> Tuple[bytes, str]:
    """Download a public image with redirect, type, and size checks."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        validate_public_image_url(current)
        response = get(
            current,
            headers={"User-Agent": "CowAgent/Feishu"},
            timeout=(5, 15),
            allow_redirects=False,
            stream=True,
        )

        if response.status_code in _REDIRECT_CODES:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("image redirect has no location")
            current = urljoin(current, location)
            continue

        if response.status_code != 200:
            response.close()
            raise ValueError("image download returned HTTP {}".format(response.status_code))

        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            response.close()
            raise ValueError("remote resource is not an image")

        try:
            content_length = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            content_length = 0
        if content_length > max_bytes:
            response.close()
            raise ValueError("remote image is too large")

        chunks = []
        downloaded = 0
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise ValueError("remote image is too large")
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks), content_type

    raise ValueError("too many image redirects")


def upload_public_image_to_feishu(
    url: str,
    access_token: str,
    post=requests.post,
    domain="https://open.feishu.cn",
) -> Optional[str]:
    """Download a public image and upload its bytes to Feishu."""
    payload, content_type = download_public_image(url)
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }.get(content_type, "img")
    response = post(
        f"{domain}/open-apis/im/v1/images",
        headers={"Authorization": "Bearer " + access_token},
        data={"image_type": "message"},
        files={
            "image": (
                "markdown-image.{}".format(extension),
                payload,
                content_type,
            )
        },
        timeout=(5, 15),
    )
    body = response.json()
    if body.get("code") != 0:
        return None
    return (body.get("data") or {}).get("image_key")
