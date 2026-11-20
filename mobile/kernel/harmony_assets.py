"""Stage the agent kernel the HarmonyOS app embeds into its rawfile resources.

    python harmony_assets.py <rawfile dir>

The HarmonyOS build runs this before every build (harmony/entry/hvigorfile.ts),
on whatever machine builds the app. It writes <rawfile dir>/cow-kernel:

    sources.zip         the kernel sources (bundle.py)
    stdlib.zip          \\
    site-packages.zip    > the Python runtime from harmony_prepare.py
    cacert.pem          /  (OpenSSL's CA store, from certifi)
    STAMP               changes whenever any of the above does

Without the runtime (harmony_prepare.py was never run) the directory is
removed, and the app builds without the embedded kernel.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

from bundle import bundle

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, "..", "harmony", "cow-python"))
RUNTIME_FILES = ["stdlib.zip", "site-packages.zip"]


def _zip_tree(root: str, target: str) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, dirs, files in os.walk(root):
            dirs.sort()
            for f in sorted(files):
                path = os.path.join(d, f)
                # A fixed timestamp keeps the archive, and so STAMP, stable across runs.
                info = zipfile.ZipInfo(os.path.relpath(path, root).replace(os.sep, "/"), (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as src:
                    zf.writestr(info, src.read())


def _digest(paths) -> str:
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()[:16]


def stage(rawfile: str) -> None:
    dest = os.path.join(rawfile, "cow-kernel")
    if not all(os.path.isfile(os.path.join(RUNTIME, name)) for name in RUNTIME_FILES):
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        print("cow-kernel: no Python runtime in mobile/harmony/cow-python "
              "(see mobile/kernel/harmony_prepare.py); building without the embedded kernel")
        return
    os.makedirs(dest, exist_ok=True)
    for name in RUNTIME_FILES:
        src = os.path.join(RUNTIME, name)
        target = os.path.join(dest, name)
        if not os.path.exists(target) or _digest([src]) != _digest([target]):
            shutil.copy2(src, target)
    with zipfile.ZipFile(os.path.join(RUNTIME, "site-packages.zip")) as zf:
        with open(os.path.join(dest, "cacert.pem"), "wb") as f:
            f.write(zf.read("certifi/cacert.pem"))
    with tempfile.TemporaryDirectory() as tmp:
        sources = os.path.join(tmp, "cow-kernel")
        bundle(sources)
        _zip_tree(sources, os.path.join(dest, "sources.zip"))
    names = RUNTIME_FILES + ["cacert.pem", "sources.zip"]
    stamp = _digest(os.path.join(dest, name) for name in names)
    with open(os.path.join(dest, "STAMP"), "w") as f:
        f.write(stamp + "\n")
    print(f"cow-kernel: staged {stamp}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    stage(sys.argv[1])
