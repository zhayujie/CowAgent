#!/usr/bin/env python3
"""
Unified image generation script.

Usage:
    python generate.py '<json_args>'

Supported model families (each provider is tried in priority order:
OpenAI → Gemini → Seedream → Qwen → MiniMax → LinkAI; missing API keys
are skipped, and the provider that natively owns the requested model is
promoted to the front of the queue):

    - gpt-image-2 / gpt-image-1                    → OpenAI
    - nano-banana / gemini-*-image-*               → Gemini
    - doubao-seedream-* / seedream-*               → Seedream (Volcengine Ark)
    - qwen-image-2.0 / qwen-image-2.0-pro / etc.   → Qwen (DashScope)
    - image-01 / minimax-image                     → MiniMax
    - any model                                    → LinkAI (universal proxy)

Dependencies: requests (stdlib: json, sys, os, base64, io, abc, uuid, pathlib, urllib)
"""

import json
import sys
import os
import base64
import io
import time
import uuid
import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlparse
from urllib.error import URLError

try:
    import requests

    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ---------------------------------------------------------------------------
# Size / aspect-ratio resolution
# ---------------------------------------------------------------------------

_SIZE_TABLE = {
    # (tier, ratio) -> "WxH"
    ("1K", "1:1"): "1024x1024",
    ("1K", "3:2"): "1536x1024",
    ("1K", "2:3"): "1024x1536",
    ("2K", "1:1"): "2048x2048",
    ("2K", "16:9"): "2048x1152",
    ("2K", "9:16"): "1152x2048",
    ("4K", "16:9"): "3840x2160",
    ("4K", "9:16"): "2160x3840",
}

_TIER_ORDER = ["1K", "2K", "4K"]
_RATIO_DEFAULT = {"1K": "1:1", "2K": "1:1", "4K": "16:9"}

_PIXEL_RE = re.compile(r"^\d+x\d+$")


