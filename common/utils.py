import io
import os
import re
import sys
from contextvars import ContextVar
from typing import Optional
from urllib.parse import urlparse
from common.log import logger

def fsize(file):
    if isinstance(file, io.BytesIO):
        return file.getbuffer().nbytes
    elif isinstance(file, str):
        return os.path.getsize(file)
    elif hasattr(file, "seek") and hasattr(file, "tell"):
        pos = file.tell()
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(pos)
        return size
    else:
        raise TypeError("Unsupported type")


def compress_imgfile(file, max_size):
    if fsize(file) <= max_size:
        return file
    from PIL import Image
    file.seek(0)
    img = Image.open(file)
    rgb_image = img.convert("RGB")
    quality = 95
    min_quality = 10
    while True:
        out_buf = io.BytesIO()
        rgb_image.save(out_buf, "JPEG", quality=quality)
        if fsize(out_buf) <= max_size or quality <= min_quality:
            # Stop at min_quality: further decrements would pass an invalid
            # quality (<1) to PIL and the loop would otherwise never terminate
            # for images that cannot be compressed below max_size.
            return out_buf
        quality -= 5


def split_string_by_utf8_length(string, max_length, max_split=0):
    encoded = string.encode("utf-8")
    start, end = 0, 0
    result = []
    while end < len(encoded):
        if max_split > 0 and len(result) >= max_split:
            result.append(encoded[start:].decode("utf-8"))
            break
        end = min(start + max_length, len(encoded))
        # 如果当前字节不是 UTF-8 编码的开始字节，则向前查找直到找到开始字节为止
        while end < len(encoded) and (encoded[end] & 0b11000000) == 0b10000000:
            end -= 1
        result.append(encoded[start:end].decode("utf-8"))
        start = end
    return result


def get_path_suffix(path):
    path = urlparse(path).path
    return os.path.splitext(path)[-1].lstrip('.')


def convert_webp_to_png(webp_image):
    from PIL import Image
    try:
        webp_image.seek(0)
        img = Image.open(webp_image).convert("RGBA")
        png_image = io.BytesIO()
        img.save(png_image, format="PNG")
        png_image.seek(0)
        return png_image
    except Exception as e:
        logger.error(f"Failed to convert WEBP to PNG: {e}")
        raise


def remove_markdown_symbol(text: str):
    # 移除markdown格式，目前先移除**
    if not text:
        return text
    return re.sub(r'\*\*(.*?)\*\*', r'\1', text)


def expand_path(path: str) -> str:
    """
    Expand user path with proper Windows support.
    
    On Windows, os.path.expanduser('~') may not work properly in some shells (like PowerShell).
    This function provides a more robust path expansion.
    
    Args:
        path: Path string that may contain ~
        
    Returns:
        Expanded absolute path
    """
    if not path:
        return path
    
    # Try standard expansion first
    expanded = os.path.expanduser(path)
    
    # If expansion didn't work (path still starts with ~), use HOME or USERPROFILE
    if expanded.startswith('~'):
        import platform
        if platform.system() == 'Windows':
            # On Windows, try USERPROFILE first, then HOME
            home = os.environ.get('USERPROFILE') or os.environ.get('HOME')
        else:
            # On Unix-like systems, use HOME
            home = os.environ.get('HOME')
        
        if home:
            # Replace ~ with home directory
            if path == '~':
                expanded = home
            elif path.startswith('~/') or path.startswith('~\\'):
                expanded = os.path.join(home, path[2:])
    
    return expanded


def is_cloud_deployment() -> bool:
    if os.environ.get("CLOUD_DEPLOYMENT_ID"):
        return True
    try:
        from config import conf
        if conf().get("cloud_deployment_id"):
            return True
    except Exception:
        pass
    return False


# Above this value a reported memory limit means "unlimited" rather than a real
# cap (the kernel exposes a near-64-bit sentinel when no limit is set).
_NO_MEMORY_LIMIT_THRESHOLD = 1 << 53


