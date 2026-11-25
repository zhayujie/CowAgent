"""Public links for an Agent's websites/ dir.

Publishing is off unless ``websites_base_url`` names the URL a static server
exposes the directory at. This module has no optional dependencies, so the
prompt rules and the send tool's public links work in every install.
"""

import os
from typing import Callable, Optional

from common.log import logger
from config import conf

# Subdir under websites/ used by the send tool
COW_SEND_WEB_SUBDIR = "cow-send"

_base_url_fallback: Optional[Callable[[], str]] = None


def set_base_url_fallback(resolver: Optional[Callable[[], str]]) -> None:
    """Register where the websites/ dir is served when ``websites_base_url`` is unset."""
    global _base_url_fallback
    _base_url_fallback = resolver


def _base_url() -> str:
    """Return the URL prefix the websites/ dir is served at."""
    base_url = str(conf().get("websites_base_url") or "").strip().rstrip("/")
    if base_url.startswith(("http://", "https://")):
        return base_url
    if _base_url_fallback is None:
        return ""
    try:
        return _base_url_fallback() or ""
    except Exception as e:
        logger.warning(f"[publish] base url fallback failed: {e}")
        return ""


def _publish_profile(workspace_dir: str = ""):
    """The Agent whose websites/ dir is in play, as (registry, profile).

    Resolved from *workspace_dir* when it names a configured Agent, so callers
    that hold a workspace path do not need an identity. A path that is not one
    (a project directory, say) falls back to the Agent this work belongs to.
    """
    from agent.registry import get_agent_registry
    from common.runtime_identity import current_identity
    from common.utils import expand_path

    registry = get_agent_registry()
    if workspace_dir:
        target = os.path.realpath(expand_path(workspace_dir))
        for profile in registry.list():
            if os.path.realpath(expand_path(profile.workspace)) == target:
                return registry, profile
    return registry, registry.get_or_default(current_identity().agent_id)


def get_publish_dir(workspace_dir: str = "", ensure: bool = False) -> str:
    """Return the directory whose contents the public route serves."""
    from common import state_dir

    try:
        _, profile = _publish_profile(workspace_dir)
        return str(state_dir.websites_dir(base=profile.workspace, ensure=ensure))
    except Exception:
        return str(state_dir.websites_dir(base=workspace_dir or None, ensure=ensure))


def get_publish_base_url(workspace_dir: str = "") -> str:
    """Return the URL prefix that maps to an Agent's websites/ dir.

    Empty unless ``websites_base_url`` or a registered fallback says where it is served.

    The route serves the default Agent's directory at the root, so every other
    Agent is addressed by where its own directory sits relative to the instance
    root. Deriving that from the resolved paths keeps the layout defined in one
    place (state_dir) rather than spelled out again here.
    """
    base = _base_url()
    if not base:
        return ""
    try:
        from common import state_dir

        registry, profile = _publish_profile(workspace_dir)
        if profile.id == registry.default_agent_id:
            return base
        relative = os.path.relpath(
            str(state_dir.websites_dir(base=profile.workspace)),
            str(state_dir.shared_root()),
        ).replace(os.sep, "/")
        if relative.startswith(".."):
            # A workspace placed outside the instance root is not under the
            # route, and answering with the default Agent's prefix would hand
            # out a link to someone else's files.
            return ""
        return f"{base}/{relative}"
    except Exception:
        return base