def resolve_size(size: str | None, aspect_ratio: str | None) -> str | None:
    """Resolve (size, aspect_ratio) to a concrete 'WxH' string or None."""
    if size and _PIXEL_RE.match(size):
        return size
    if size and size.lower() == "auto":
        size = None
    if not size and not aspect_ratio:
        return None

    tier = size.upper() if size else None
    ratio = aspect_ratio

    if tier and ratio:
        key = (tier, ratio)
        if key in _SIZE_TABLE:
            return _SIZE_TABLE[key]
        # Upgrade: try higher tiers with same ratio
        start = _TIER_ORDER.index(tier) + 1 if tier in _TIER_ORDER else 0
        for t in _TIER_ORDER[start:]:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]
        # Cross-tier: any tier with this ratio
        for t in _TIER_ORDER:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]
        # Tier default
        if tier in _RATIO_DEFAULT:
            return _SIZE_TABLE.get((tier, _RATIO_DEFAULT[tier]))

    if tier and not ratio:
        default_ratio = _RATIO_DEFAULT.get(tier)
        if default_ratio:
            return _SIZE_TABLE.get((tier, default_ratio))

    if ratio and not tier:
        for t in _TIER_ORDER:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]

    return None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _load_image(source: str) -> bytes:
    """Load image from a local file path or URL."""
    if os.path.isfile(source):
        with open(source, "rb") as f:
            return f.read()
    if _HAS_REQUESTS:
        resp = requests.get(source, timeout=60)
        resp.raise_for_status()
        return resp.content
    req = Request(source)
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _compress_image(data: bytes, max_bytes: int = 4 * 1024 * 1024, max_edge: int = 4096) -> bytes:
    """Compress image to fit size/dimension limits. Requires Pillow only when needed."""
    if len(data) <= max_bytes:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if max(w, h) <= max_edge:
                return data
        except ImportError:
            return data
        except Exception:
            return data

    try:
        from PIL import Image
    except ImportError:
        return data

    img = Image.open(io.BytesIO(data))
    w, h = img.size

    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        w, h = int(w * ratio), int(h * ratio)
        img = img.resize((w, h), Image.LANCZOS)

    buf = io.BytesIO()
    fmt = img.format or "PNG"
    if fmt.upper() == "JPEG":
        quality = 85
        while True:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= max_bytes or quality <= 20:
                break
            quality -= 10
    else:
        img.save(buf, format=fmt)
        if buf.tell() > max_bytes:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _save_image(data: bytes, output_dir: str) -> str:
    """Save image bytes to output_dir and return the path."""
    os.makedirs(output_dir, exist_ok=True)
    ext = "png"
    if data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif data[:4] == b"RIFF":
        ext = "webp"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    path = os.path.join(output_dir, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class ImageProvider(ABC):
    """Abstract base class for image generation providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        image_url: str | list | None = None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        """Generate image(s) and return list of local file paths.

        `size` may be a tier ("1K" / "2K" / "4K" / "512") or pixels ("WxH").
        Providers that need pixel sizes should call `resolve_size(size, aspect_ratio)`.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (gpt-image-2, gpt-image-1)
# ---------------------------------------------------------------------------

class OpenAIProvider(ImageProvider):
    """Provider for OpenAI Image API (generations + edits)."""

    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or self.DEFAULT_MODEL

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    @staticmethod
    def _raise_for_api_error(resp):
        """Raise with server error details instead of bare HTTP status."""
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message") or body.get("message") or resp.text
            except Exception:
                msg = resp.text or resp.reason
            raise RuntimeError(f"API {resp.status_code}: {msg} (url: {resp.url})")

    def _post_json(self, url: str, payload: dict) -> dict:
        headers = {**self._headers(), "Content-Type": "application/json"}
        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            self._raise_for_api_error(resp)
            return resp.json()
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers=headers, method="POST")
        with urlopen(req, timeout=300) as r:
            return json.loads(r.read())

    def _post_multipart(self, url: str, fields: dict, files: list[tuple]) -> dict:
        """POST multipart/form-data using requests (or fall back to urllib)."""
        headers = self._headers()
        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, data=fields, files=files, timeout=300)
            self._raise_for_api_error(resp)
            return resp.json()
        boundary = uuid.uuid4().hex
        body = b""
        for key, val in fields.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode()
        for field_name, (filename, filedata, content_type) in files:
            body += (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode() + filedata + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=300) as r:
            return json.loads(r.read())

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        # OpenAI Images API expects pixel size like 1024x1024.
        resolved = resolve_size(size, aspect_ratio) if (size or aspect_ratio) else None
        if image_url:
            return self._edit(prompt, image_url=image_url, quality=quality, size=resolved, output_dir=output_dir)
        return self._create(prompt, quality=quality, size=resolved, output_dir=output_dir)

    def _create(self, prompt: str, *, quality: str | None, size: str | None, output_dir: str) -> list[str]:
        url = f"{self.api_base}/images/generations"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
        }
        if quality:
            payload["quality"] = quality
        if size:
            payload["size"] = size
        result = self._post_json(url, payload)
        return self._save_results(result, output_dir)

    def _edit(
        self,
        prompt: str,
        *,
        image_url,
        quality: str | None,
        size: str | None,
        output_dir: str,
    ) -> list[str]:
        urls = image_url if isinstance(image_url, list) else [image_url]
        image_data_list = [_compress_image(_load_image(u)) for u in urls]

        url = f"{self.api_base}/images/edits"

        fields = {"model": self.model, "prompt": prompt}
        if quality:
            fields["quality"] = quality
        if size:
            fields["size"] = size

        files = []
        for i, img_bytes in enumerate(image_data_list):
            ext = "png"
            if img_bytes[:3] == b"\xff\xd8\xff":
                ext = "jpg"
            field_name = "image[]" if len(image_data_list) > 1 else "image"
            files.append((field_name, (f"image_{i}.{ext}", img_bytes, f"image/{ext}")))

        result = self._post_multipart(url, fields, files)
        return self._save_results(result, output_dir)

    @staticmethod
    def _save_results(result: dict, output_dir: str) -> list[str]:
        paths = []
        for item in result.get("data", []):
            if "b64_json" in item:
                raw = base64.b64decode(item["b64_json"])
                paths.append(_save_image(raw, output_dir))
            elif "url" in item:
                raw = _load_image(item["url"])
                paths.append(_save_image(raw, output_dir))
        return paths


# ---------------------------------------------------------------------------
# LinkAI provider (uses unified /v1/images/generations)
# ---------------------------------------------------------------------------