def _read_int_file(path: str):
    try:
        with open(path, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _read_stat_file(path: str) -> dict:
    """Parse a whitespace-separated ``key value`` file into {key: int}."""
    stats = {}
    try:
        with open(path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        stats[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        pass
    return stats


def memory_headroom_mb():
    """MB of additional memory a new child process can claim, or None.

    Returns None when the runtime enforces no memory limit — the normal case for
    a plain install, where the caller should skip any budget check.

    Only unreclaimable memory (anonymous pages, unevictable pages, kernel slab)
    counts as used. Page cache is deliberately excluded: it grows to fill the
    whole limit and is dropped on demand, so counting it would make the headroom
    look permanently exhausted.
    """
    # Unified hierarchy (cgroup v2).
    limit = _read_int_file("/sys/fs/cgroup/memory.max")
    if limit is not None:
        stats = _read_stat_file("/sys/fs/cgroup/memory.stat")
        used = (
            stats.get("anon", 0)
            + stats.get("unevictable", 0)
            + stats.get("slab_unreclaimable", 0)
        )
    else:
        # Legacy hierarchy (cgroup v1).
        limit = _read_int_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        if limit is None:
            return None
        stats = _read_stat_file("/sys/fs/cgroup/memory/memory.stat")
        used = stats.get("total_rss", stats.get("rss", 0))

    if limit >= _NO_MEMORY_LIMIT_THRESHOLD:
        return None
    return max(0.0, (limit - used) / (1024 * 1024))


def apply_cloud_user(headers: dict) -> dict:
    """
    Tag *headers* with the console user driving this request, when there is one.

    Read through sys.modules so purely local runs, where the cloud client is
    never imported, stay untouched.
    """
    module = sys.modules.get("common.cloud_client")
    user_id = module.current_user_id() if module else None
    if user_id:
        headers["X-User-Id"] = user_id
    return headers


def _deployment_id() -> str:
    """Server-side deployment id, or '' when unset."""
    dep = os.environ.get("CLOUD_DEPLOYMENT_ID", "")
    if dep:
        return dep
    try:
        from config import conf
        return conf().get("cloud_deployment_id", "") or ""
    except Exception:
        return ""


def get_client_source() -> str:
    """Coarse runtime origin, for stats only. First match wins."""
    if _deployment_id():
        return "cloud"
    explicit = (os.environ.get("COW_CLIENT_SOURCE") or "").strip()
    if explicit:
        return explicit
    if os.environ.get("COW_DESKTOP") == "1":
        return "desktop"
    return "open-source"


def _client_os() -> str:
    """Coarse OS family (mac / windows / linux), for stats only."""
    p = sys.platform
    if p.startswith("darwin"):
        return "mac"
    if p.startswith("win"):
        return "windows"
    if p.startswith("linux"):
        return "linux"
    return p or ""


_run_id: "ContextVar[Optional[str]]" = ContextVar("agent_run_id", default=None)


def set_agent_run_id(run_id: Optional[str]):
    value = str(run_id).strip() if run_id is not None and str(run_id).strip() else None
    return _run_id.set(value)


def clear_agent_run_id(token) -> None:
    try:
        _run_id.reset(token)
    except Exception:
        pass


def apply_client_source(headers: dict) -> dict:
    """Tag headers with the runtime origin (and deployment id when set)."""
    headers["X-Client-Source"] = get_client_source()
    os_family = _client_os()
    if os_family:
        headers["X-Client-OS"] = os_family
    version = (os.environ.get("COW_CLIENT_VERSION") or "").strip()
    if version:
        headers["X-Client-Version"] = version
    run_id = _run_id.get()
    if run_id:
        headers["X-Agent-Run-Id"] = run_id
    dep = _deployment_id()
    if dep:
        headers["X-Deployment-Id"] = dep
    return headers


def get_cloud_headers(api_key: str) -> dict:
    """
    Build standard headers for LinkAI API requests,
    including client_id when available.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        from linkai import LinkAIClient
        client_id = LinkAIClient.fetch_client_id()
        if client_id:
            headers["X-Client-Id"] = client_id
    except Exception:
        pass
    apply_client_source(headers)
    return apply_cloud_user(headers)
