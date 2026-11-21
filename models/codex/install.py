"""Install the official Codex CLI into the current CowAgent instance."""

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

VERSION = "0.171.0"
_RELEASE = f"https://github.com/openai/codex/releases/download/rust-v{VERSION}/"
# SHA-256 digests of the official release assets. Update them with VERSION.
_ASSETS = {
    "x86_64-unknown-linux-musl": "01baa2e47809f8597be5b2f8abd4e4dfe3fb5bcb6e504c2fbaaad97056c15e8d",
    "aarch64-unknown-linux-musl": "bcf50b836385e51bd2976ab2bbe92b1b08a1cbe37712eb8dbe378aa78d24871c",
    "x86_64-apple-darwin": "6f9b1144ffaa64aa12bf30f312405b266b84c433bae9f070be10245762c7aa44",
    "aarch64-apple-darwin": "9414c8c967f110b11e8324c0cfa2b20f012094ef890110a561c92ee535a2681a",
    "x86_64-pc-windows-msvc": "4cfd8acd6dd74ccba36393c33b460907e907a8c19051e16a0d0a9783ae0246c5",
    "aarch64-pc-windows-msvc": "6c1e4aff77eff3653e444f633922ea05f773f43e791f79ec6de33c44a2ca4577",
}
_SYSTEMS = {"Linux": "unknown-linux-musl", "Darwin": "apple-darwin", "Windows": "pc-windows-msvc"}
_ARCHES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}
_MAX_ARCHIVE = 160 * 1024 * 1024
_MAX_BINARY = 450 * 1024 * 1024


class InstallError(RuntimeError):
    pass


def _binary_name():
    return "codex.exe" if os.name == "nt" else "codex"


def find_codex(home):
    managed = home / "bin" / _binary_name()
    if managed.is_file() and os.access(managed, os.X_OK):
        return str(managed.resolve())
    external = shutil.which("codex")
    return str(Path(external).absolute()) if external else None


def install_codex(home):
    """Reuse an existing CLI or install a verified release without sudo."""
    executable = find_codex(home)
    if executable:
        return executable

    target = f"{_ARCHES.get(platform.machine().lower())}-{_SYSTEMS.get(platform.system())}"
    expected = _ASSETS.get(target)
    if not expected:
        raise InstallError("Automatic Codex installation supports x64 and ARM64 on Linux, macOS and Windows.")

    destination = home / "bin" / _binary_name()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    member_name = f"codex-{target}" + (".exe" if platform.system() == "Windows" else "")
    with tempfile.TemporaryDirectory(prefix=".install-", dir=destination.parent) as temporary:
        archive = Path(temporary) / "codex.tar.gz"
        binary = Path(temporary) / _binary_name()
        try:
            _download(_RELEASE + member_name + ".tar.gz", archive, expected)
            with tarfile.open(archive, "r:gz") as package:
                for entry in package:
                    if Path(entry.name).name == member_name and entry.isfile() and entry.size <= _MAX_BINARY:
                        with package.extractfile(entry) as source, binary.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        break
                else:
                    raise InstallError("The Codex archive does not contain the expected executable.")
            binary.chmod(0o700)
            check = subprocess.run([str(binary.resolve()), "--version"], capture_output=True, timeout=15)
            if check.returncode or check.stdout.strip() != f"codex-cli {VERSION}".encode():
                raise InstallError("The downloaded Codex CLI failed its version check.")
            # A simultaneous installer may have already published this version.
            if not (destination.is_file() and os.access(destination, os.X_OK)):
                try:
                    os.replace(binary, destination)
                except OSError:
                    if not (destination.is_file() and os.access(destination, os.X_OK)):
                        raise
        except (OSError, tarfile.TarError, subprocess.SubprocessError) as exc:
            raise InstallError(f"Could not install Codex CLI. Check access to GitHub Releases and free disk space. ({exc})") from exc
    return str(destination.resolve())


def _download(url, archive, expected):
    digest = hashlib.sha256()
    deadline = time.monotonic() + 300
    size = 0
    with urlopen(url, timeout=30) as source, archive.open("wb") as output:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > _MAX_ARCHIVE or time.monotonic() > deadline:
                raise InstallError("The Codex download exceeded its size or time limit.")
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != expected:
        raise InstallError("The Codex download failed SHA-256 verification.")