class LinkAIProvider(ImageProvider):
    """Provider for LinkAI unified image generation API."""

    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or self.DEFAULT_MODEL

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/v1/images/generations"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
        }
        if quality:
            payload["quality"] = quality
        # LinkAI accepts both pixel sizes (1024x1024) and tier shorthand (1K/2K/4K).
        # Pass through whatever the caller gave us; also forward aspect_ratio.
        if size:
            payload["size"] = size
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            resolved = []
            for u in urls:
                if os.path.isfile(u):
                    data = _load_image(u)
                    ext = u.rsplit(".", 1)[-1].lower() if "." in u else "png"
                    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
                    resolved.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
                else:
                    resolved.append(u)
            payload["image_url"] = resolved if len(resolved) > 1 else resolved[0]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("error", {}).get("message") or body.get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        if "error" in result:
            raise RuntimeError(result["error"].get("message", str(result["error"])))

        paths = []
        for item in result.get("data", []):
            if "url" in item:
                raw = _load_image(item["url"])
                paths.append(_save_image(raw, output_dir))
            elif "b64_json" in item:
                raw = base64.b64decode(item["b64_json"])
                paths.append(_save_image(raw, output_dir))
        return paths


# ---------------------------------------------------------------------------
# Gemini provider (Nano Banana family — gemini-*-image-*)
# ---------------------------------------------------------------------------

# Friendly aliases → real Gemini model id
_GEMINI_MODEL_ALIASES = {
    "nano-banana": "gemini-2.5-flash-image",
    "nano-banana-2": "gemini-3.1-flash-image-preview",
    "nano-banana-pro": "gemini-3-pro-image-preview",
}


class GeminiProvider(ImageProvider):
    """Provider for Google Gemini native image generation (Nano Banana family)."""

    DEFAULT_MODEL = "gemini-3.1-flash-image-preview"  # nano-banana-2

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _GEMINI_MODEL_ALIASES.get(model, model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # not used; Gemini has no `quality` param
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        # Build request parts: prompt text + optional inline images
        parts: list[dict] = [{"text": prompt}]
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            for u in urls:
                data = _compress_image(_load_image(u))
                mime = _guess_mime(data)
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(data).decode(),
                    }
                })

        payload: dict = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }

        # Gemini natively supports aspectRatio + imageSize tiers (512/1K/2K/4K).
        _GEMINI_VALID_TIERS = {"512", "1K", "2K", "4K"}
        _GEMINI_TIER_FALLBACK = {"3K": "2K"}
        image_config: dict = {}
        if size:
            if "x" in size.lower():
                tier = _pixels_to_tier(size)
            else:
                tier = size.upper()
            tier = _GEMINI_TIER_FALLBACK.get(tier, tier)
            if tier in _GEMINI_VALID_TIERS:
                image_config["imageSize"] = tier
        if aspect_ratio:
            image_config["aspectRatio"] = aspect_ratio
        elif size and "x" in size.lower():
            ratio = _pixels_to_ratio(size)
            if ratio:
                image_config["aspectRatio"] = ratio
        if image_config:
            payload["generationConfig"]["imageConfig"] = image_config

        url = f"{self.api_base}/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        return self._extract_images(result, output_dir)

    @staticmethod
    def _extract_images(result: dict, output_dir: str) -> list[str]:
        paths: list[str] = []
        for cand in result.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue  # skip thinking-stage interim images
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    raw = base64.b64decode(inline["data"])
                    paths.append(_save_image(raw, output_dir))
        if not paths:
            # Surface the model's text reply (often a refusal explanation)
            for cand in result.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        raise RuntimeError(f"Gemini returned no image: {part['text'][:200]}")
            raise RuntimeError("Gemini returned no image (empty response)")
        return paths


def _guess_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/png"


def _pixels_to_tier(pixel_str: str) -> str:
    """Map 'WxH' to nearest Gemini tier (512 / 1K / 2K / 4K)."""
    try:
        w, h = (int(x) for x in pixel_str.lower().split("x"))
        long_edge = max(w, h)
    except Exception:
        return "1K"
    if long_edge <= 768:
        return "512"
    if long_edge <= 1536:
        return "1K"
    if long_edge <= 3072:
        return "2K"
    return "4K"


def _pixels_to_ratio(pixel_str: str) -> str | None:
    """Map 'WxH' to a Gemini-supported aspect ratio string when possible."""
    try:
        w, h = (int(x) for x in pixel_str.lower().split("x"))
    except Exception:
        return None
    # Reduce to a small ratio
    from math import gcd
    g = gcd(w, h)
    rw, rh = w // g, h // g
    candidate = f"{rw}:{rh}"
    supported = {"1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
                 "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"}
    return candidate if candidate in supported else None