def _file_digest(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_send_file(src_path: str, workspace_root: str) -> str:
    """Return a public URL for *src_path*, copying it into ``websites/cow-send/``.

    A file already under the websites/ dir is linked in place. Copies are
    named by content hash, so sending the same file again reuses the copy,
    while an edited file gets a new one and earlier links keep their content.

    Returns empty string when publishing is off.
    """
    import shutil
    import tempfile
    from urllib.parse import quote

    base = get_publish_base_url(workspace_root)
    if not base or not src_path or not os.path.isfile(src_path):
        return ""
    publish_dir = get_publish_dir(workspace_root)

    real_src = os.path.realpath(src_path)
    real_publish = os.path.realpath(publish_dir)
    try:
        if os.path.commonpath([real_src, real_publish]) == real_publish:
            relative = os.path.relpath(real_src, real_publish).replace(os.sep, "/")
            return f"{base}/{quote(relative)}"
    except ValueError:
        pass

    send_dir = os.path.join(publish_dir, COW_SEND_WEB_SUBDIR)
    ext = os.path.splitext(src_path)[1].lower()
    if len(ext) > 12 or not ext.replace(".", "").isalnum():
        ext = ""
    tmp_path = ""
    try:
        os.makedirs(send_dir, exist_ok=True)
        dest_name = f"{_file_digest(src_path)[:32]}{ext}"
        dest_path = os.path.join(send_dir, dest_name)
        if not (os.path.isfile(dest_path) and os.path.getsize(dest_path) == os.path.getsize(src_path)):
            # Copy then rename, so a concurrent send never serves a partial file.
            fd, tmp_path = tempfile.mkstemp(dir=send_dir, prefix=".tmp-")
            os.close(fd)
            shutil.copy2(src_path, tmp_path)
            os.replace(tmp_path, dest_path)
            tmp_path = ""
    except OSError as e:
        logger.warning(f"[publish] copy_send_file: copy failed: {e}")
        return ""
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return f"{base}/{COW_SEND_WEB_SUBDIR}/{dest_name}"


def _display_path(path: str) -> str:
    """Spell an absolute path the short way the Agent is used to seeing."""
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    return path.replace(os.sep, "/")


def build_publish_prompt(workspace_dir: str) -> list:
    """Build system prompt lines for the website/file sharing rules.

    Returns an empty list when the websites/ dir has no public address,
    so callers can safely do ``lines.extend(build_publish_prompt(...))``.

    The directory is named absolutely rather than as a bare ``websites/``: each
    Agent has its own, and a relative path would also resolve into the project
    directory in a project-mode session, where nothing is served.
    """
    base_url = get_publish_base_url(workspace_dir)
    if not base_url:
        return []
    pub = _display_path(get_publish_dir(workspace_dir))

    return [
        "**文件分享与网页生成规则** (非常重要):",
        "",
        f"工作空间的 `{pub}/` 目录已配置公网访问，访问地址前缀为: `{base_url}`",
        "",
        "该目录下的文件任何拿到链接的人都能打开，**不要**放入密钥、配置文件或隐私数据",
        "",
        f"1. **网页/网站**: 编写网页、H5页面等前端代码时，**必须**将文件放到 `{pub}/` 目录中",
        f"   - 例如: `{pub}/index.html` → `{base_url}/index.html`",
        f"   - 例如: `{pub}/my-app/index.html` → `{base_url}/my-app/index.html`",
        "",
        f"2. **生成文件分享** (PPT、PDF、图片、音视频等): 当你为用户生成了需要下载或查看的文件时，**可以**将文件保存到 `{pub}/` 目录中",
        f"  - 例如: 生成的PPT保存到 `{pub}/files/report.pptx` → 下载链接为 `{base_url}/files/report.pptx`",
        "   - 你仍然可以同时使用 `send` 工具发送文件（在微信、飞书、钉钉、web等渠道中有效），但**必须同时在回复文本中提供下载链接**作为兜底，因为部分渠道无法通过 send 接收本地文件",
        "",
        "3. **必须发送链接**: 无论是网页还是文件，生成后**必须将完整的访问/下载链接直接写在回复文本中发送给用户**",
        "",
        "4. **文件名和路径尽量使用英文/拼音/数字等**，不要使用中文，避免链接无法访问",
        "",
        f"5. 建议为每个独立项目在 `{pub}/` 下创建子目录，保持结构清晰",
        "",
    ]
