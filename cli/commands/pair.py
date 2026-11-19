"""cow pair - Let another device connect to this one, from the terminal.

For servers without a screen: prints a one-time code, a link and a QR code
that the app, the desktop client or another web console redeems, the same as
the code shown under Settings > Devices.
"""

import ipaddress
import json
import os
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

import click

from cli.utils import get_cli_language, get_device_dir

POLL_SECONDS = 2
# Off until the mobile app is published: skips the QR code and the app hint.
MOBILE_PAIRING = False


class _Unreachable(Exception):
    pass


def _read_runtime() -> Optional[dict]:
    from cli.commands.process import _is_pid_alive

    path = os.path.join(get_device_dir(), "console.json")
    try:
        with open(path, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not info.get("url") or not info.get("key"):
        return None
    try:
        if not _is_pid_alive(int(info.get("pid") or 0)):
            return None
    except (TypeError, ValueError):
        return None
    return info


def _call(info: dict, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(info["url"].rstrip("/") + path, data=data, method=method)
    req.add_header("X-Cow-Local-Key", info["key"])
    if data is not None:
        req.add_header("Content-Type", "application/json")
    context = None
    if info["url"].startswith("https://"):
        # Our own process on this machine, under a certificate issued for the
        # public name rather than for the loopback address.
        context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=context) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise _Unreachable(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _Unreachable(str(e)) from e


def _only_private(urls: list) -> bool:
    for url in urls:
        host = urlsplit(url).hostname or ""
        try:
            if ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if not host.endswith(".local"):
                return False
    return True


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - _width(text))


def _print_qr(text: str) -> None:
    try:
        import io
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    try:
        click.echo(buf.getvalue())
    except UnicodeEncodeError:
        pass


@click.command()
@click.option("--url", "url", default="",
              help="Address other devices reach this server at, e.g. http://203.0.113.5:9899")
@click.option("--no-wait", is_flag=True, help="Print the code and exit without waiting")
def pair(url, no_wait):
    """Connect another device to this instance."""
    get_cli_language()
    from common import i18n
    _t = i18n.t

    info = _read_runtime()
    if info is None:
        click.echo(click.style(_t(
            "CowAgent 没有在运行，或未启用网页控制台。先用 cow start 启动。",
            "CowAgent isn't running, or its web console is off. Start it with `cow start`."), fg="red"))
        sys.exit(1)

    try:
        res = _call(info, "POST", "/api/pairing", {"base_url": url.strip()})
    except _Unreachable as e:
        click.echo(click.style(_t(f"无法连接到运行中的实例：{e}",
                                  f"Couldn't reach the running instance: {e}"), fg="red"))
        sys.exit(1)

    if res.get("status") != "success":
        if res.get("reason") == "local_only":
            click.echo(click.style(_t(
                "这个实例只监听 127.0.0.1，其他设备连不上。\n"
                "在 config.json 中设置 web_password（设置后默认监听所有网卡），然后执行 cow restart。",
                "This instance only listens on 127.0.0.1, so no other device can reach it.\n"
                "Set web_password in config.json (it then listens on all interfaces) and run `cow restart`."),
                fg="yellow"))
        else:
            click.echo(click.style(res.get("message") or _t("创建配对码失败", "Couldn't create a pairing code"),
                                   fg="red"))
        sys.exit(1)

    urls = res.get("urls") or []
    instance = res.get("instance") or {}
    minutes = max(1, int(res.get("expires_in") or 300) // 60)
    title = instance.get("name") or "CowAgent"
    if instance.get("version"):
        title += f" (v{instance['version']})"

    click.echo("")
    click.echo(click.style(_t(f"让其他设备连接 · {title}", f"Let another device connect · {title}"), bold=True))
    if MOBILE_PAIRING:
        _print_qr(res.get("link") or "")
        click.echo(_t("  用 CowAgent App 扫码；或在另一台设备的「连接其他设备」中输入：",
                      "  Scan with the CowAgent app, or enter on the other device under \"Connect to a device\":"))
    else:
        click.echo(_t("  在另一台设备的「连接其他设备」中输入：",
                      "  Enter on the other device under \"Connect to a device\":"))
    label_addr, label_code = _t("地址", "Address"), _t("配对码", "Code")
    width = max(_width(label_addr), _width(label_code)) + 2
    for i, address in enumerate(urls):
        click.echo("    " + _pad(label_addr if i == 0 else "", width) + address)
    click.echo("    " + _pad(label_code, width) + click.style(res.get("code") or "", bold=True)
               + click.style(_t(f"   {minutes} 分钟内有效，只能使用一次",
                                f"   valid for {minutes} min, single use"), dim=True))
    click.echo(click.style(_t("  链接：", "  Link: ") + (res.get("link") or ""), dim=True))

    if _only_private(urls):
        click.echo("")
        click.echo(click.style(_t(
            "  这些地址只在同一局域网内可用。设备从别处连接时，用 --url 指定公网地址，"
            "或在 config.json 中设置 web_public_url。",
            "  These addresses only work on the same network. For a device elsewhere, pass --url "
            "with the public address, or set web_public_url in config.json."), fg="yellow"))
    if not res.get("password_set"):
        click.echo(click.style(_t(
            "  未设置 web_password：能访问这个地址的人都能使用控制台，建议先设置密码。",
            "  No web_password is set: anyone who can reach this address can use the console. "
            "Set one first."), fg="yellow"))

    if no_wait:
        return
    click.echo("")
    click.echo(click.style(_t("等待设备连接…（Ctrl+C 退出）", "Waiting for the device… (Ctrl+C to quit)"), dim=True))
    try:
        while True:
            time.sleep(POLL_SECONDS)
            try:
                state = _call(info, "GET", f"/api/pairing/{res['pairing_id']}")
            except _Unreachable:
                continue
            if state.get("state") == "paired":
                device = state.get("device") or {}
                name = device.get("name") or _t("新设备", "New device")
                click.echo(click.style(_t(f"✓ 已连接：{name}", f"✓ Connected: {name}"), fg="green"))
                click.echo(_t("  可在 设置 → 设备 中查看或移除。",
                              "  Review or remove it under Settings > Devices."))
                return
            if state.get("state") == "expired":
                click.echo(click.style(_t("配对码已过期，重新执行 cow pair 获取新的。",
                                          "The code expired. Run `cow pair` again for a new one."), fg="yellow"))
                sys.exit(1)
    except KeyboardInterrupt:
        click.echo("")