# ---------------------------------------------------------------------------
# Seedream provider (Volcengine Ark, OpenAI-compatible /images/generations)
# ---------------------------------------------------------------------------

# Friendly aliases → real Seedream model id (Ark Model IDs).
_SEEDREAM_MODEL_ALIASES = {
    "seedream": "doubao-seedream-5-0-260128",
    "seedream-lite": "doubao-seedream-5-0-260128",
    "seedream-5.0": "doubao-seedream-5-0-260128",
    "seedream-5.0-lite": "doubao-seedream-5-0-260128",
    "seedream-5-0-lite": "doubao-seedream-5-0-260128",
    "doubao-seedream-5-0": "doubao-seedream-5-0-260128",
    "doubao-seedream-5-0-lite": "doubao-seedream-5-0-260128",
    "seedream-4.5": "doubao-seedream-4-5-251128",
    "seedream-4-5": "doubao-seedream-4-5-251128",
    "doubao-seedream-4-5": "doubao-seedream-4-5-251128",
}

# Seedream supports either a coarse tier ("2K"/"3K"/"4K") or explicit "WxH".
# We pass the user's tier through as-is when valid; otherwise translate ratio
# hints into the recommended pixel sizes from the Ark docs.
# Valid size tiers for Seedream (5.0 lite: 2K/3K, 4.5: 2K/4K).
# Unsupported tiers are mapped to the nearest valid one.
_SEEDREAM_VALID_TIERS = {"2K", "3K", "4K"}
_SEEDREAM_TIER_FALLBACK = {"512": "2K", "1K": "2K"}
_SEEDREAM_SIZE_TABLE = {
    # (tier, ratio) -> "WxH" recommended pixel sizes (Seedream 5.0 lite + 4.5 share most)
    ("2K", "1:1"): "2048x2048",
    ("2K", "3:4"): "1728x2304",
    ("2K", "4:3"): "2304x1728",
    ("2K", "16:9"): "2848x1600",
    ("2K", "9:16"): "1600x2848",
    ("2K", "3:2"): "2496x1664",
    ("2K", "2:3"): "1664x2496",
    ("2K", "21:9"): "3136x1344",
    ("3K", "1:1"): "3072x3072",
    ("3K", "3:4"): "2592x3456",
    ("3K", "4:3"): "3456x2592",
    ("3K", "16:9"): "4096x2304",
    ("3K", "9:16"): "2304x4096",
    ("3K", "2:3"): "2496x3744",
    ("3K", "3:2"): "3744x2496",
    ("3K", "21:9"): "4704x2016",
    ("4K", "1:1"): "4096x4096",
    ("4K", "3:4"): "3520x4704",
    ("4K", "4:3"): "4704x3520",
    ("4K", "16:9"): "5504x3040",
    ("4K", "9:16"): "3040x5504",
    ("4K", "2:3"): "3328x4992",
    ("4K", "3:2"): "4992x3328",
    ("4K", "21:9"): "6240x2656",
}


class SeedreamProvider(ImageProvider):
    """Provider for Volcengine Ark Seedream image generation API.

    The endpoint is OpenAI-compatible (POST {base}/images/generations) but
    accepts an extra `image` field (string or list) for image-to-image and
    multi-image fusion, plus `sequential_image_generation` / `watermark` flags.
    Reference docs accept both `2K` shorthand and explicit `WxH` for `size`.
    """

    DEFAULT_MODEL = "doubao-seedream-5-0-260128"  # seedream 5.0 lite

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _SEEDREAM_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # not honoured by Seedream
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/images/generations"

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "response_format": "url",
            "watermark": False,
        }

        # Default to 2K (Seedream 5.0 lite minimum tier), unless caller picks one.
        seedream_size = self._resolve_seedream_size(size, aspect_ratio)
        if seedream_size:
            payload["size"] = seedream_size

        # Image-to-image / multi-image fusion (up to 14 reference images).
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            prepared: list[str] = []
            for u in urls[:14]:
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    prepared.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
                else:
                    prepared.append(u)
            payload["image"] = prepared if len(prepared) > 1 else prepared[0]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    err = body.get("error") or {}
                    msg = err.get("message") or body.get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        if result.get("error"):
            err = result["error"]
            raise RuntimeError(f"Seedream {err.get('code')}: {err.get('message')}")

        paths: list[str] = []
        for item in result.get("data") or []:
            u = item.get("url")
            b64 = item.get("b64_json")
            if u:
                paths.append(_save_image(_load_image(u), output_dir))
            elif b64:
                paths.append(_save_image(base64.b64decode(b64), output_dir))
        if not paths:
            raise RuntimeError(f"Seedream returned no image: {result}")
        return paths

    @staticmethod
    def _resolve_seedream_size(size: str | None, aspect_ratio: str | None) -> str | None:
        if not size and not aspect_ratio:
            return "2K"
        # Explicit pixel values: pass through (normalise separator)
        if size and "x" in size.lower() and "*" not in size:
            return size.lower()
        if size and "*" in size:
            return size.replace("*", "x")
        tier = (size or "2K").upper()
        # Map unsupported tiers (512, 1K) to the nearest valid one
        tier = _SEEDREAM_TIER_FALLBACK.get(tier, tier)
        if tier not in _SEEDREAM_VALID_TIERS:
            tier = "2K"
        ratio = aspect_ratio or "1:1"
        if (tier, ratio) in _SEEDREAM_SIZE_TABLE:
            return _SEEDREAM_SIZE_TABLE[(tier, ratio)]
        return tier


