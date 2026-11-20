"""Fetch the Python runtime and packages the iOS app embeds for its agent kernel.

    python3.13 ios_prepare.py

Needs macOS with Xcode and the same Python version the app embeds (3.13);
`pod install` runs it. Everything lands in mobile/ios/build/cow-python, which
git ignores:

    Python.xcframework            CPython for iOS (BeeWare Python-Apple-support)
    app_packages-iphoneos         requirements.txt built for devices
    app_packages-iphonesimulator  requirements.txt built for the simulator

Packages without an iOS wheel are compiled from source with the cross-build
environment the runtime ships. Reruns skip whatever is already up to date.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile

PYTHON_VERSION = (3, 13)
SUPPORT = "3.13-b18"
SUPPORT_URL = (
    "https://github.com/beeware/Python-Apple-support/releases/download/"
    f"{SUPPORT}/Python-3.13-iOS-support.b18.tar.gz"
)
SUPPORT_SHA256 = "d06acf2a9c7964a8689566353a0e707402eff822037de5e29ba0e16040f7047d"

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
OUT = os.path.join(HERE, "..", "ios", "build", "cow-python")
FRAMEWORK = os.path.join(OUT, "Python.xcframework")

# (SDK, xcframework slice, platform config). The simulator build targets Apple
# silicon Macs only.
TARGETS = [
    ("iphoneos", "ios-arm64", "arm64-iphoneos"),
    ("iphonesimulator", "ios-arm64_x86_64-simulator", "arm64-iphonesimulator"),
]

# Build backends for packages that only publish source; the cross environment
# builds without isolation so they compile against iOS.
BUILD_TOOLS = ["setuptools", "wheel", "flit_core", "hatchling"]

# Parts of the standard library the kernel never imports.
STDLIB_SKIP = [
    "test", "idlelib", "tkinter", "turtledemo", "turtle.py", "ensurepip",
    "pydoc_data", "_pyrepl", "lib2to3",
]
DYNLOAD_SKIP_PREFIXES = ("_test", "_ctypes_test", "_xxtestfuzz", "xxlimited", "xxsubtype")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write(text)


def _rmtree(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)


def prepare_framework() -> None:
    stamp = os.path.join(FRAMEWORK, ".cow-support")
    if _read(stamp) == SUPPORT:
        return
    print(f"Downloading Python {SUPPORT} for iOS...", flush=True)
    archive = os.path.join(OUT, "python-ios-support.tar.gz")
    subprocess.run(["curl", "-fL", "--retry", "3", "-o", archive, SUPPORT_URL], check=True)
    if _sha256(archive) != SUPPORT_SHA256:
        os.remove(archive)
        sys.exit(f"Checksum mismatch for {SUPPORT_URL}")

    _rmtree(FRAMEWORK)
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if m.name.startswith("Python.xcframework/")]
        tar.extractall(OUT, members=members, filter="data")
    os.remove(archive)
    _prune_stdlib()
    _write(stamp, SUPPORT)


def _prune_stdlib() -> None:
    stdlib = os.path.join(FRAMEWORK, "lib", f"python{PYTHON_VERSION[0]}.{PYTHON_VERSION[1]}")
    for name in STDLIB_SKIP:
        path = os.path.join(stdlib, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    for root, _dirs, files in os.walk(FRAMEWORK):
        if os.path.basename(root) != "lib-dynload":
            continue
        for name in files:
            if name.startswith(DYNLOAD_SKIP_PREFIXES):
                os.remove(os.path.join(root, name))


def prepare_packages(sdk: str, slice_name: str, config: str) -> None:
    dest = os.path.join(OUT, f"app_packages-{sdk}")
    stamp_path = os.path.join(dest, ".cow-stamp")
    stamp = hashlib.sha256((_read(__file__) + _read(REQUIREMENTS)).encode()).hexdigest()
    if _read(stamp_path) == stamp:
        return
    print(f"Installing the kernel's Python packages for {sdk}...", flush=True)

    venv = os.path.join(OUT, f"venv-{config}")
    _rmtree(venv)
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    pip = [os.path.join(venv, "bin", "python3"), "-m", "pip", "--disable-pip-version-check", "-q"]
    subprocess.run(pip + ["install"] + BUILD_TOOLS, check=True)
    slice_dir = os.path.join(FRAMEWORK, slice_name)
    subprocess.run(
        [os.path.join(venv, "bin", "python3"),
         os.path.join(slice_dir, "platform-config", config, "make_cross_venv.py"), venv],
        check=True,
    )

    staging = dest + ".tmp"
    _rmtree(staging)
    env = dict(os.environ)
    # The slice's bin holds the compiler wrappers that target this SDK.
    env["PATH"] = os.path.join(slice_dir, "bin") + os.pathsep + env.get("PATH", "")
    subprocess.run(
        # The app caches bytecode outside its read-only bundle, so none ships in it.
        pip + ["install", "--no-build-isolation", "--no-compile", "--target", staging, "-r", REQUIREMENTS],
        check=True,
        env=env,
    )
    _rmtree(os.path.join(staging, "bin"))
    _rmtree(dest)
    os.rename(staging, dest)
    _write(stamp_path, stamp)
    _rmtree(venv)


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("The iOS kernel can only be prepared on macOS.")
    if sys.version_info[:2] != PYTHON_VERSION:
        sys.exit(
            f"Run this with Python {PYTHON_VERSION[0]}.{PYTHON_VERSION[1]}, the version the app embeds "
            f"(found {sys.version_info[0]}.{sys.version_info[1]})."
        )
    os.makedirs(OUT, exist_ok=True)
    prepare_framework()
    for target in TARGETS:
        prepare_packages(*target)


if __name__ == "__main__":
    main()
