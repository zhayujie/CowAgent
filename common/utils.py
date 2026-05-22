import io
import os
import re
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
    while True:
        out_buf = io.BytesIO()
        rgb_image.save(out_buf, "JPEG", quality=quality)
        if fsize(out_buf) <= max_size:
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
    return headers