# ---------------------------------------------------------------------------
# Qwen provider (DashScope multimodal-generation: qwen-image-* family)
# ---------------------------------------------------------------------------

# Friendly aliases → real Qwen model id
_QWEN_MODEL_ALIASES = {
    "qwen": "qwen-image-2.0-pro",
    "qwen-image": "qwen-image-2.0-pro",
    "qwen-image-pro": "qwen-image-2.0-pro",
}

# Qwen pixel-size table (closest match by tier+ratio).
# qwen-image-2.0(*) supports any WxH between 512*512 and 2048*2048.
_QWEN_SIZE_TABLE = {
    # (tier, ratio) -> "W*H"
    ("1K", "1:1"): "1024*1024",
    ("1K", "16:9"): "1280*720",
    ("1K", "9:16"): "720*1280",
    ("1K", "4:3"): "1184*888",
    ("1K", "3:4"): "888*1184",
    ("1K", "3:2"): "1248*832",
    ("1K", "2:3"): "832*1248",
    ("2K", "1:1"): "2048*2048",
    ("2K", "16:9"): "2688*1536",  # exceeds 2048 cap → clamped at runtime if needed
    ("2K", "9:16"): "1536*2688",
    ("2K", "4:3"): "2368*1728",
    ("2K", "3:4"): "1728*2368",
}


class QwenProvider(ImageProvider):
    """Provider for Alibaba DashScope Qwen image API (qwen-image-2.0[-pro])."""

    DEFAULT_MODEL = "qwen-image-2.0"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _QWEN_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # not supported by Qwen image API
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/api/v1/services/aigc/multimodal-generation/generation"

        # Build content array: 0..3 images then a single text part.
        content: list[dict] = []
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            for u in urls[:3]:  # API caps at 3 reference images
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    image_field = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                else:
                    image_field = u
                content.append({"image": image_field})
        content.append({"text": prompt})

        payload: dict = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": content}]},
        }

        # Map (size, aspect_ratio) → Qwen "W*H"
        qwen_size = self._resolve_qwen_size(size, aspect_ratio)
        if qwen_size:
            payload["parameters"] = {"size": qwen_size}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("message") or body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        # Business-level errors arrive on HTTP 200 with a `code` field.
        if result.get("code"):
            raise RuntimeError(f"Qwen {result.get('code')}: {result.get('message')}")

        paths: list[str] = []
        choices = (result.get("output") or {}).get("choices") or []
        for ch in choices:
            for part in ((ch.get("message") or {}).get("content") or []):
                u = part.get("image")
                if u:
                    paths.append(_save_image(_load_image(u), output_dir))
        if not paths:
            raise RuntimeError(f"Qwen returned no image: {result}")
        return paths

    @staticmethod
    def _resolve_qwen_size(size: str | None, aspect_ratio: str | None) -> str | None:
        if not size and not aspect_ratio:
            return None
        if size and "x" in size.lower() and "*" not in size:
            return size.lower().replace("x", "*")
        if size and "*" in size:
            return size
        tier = (size or "1K").upper()
        # Qwen supports 1K and 2K; clamp others
        _QWEN_TIER_MAP = {"512": "1K", "3K": "2K", "4K": "2K"}
        tier = _QWEN_TIER_MAP.get(tier, tier)
        if tier not in ("1K", "2K"):
            tier = "1K"
        ratio = aspect_ratio or "1:1"
        if (tier, ratio) in _QWEN_SIZE_TABLE:
            return _QWEN_SIZE_TABLE[(tier, ratio)]
        return _QWEN_SIZE_TABLE.get((tier, "1:1"))


