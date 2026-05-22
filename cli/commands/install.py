"""cow install-browser - Install Playwright + Chromium for the browser tool."""

import os
import sys
import subprocess
from typing import Callable, Optional

import click

PLAYWRIGHT_VERSION = "1.52.0"
PLAYWRIGHT_LEGACY_VERSION = "1.28.0"
GLIBC_THRESHOLD = (2, 28)
CHINA_MIRROR = "https://registry.npmmirror.com/-/binary/playwright"

# stream(msg, fg=None) — fg is "yellow" | "green" | "red" | None
StreamFn = Callable[[str, Optional[str]], None]
# on_phase(msg) — coarse-grained progress for chat channels (Chinese)
PhaseFn = Callable[[str], None]


def _phase(cb: Optional[PhaseFn], msg: str) -> None:
    if cb:
        cb(msg)


def _has_display() -> bool:
    """Check if a graphical display is available (Linux only)."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _is_headless_linux() -> bool:
    return sys.platform == "linux" and not _has_display()


def _get_installed_version() -> str:
    try:
        out = subprocess.check_output(
            [sys.executable, "-c", "import playwright; print(playwright.__version__)"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return ""


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _get_glibc_version():
    if sys.platform != "linux":
        return None
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        gnu_get_libc_version = libc.gnu_get_libc_version
        gnu_get_libc_version.restype = ctypes.c_char_p
        ver = gnu_get_libc_version().decode()
        parts = ver.split(".")
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _is_china_network() -> bool:
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "config", "get", "global.index-url"],
            stderr=subprocess.DEVNULL,
        )
        url = out.decode().strip().lower()
        return any(kw in url for kw in ("tsinghua", "aliyun", "npmmirror", "douban", "ustc", "huawei", "tencentyun"))
    except Exception:
        return False


def _pip_install(package_spec: str, stream: StreamFn) -> int:
    """Install a package, retrying with --user on permission failure."""
    python = sys.executable
    ret = subprocess.call([python, "-m", "pip", "install", package_spec])
    if ret != 0:
        stream("  Retrying with --user flag...", "yellow")
        ret = subprocess.call([python, "-m", "pip", "install", "--user", package_spec])
    return ret


def _default_stream(msg: str, fg: Optional[str] = None) -> None:
    """CLI: colored click output."""
    if fg == "yellow":
        click.echo(click.style(msg, fg="yellow"))
    elif fg == "green":
        click.echo(click.style(msg, fg="green"))
    elif fg == "red":
        click.echo(click.style(msg, fg="red"))
    else:
        click.echo(msg)


def run_install_browser(
    stream: Optional[StreamFn] = None,
    on_phase: Optional[PhaseFn] = None,
) -> int:
    """
    Install Playwright Python package, optional Linux deps, and Chromium.

    Reused by ``cow install-browser`` CLI and chat ``/install-browser``.

    Args:
        stream: Optional callback ``(message, fg)`` for each line. ``fg`` is
            ``yellow`` / ``green`` / ``red`` or None. Defaults to colored click output.
        on_phase: Optional callback for coarse progress (e.g. push to chat);
            messages are short Chinese status lines.

    Returns:
        0 on success, 1 on fatal failure (pip or chromium install failed).
    """
    stream = stream or _default_stream
    python = sys.executable
    legacy_mode = False

    _phase(on_phase, "🔧 开始安装浏览器工具依赖（约几分钟，请耐心等待）…")

    glibc = _get_glibc_version()
    if glibc and glibc < GLIBC_THRESHOLD:
        legacy_mode = True
        glibc_str = f"{glibc[0]}.{glibc[1]}"
        stream(
            f"glibc {glibc_str} detected (< 2.28). "
            f"Will install playwright {PLAYWRIGHT_LEGACY_VERSION} for compatibility.",
            "yellow",
        )
        stream("  Note: upgrade your OS for full browser tool support.", "yellow")
        stream("")
        _phase(
            on_phase,
            f"ℹ️ 检测到 glibc {glibc_str}（较旧），将安装兼容版 Playwright {PLAYWRIGHT_LEGACY_VERSION}。",
        )

    target_version = PLAYWRIGHT_LEGACY_VERSION if legacy_mode else PLAYWRIGHT_VERSION

    _phase(on_phase, "📦 [1/3] 正在安装 Playwright Python 包…")
    stream("[1/3] Installing playwright Python package...", "yellow")
    ret = _pip_install(f"playwright=={target_version}", stream)
    if ret != 0:
        stream("Failed to install playwright package.", "red")
        _phase(on_phase, "❌ [1/3] Playwright Python 包安装失败。")
        return 1

    installed = _get_installed_version()
    if installed:
        stream(f"  playwright {installed} installed.", "green")
    stream("")
    _phase(on_phase, f"✅ [1/3] Playwright 包已安装（{installed or target_version}）。")

    if sys.platform == "linux":
        _phase(on_phase, "🔧 [2/3] 正在安装 Linux 系统依赖与轻量中文字体（文泉驿正黑，部分步骤可能需要 sudo）…")
        stream("[2/3] Installing system dependencies (Linux)...", "yellow")
        ret = subprocess.call([python, "-m", "playwright", "install-deps", "chromium"])
        if ret != 0:
            stream(
                "  Could not auto-install system deps (may need sudo).\n"
                f"  Run manually: sudo {python} -m playwright install-deps chromium",
                "yellow",
            )
        # Prefer fonts-wqy-zenhei only (~few MB). fonts-noto-cjk is much larger (~150MB+).
        stream("  Installing CJK font (fonts-wqy-zenhei, lightweight)...")
        font_ret = subprocess.call(
            ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "fonts-wqy-zenhei"],
            stderr=subprocess.DEVNULL,
        )
        if font_ret != 0:
            stream(
                "  Could not auto-install CJK font.\n"
                "  Run manually: sudo apt-get install -y fonts-wqy-zenhei\n"
                "  (Optional, larger full coverage: sudo apt-get install -y fonts-noto-cjk)",
                "yellow",
            )
        else:
            subprocess.call(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stream("  CJK font (wqy-zenhei) installed.", "green")
        _phase(
            on_phase,
            "✅ [2/3] Linux 依赖与字体步骤已执行（若有权限问题请查看服务器日志或手动执行提示命令）。",
        )
    else:
        stream(f"[2/3] Skipping system deps (not needed on {sys.platform}).", "yellow")
        _phase(on_phase, f"ℹ️ [2/3] 当前系统（{sys.platform}）跳过 Linux 专用依赖。")
    stream("")

    _phase(on_phase, "🌐 [3/3] 正在下载并安装 Chromium（体积较大，请耐心等待）…")
    stream("[3/3] Installing Chromium browser...", "yellow")
    cmd = [python, "-m", "playwright", "install", "chromium"]

    if _is_headless_linux() and not legacy_mode:
        ver = _version_tuple(installed or "")
        if ver >= (1, 57, 0):
            cmd.append("--only-shell")
            stream("  (headless shell for Linux server)", None)
        else:
            stream("  (full Chromium)", None)
    elif sys.platform == "linux" and _has_display():
        stream("  (full browser for Linux desktop)", None)

    env = os.environ.copy()
    use_mirror = _is_china_network()
    if use_mirror:
        env["PLAYWRIGHT_DOWNLOAD_HOST"] = CHINA_MIRROR
        stream(f"  (using China mirror: {CHINA_MIRROR})", None)
        _phase(on_phase, "📡 检测到国内 pip 源配置，Chromium 将优先走国内镜像下载。")

    ret = subprocess.call(cmd, env=env)

    if ret != 0 and use_mirror:
        stream("  Mirror download failed, retrying with official CDN...", "yellow")
        _phase(on_phase, "⚠️ 镜像下载失败，正在改用官方源重试…")
        env_no_mirror = os.environ.copy()
        env_no_mirror.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        ret = subprocess.call(cmd, env=env_no_mirror)

    if ret != 0:
        stream("Failed to install Chromium.", "red")
        _phase(on_phase, "❌ [3/3] Chromium 安装失败。")
        return 1

    stream("")
    _phase(on_phase, "✅ [3/3] Chromium 已安装。")

    stream("Verifying browser installation...", None)
    _phase(on_phase, "🔍 正在验证 Playwright 能否正常加载…")
    ret = subprocess.call(
        [python, "-c", "from playwright.sync_api import sync_playwright; print('OK')"],
        stderr=subprocess.DEVNULL,
    )
    if ret != 0:
        stream(
            "  Warning: playwright import failed. Browser tool may not work on this system.\n"
            "  Consider upgrading your OS or using Docker.",
            "yellow",
        )
        _phase(on_phase, "⚠️ 验证未完全通过：本机可能仍无法使用浏览器工具，请查看日志或升级系统。")
    else:
        stream("  Verification passed.", "green")
        _phase(on_phase, "✅ 验证通过。")

    stream("")
    stream("Browser tool ready! Restart CowAgent to enable it.", "green")
    _phase(on_phase, "🎉 全部步骤结束。请重启 CowAgent 后使用 browser 工具。")
    return 0


@click.command("install-browser")
def install_browser():
    """Install browser tool dependencies (Playwright + Chromium)."""
    code = run_install_browser()
    if code != 0:
        raise SystemExit(code)