# ---------------------------------------------------------------------------
# MiniMax provider (image-01 family)
# ---------------------------------------------------------------------------

# Friendly aliases → real MiniMax model id
_MINIMAX_MODEL_ALIASES = {
    "minimax": "image-01",
    "minimax-image": "image-01",
    "minimax-image-01": "image-01",
}

_MINIMAX_SUPPORTED_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


class MinimaxProvider(ImageProvider):
    """Provider for MiniMax image generation API (image-01)."""

    DEFAULT_MODEL = "image-01"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _MINIMAX_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # not supported by MiniMax
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/v1/image_generation"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "response_format": "base64",
        }

        # MiniMax accepts aspect_ratio directly; derive from pixels if needed.
        ratio = aspect_ratio
        if not ratio and size and "x" in size.lower():
            ratio = _pixels_to_ratio(size)
        if ratio and ratio in _MINIMAX_SUPPORTED_RATIOS:
            payload["aspect_ratio"] = ratio

        # Image-to-image uses subject_reference; accept URL or local file (→ base64).
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            refs = []
            for u in urls:
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    image_file = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                else:
                    image_file = u
                refs.append({"type": "character", "image_file": image_file})
            payload["subject_reference"] = refs

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("base_resp", {}).get("status_msg") or body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        # MiniMax returns business errors inside base_resp even on HTTP 200.
        base_resp = result.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            raise RuntimeError(f"MiniMax {base_resp.get('status_code')}: {base_resp.get('status_msg')}")

        data_obj = result.get("data") or {}
        b64_list = data_obj.get("image_base64") or []
        urls_list = data_obj.get("image_urls") or []

        paths: list[str] = []
        for b64 in b64_list:
            paths.append(_save_image(base64.b64decode(b64), output_dir))
        for u in urls_list:
            paths.append(_save_image(_load_image(u), output_dir))
        if not paths:
            raise RuntimeError(f"MiniMax returned no image: {result}")
        return paths


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

# Model-prefix → preferred provider label.
# When the requested model matches a prefix, that provider is promoted to the
# front of the queue. All other configured providers still run as fallbacks.
_MODEL_PREFERRED_PROVIDER: list[tuple[tuple[str, ...], str]] = [
    (("gpt-image",), "OpenAI"),
    (("nano-banana", "gemini-"), "Gemini"),
    (("seedream", "doubao-seedream"), "Seedream"),
    (("qwen-image", "qwen"), "Qwen"),
    (("minimax", "image-01"), "MiniMax"),
]

# Default global priority when the model has no preferred provider.
_DEFAULT_PROVIDER_ORDER = ["OpenAI", "Gemini", "Seedream", "Qwen", "MiniMax", "LinkAI"]


def _preferred_provider(model: str) -> str | None:
    m = (model or "").lower()
    for prefixes, label in _MODEL_PREFERRED_PROVIDER:
        if m.startswith(prefixes):
            return label
    return None


def _build_providers(model: str) -> list[tuple[str, ImageProvider]]:
    """Build an ordered list of (label, provider) to try.

    Behaviour:
      1. All providers with a configured API key are added in the global
         priority order: OpenAI → Gemini → Seedream → Qwen → MiniMax → LinkAI.
      2. If `model` natively belongs to one of the providers AND that provider
         is configured, it is promoted to the front so it gets the first
         attempt with the right model id.
      3. If the preferred provider is NOT configured (no API key), the model
         id would 100% fail on every other backend, so we drop the explicit
         model and fall back to automatic routing — every provider then uses
         its own DEFAULT_MODEL.
    """
    keys = {
        "OpenAI": os.environ.get("OPENAI_API_KEY", ""),
        "Gemini": os.environ.get("GEMINI_API_KEY", ""),
        "Seedream": os.environ.get("ARK_API_KEY", ""),
        "Qwen": os.environ.get("DASHSCOPE_API_KEY", ""),
        "MiniMax": os.environ.get("MINIMAX_API_KEY", ""),
        "LinkAI": os.environ.get("LINKAI_API_KEY", ""),
    }
    bases = {
        "OpenAI": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "Gemini": os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com"),
        "Seedream": os.environ.get("ARK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3"),
        "Qwen": os.environ.get("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com"),
        "MiniMax": os.environ.get("MINIMAX_API_BASE", "https://api.minimaxi.com"),
        "LinkAI": os.environ.get("LINKAI_API_BASE", "https://api.link-ai.tech"),
    }

    pref = _preferred_provider(model)

    # If a specific model is requested and its native provider has no key,
    # other backends won't recognise the id → reset to auto routing.
    if pref and not keys.get(pref):
        model = ""
        pref = None

    factories = {
        "OpenAI": OpenAIProvider,
        "Gemini": GeminiProvider,
        "Seedream": SeedreamProvider,
        "Qwen": QwenProvider,
        "MiniMax": MinimaxProvider,
        "LinkAI": LinkAIProvider,
    }
    available: dict[str, ImageProvider] = {}
    for label, key in keys.items():
        if key:
            available[label] = factories[label](api_key=key, api_base=bases[label], model=model)

    # When a specific model is pinned, only try its native provider — other
    # backends won't recognise the model id so retrying them is pointless.
    if pref and pref in available:
        return [(pref, available[pref])]

    # Auto routing: try every configured provider in priority order.
    ordered: list[str] = []
    for label in _DEFAULT_PROVIDER_ORDER:
        if label in available:
            ordered.append(label)
    return [(label, available[label]) for label in ordered]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python generate.py '<json_args>'"}))
        sys.exit(1)

    try:
        raw = sys.argv[1]
        raw = raw.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
        args = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    prompt = args.get("prompt")
    if not prompt:
        print(json.dumps({"error": "Missing required parameter: prompt"}))
        sys.exit(1)

    # Model resolution priority:
    #   1. Explicit `model` in the call args (agent / user override)
    #   2. SKILL_IMAGE_GENERATION_MODEL env var (synced from
    #      config["skill"]["image-generation"]["model"] at startup)
    #   3. None → fall back to automatic provider routing (try every
    #      provider with a configured API key in global priority order)
    model = args.get("model") or os.environ.get("SKILL_IMAGE_GENERATION_MODEL") or ""
    quality = args.get("quality")
    size = args.get("size")
    aspect_ratio = args.get("aspect_ratio")
    image_url = args.get("image_url")

    output_dir = os.environ.get("IMAGE_OUTPUT_DIR", os.path.join(os.getcwd(), "images"))

    providers = _build_providers(model)
    if not providers:
        target = f"model '{model}'" if model else "image generation"
        print(json.dumps({
            "error": (
                f"No API key configured for {target}. "
                "Set at least one of OPENAI_API_KEY / GEMINI_API_KEY / "
                "ARK_API_KEY / DASHSCOPE_API_KEY / MINIMAX_API_KEY / "
                "LINKAI_API_KEY via the env_config tool, then try again."
            )
        }, ensure_ascii=False))
        sys.exit(1)

    errors = []
    for label, provider in providers:
        try:
            attempt_model = getattr(provider, "model", model) or "auto"
            print(f"[image-generation] Trying {label} (model={attempt_model})...", file=sys.stderr)
            t0 = time.time()
            paths = provider.generate(
                prompt,
                image_url=image_url,
                quality=quality,
                size=size,
                aspect_ratio=aspect_ratio,
                output_dir=output_dir,
            )
            elapsed = time.time() - t0
            # Resolved model id (after alias expansion) actually sent to the API
            actual_model = getattr(provider, "model", model)
            print(
                f"[image-generation] ✅ {label} succeeded in {elapsed:.1f}s "
                f"(model={actual_model})",
                file=sys.stderr,
            )
            result = {
                "model": actual_model,
                "images": [{"url": p} for p in paths],
            }
            print(json.dumps(result, ensure_ascii=False))
            return
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[image-generation] ❌ {label} failed in {elapsed:.1f}s: {e}", file=sys.stderr)
            errors.append(f"{label}: {e}")

    hint = " | ".join(errors)
    print(json.dumps({
        "error": f"All providers failed — {hint}. "
                 "This is likely an API key or base URL configuration issue. "
                 "Do NOT retry with the same parameters. "
                 "Ask the user to verify their API key / base URL "
                 "(OPENAI_API_KEY, GEMINI_API_KEY, ARK_API_KEY, "
                 "DASHSCOPE_API_KEY, MINIMAX_API_KEY, or LINKAI_API_KEY) "
                 "via env_config."
    }, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
