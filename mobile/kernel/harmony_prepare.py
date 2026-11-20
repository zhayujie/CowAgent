"""Build the Python runtime the HarmonyOS app embeds for its agent kernel.

    python3 harmony_prepare.py

HarmonyOS has no ready-made CPython, so this cross-compiles one. It runs on
Linux (WSL works) and needs the OpenHarmony native SDK for Linux: set OHOS_NDK
to its `native` directory (default /opt/ohos/linux/native). Everything lands in
mobile/harmony/cow-python, which git ignores:

    <abi>/include/python3.13   CPython headers
    <abi>/lib/libcowpython.a   CPython with every extension module the kernel
                               needs built in, plus OpenSSL, SQLite and the
                               regex package's _regex, all static
    stdlib.zip                 the standard library, as bytecode
    site-packages.zip          requirements.txt, as bytecode

The app links libcowpython.a into libcowkernel.so (harmony/entry/src/main/cpp/
kernel), and copies the zips into its rawfile resources at build time. Linking
everything statically keeps it to that one library: app data is mounted noexec,
so Python could not load extension modules from there anyway.

Downloads and builds are cached under ~/.cache/cow-harmony-python; reruns skip
whatever is already up to date.
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

PYTHON = "3.13.18"
PYTHON_MM = "3.13"
OPENSSL = "3.5.9"
SQLITE = ("2026", "3540100")
# Its C part is compiled here, so the pure-Python part must be the same release.
REGEX = "2026.11.19"

ABIS = {"arm64-v8a": "aarch64-linux-ohos", "x86_64": "x86_64-linux-ohos"}
# CPython's config.sub predates OHOS; its libc is musl, which configure knows.
CONFIGURE_HOSTS = {"arm64-v8a": "aarch64-linux-musl", "x86_64": "x86_64-linux-musl"}
OPENSSL_TARGETS = {"arm64-v8a": "linux-aarch64", "x86_64": "linux-x86_64"}

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
OUT = os.path.abspath(os.path.join(HERE, "..", "harmony", "cow-python"))
WORK = os.path.expanduser(os.environ.get("COW_HARMONY_WORK", "~/.cache/cow-harmony-python"))
NDK = os.environ.get("OHOS_NDK", "/opt/ohos/linux/native")
JOBS = str(os.cpu_count() or 4)

URLS = {
    "python": f"https://www.python.org/ftp/python/{PYTHON}/Python-{PYTHON}.tar.xz",
    "openssl": f"https://github.com/openssl/openssl/releases/download/openssl-{OPENSSL}/openssl-{OPENSSL}.tar.gz",
    "sqlite": f"https://www.sqlite.org/{SQLITE[0]}/sqlite-autoconf-{SQLITE[1]}.tar.gz",
}
# Bump these with the versions above.
SHA256 = {
    "python": "abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68",
    "openssl": "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a",
    "sqlite": "926ef8d3eab93fbf6e06011901273eec076b25594a4e1cdadd50c987f4f6d64e",
    "regex": "2826a006b68acfd3ed5074433caafe21d7f9d026eb82cb856724a4a893a70915",
}

# Modules that need libraries HarmonyOS lacks, or that the kernel never uses.
DISABLED_MODULES = [
    "_tkinter", "_curses", "_curses_panel", "readline", "_dbm", "_gdbm",
    "_ctypes", "_uuid", "_bz2", "_lzma", "xxlimited", "xxlimited_35", "xxsubtype",
]
# Parts of the standard library the kernel never imports.
STDLIB_SKIP = [
    "test", "idlelib", "tkinter", "turtledemo", "turtle.py", "ensurepip",
    "pydoc_data", "_pyrepl", "lib2to3", "venv", "lib-dynload", "site-packages",
]


def _run(cmd, cwd=None, env=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


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


def _check_sha256(name: str, path: str) -> None:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != SHA256[name]:
        os.remove(path)
        sys.exit(f"Checksum mismatch for {os.path.basename(path)}")


def _fetch(name: str) -> str:
    """Download a source archive once; returns its path."""
    url = URLS[name]
    archive = os.path.join(WORK, "downloads", os.path.basename(url))
    os.makedirs(os.path.dirname(archive), exist_ok=True)
    if not os.path.exists(archive):
        _run(["curl", "-fL", "--retry", "3", "-o", archive + ".part", url])
        _check_sha256(name, archive + ".part")
        os.rename(archive + ".part", archive)
    return archive


def _unpack(archive: str, dest: str) -> str:
    _rmtree(dest)
    os.makedirs(dest)
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    (top,) = os.listdir(dest)
    return os.path.join(dest, top)


def _stamped(path: str, stamp: str) -> bool:
    return _read(os.path.join(path, ".cow-stamp")) == stamp


def _stamp(path: str, stamp: str) -> None:
    _write(os.path.join(path, ".cow-stamp"), stamp)


def toolchain(abi: str) -> dict:
    """Compiler wrappers for one ABI, so autoconf sees plain single-word tools."""
    triple = ABIS[abi]
    bindir = os.path.join(WORK, "toolchain", triple)
    os.makedirs(bindir, exist_ok=True)
    llvm = os.path.join(NDK, "llvm", "bin")
    sysroot = os.path.join(NDK, "sysroot")
    for tool, real in (("clang", "clang"), ("clang++", "clang++")):
        path = os.path.join(bindir, f"{triple}-{tool}")
        # CPython's configure cross-checks the triplet it derives against
        # --print-multiarch; the OHOS one is not on its list, so stay quiet.
        _write(path, (
            "#!/bin/sh\n"
            'for a in "$@"; do [ "$a" = --print-multiarch ] && exit 0; done\n'
            f'exec "{llvm}/{real}" --target={triple} --sysroot="{sysroot}" "$@"\n'
        ))
        os.chmod(path, 0o755)
    env = dict(os.environ)
    env.update({
        "CC": os.path.join(bindir, f"{triple}-clang"),
        "CXX": os.path.join(bindir, f"{triple}-clang++"),
        "AR": os.path.join(llvm, "llvm-ar"),
        "RANLIB": os.path.join(llvm, "llvm-ranlib"),
        "STRIP": os.path.join(llvm, "llvm-strip"),
        "NM": os.path.join(llvm, "llvm-nm"),
        "READELF": os.path.join(llvm, "llvm-readelf"),
        # Everything ends up inside a shared library.
        "CFLAGS": "-fPIC -O2",
        "CXXFLAGS": "-fPIC -O2",
    })
    return env


def build_host_python() -> str:
    """CPython for the build machine: the cross build and the bytecode need the same version."""
    prefix = os.path.join(WORK, "host")
    python = os.path.join(prefix, "bin", f"python{PYTHON_MM}")
    if _stamped(prefix, PYTHON) and os.path.exists(python):
        return python
    src = _unpack(_fetch("python"), os.path.join(WORK, "src", "host"))
    _rmtree(prefix)
    _run(["./configure", f"--prefix={prefix}", "--with-ensurepip=install"], cwd=src)
    _run(["make", f"-j{JOBS}"], cwd=src)
    _run(["make", "install"], cwd=src)
    _stamp(prefix, PYTHON)
    return python


def build_openssl(abi: str, env: dict) -> str:
    prefix = os.path.join(WORK, abi, "openssl")
    if _stamped(prefix, OPENSSL):
        return prefix
    src = _unpack(_fetch("openssl"), os.path.join(WORK, "src", f"openssl-{abi}"))
    _rmtree(prefix)
    _run([
        "./Configure", OPENSSL_TARGETS[abi], f"--prefix={prefix}", "--libdir=lib",
        "no-shared", "no-tests", "no-docs", "no-apps", "no-afalgeng", "no-engine", "-fPIC",
    ], cwd=src, env=env)
    _run(["make", f"-j{JOBS}", "build_libs"], cwd=src, env=env)
    _run(["make", "install_dev"], cwd=src, env=env)
    _stamp(prefix, OPENSSL)
    return prefix


def build_sqlite(abi: str, env: dict) -> str:
    prefix = os.path.join(WORK, abi, "sqlite")
    if _stamped(prefix, SQLITE[1]):
        return prefix
    src = _unpack(_fetch("sqlite"), os.path.join(WORK, "src", f"sqlite-{abi}"))
    _rmtree(prefix)
    os.makedirs(os.path.join(prefix, "include"))
    os.makedirs(os.path.join(prefix, "lib"))
    obj = os.path.join(src, "sqlite3.o")
    _run([
        env["CC"], "-c", "-fPIC", "-O2", "-DSQLITE_THREADSAFE=1", "-DSQLITE_ENABLE_FTS5",
        "-DSQLITE_ENABLE_FTS4", "-DSQLITE_ENABLE_RTREE", "-DSQLITE_ENABLE_MATH_FUNCTIONS",
        "-DSQLITE_OMIT_LOAD_EXTENSION", "sqlite3.c", "-o", obj,
    ], cwd=src)
    _run([env["AR"], "rcs", os.path.join(prefix, "lib", "libsqlite3.a"), obj])
    for header in ("sqlite3.h", "sqlite3ext.h"):
        shutil.copy2(os.path.join(src, header), os.path.join(prefix, "include", header))
    _stamp(prefix, SQLITE[1])
    return prefix


def build_python(abi: str, env: dict, host_python: str, openssl: str, sqlite: str) -> str:
    """Cross-compile CPython with every extension module linked in (MODULE_BUILDTYPE=static)."""
    build = os.path.join(WORK, abi, "cpython")
    stamp = f"{PYTHON}-{OPENSSL}-{SQLITE[1]}-{','.join(DISABLED_MODULES)}"
    if _stamped(build, stamp):
        return build
    src = _unpack(_fetch("python"), os.path.join(WORK, "src", f"cpython-{abi}"))
    _rmtree(build)
    config_site = os.path.join(src, "config.site-ohos")
    _write(config_site, "\n".join([
        "ac_cv_file__dev_ptmx=yes",
        "ac_cv_file__dev_ptc=no",
        # The OHOS CAN bus headers predate what socketmodule expects; phones have no CAN bus.
        "ac_cv_header_linux_can_h=no",
        "ac_cv_header_linux_can_raw_h=no",
        "ac_cv_header_linux_can_bcm_h=no",
        "ac_cv_header_linux_can_j1939_h=no",
        "ac_cv_can_raw_fd_frames=no",
        "ac_cv_can_raw_join_filters=no",
        # libintl.h exists but declares none of gettext's functions.
        "ac_cv_header_libintl_h=no",
    ]) + "\n")
    cenv = dict(env)
    cenv.update({
        "CONFIG_SITE": config_site,
        "MODULE_BUILDTYPE": "static",
        "LIBSQLITE3_CFLAGS": f"-I{sqlite}/include",
        "LIBSQLITE3_LIBS": f"-L{sqlite}/lib -lsqlite3 -lm",
    })
    for name in DISABLED_MODULES:
        cenv[f"py_cv_module_{name}"] = "n/a"
    _run([
        "./configure", f"--host={CONFIGURE_HOSTS[abi]}", "--build=x86_64-pc-linux-gnu",
        f"--with-build-python={host_python}", "--prefix=/python",
        "--disable-shared", "--without-ensurepip", "--disable-test-modules",
        f"--with-openssl={openssl}", "--with-openssl-rpath=no", "--enable-ipv6",
    ], cwd=src, env=cenv)
    _run(["make", f"-j{JOBS}", "all"], cwd=src, env=cenv)
    dest = os.path.join(build, "install")
    _run(["make", "install", f"DESTDIR={dest}", "COMPILEALL_OPTS=-j0"], cwd=src, env=cenv)
    shutil.copy2(os.path.join(src, f"libpython{PYTHON_MM}.a"), os.path.join(build, f"libpython{PYTHON_MM}.a"))
    # Static modules leave their bundled libraries (expat, mpdec, HACL*) as separate archives.
    os.makedirs(os.path.join(build, "modlibs"))
    for lib in glob.glob(os.path.join(src, "Modules", "**", "*.a"), recursive=True):
        shutil.copy2(lib, os.path.join(build, "modlibs", os.path.basename(lib)))
    _stamp(build, stamp)
    return build


def fetch_regex(host_python: str) -> str:
    dest = os.path.join(WORK, "src", "regex")
    src = os.path.join(dest, f"regex-{REGEX}")
    if _stamped(dest, REGEX) and os.path.isdir(src):
        return src
    _rmtree(dest)
    os.makedirs(dest)
    _run([host_python, "-m", "pip", "download", "--no-deps", "--no-binary", ":all:",
          "-d", dest, f"regex=={REGEX}"])
    archive = os.path.join(dest, f"regex-{REGEX}.tar.gz")
    _check_sha256("regex", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    _stamp(dest, REGEX)
    return src


def build_regex(abi: str, env: dict, regex_src: str, include: str) -> list:
    out = os.path.join(WORK, abi, "regex")
    _rmtree(out)
    os.makedirs(out)
    objs = []
    for name in ("_regex.c", "_regex_unicode.c"):
        path = os.path.join(regex_src, "src", name)
        obj = os.path.join(out, name[:-2] + ".o")
        _run([env["CC"], "-c", "-fPIC", "-O2", f"-I{include}", path, "-o", obj])
        objs.append(obj)
    return objs


def package_abi(abi: str, env: dict, build: str, openssl: str, sqlite: str, regex_objs: list) -> None:
    dest = os.path.join(OUT, abi)
    _rmtree(dest)
    os.makedirs(os.path.join(dest, "lib"))
    include = os.path.join(build, "install", "python", "include", f"python{PYTHON_MM}")
    shutil.copytree(include, os.path.join(dest, "include", f"python{PYTHON_MM}"))
    # One archive, so the app links a single library.
    archives = [os.path.join(build, f"libpython{PYTHON_MM}.a")]
    archives += sorted(glob.glob(os.path.join(build, "modlibs", "*.a")))
    archives += [os.path.join(openssl, "lib", "libssl.a"), os.path.join(openssl, "lib", "libcrypto.a")]
    archives += [os.path.join(sqlite, "lib", "libsqlite3.a")]
    target = os.path.join(dest, "lib", "libcowpython.a")
    script = [f"CREATE {target}"] + [f"ADDLIB {a}" for a in archives]
    script += [f"ADDMOD {o}" for o in regex_objs] + ["SAVE", "END"]
    subprocess.run([env["AR"], "-M"], input="\n".join(script) + "\n", text=True, check=True)
    _run([env["RANLIB"], target])


def _compile_tree(host_python: str, root: str) -> None:
    """Replace every .py under root with its bytecode, as the zips import from it."""
    code = (
        "import os, py_compile, sys\n"
        "root = sys.argv[1]\n"
        "for d, _, files in os.walk(root):\n"
        "    for f in files:\n"
        "        if f.endswith('.py'):\n"
        "            src = os.path.join(d, f)\n"
        "            try:\n"
        "                py_compile.compile(src, cfile=src + 'c', dfile=os.path.relpath(src, root), doraise=True,\n"
        "                                   invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)\n"
        "            except py_compile.PyCompileError as e:\n"
        "                print('skip', e.msg.splitlines()[0])\n"
        "            os.remove(src)\n"
    )
    _run([host_python, "-c", code, root])
    for d, dirs, _ in os.walk(root):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
            shutil.rmtree(os.path.join(d, "__pycache__"))


def _zip_tree(root: str, target: str) -> None:
    tmp = target + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for d, dirs, files in os.walk(root):
            dirs.sort()
            # zipimport finds namespace packages (no __init__, like jaraco) by their directory entry.
            if d != root:
                zf.write(d, os.path.relpath(d, root))
            for f in sorted(files):
                path = os.path.join(d, f)
                zf.write(path, os.path.relpath(path, root))
    os.replace(tmp, target)


def package_stdlib(host_python: str, builds: dict) -> None:
    stage = os.path.join(WORK, "stage", "stdlib")
    _rmtree(stage)
    first = next(iter(builds.values()))
    shutil.copytree(os.path.join(first, "install", "python", "lib", f"python{PYTHON_MM}"), stage,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "config-*"))
    for name in STDLIB_SKIP:
        path = os.path.join(stage, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    # sysconfig's data module is named per ABI, so both fit in one zip.
    for build in builds.values():
        lib = os.path.join(build, "install", "python", "lib", f"python{PYTHON_MM}")
        for path in glob.glob(os.path.join(lib, "_sysconfigdata_*.py")):
            shutil.copy2(path, stage)
    _compile_tree(host_python, stage)
    _zip_tree(stage, os.path.join(OUT, "stdlib.zip"))


def package_site(host_python: str) -> None:
    stage = os.path.join(WORK, "stage", "site-packages")
    _rmtree(stage)
    constraints = os.path.join(WORK, "constraints.txt")
    _write(constraints, f"regex=={REGEX}\n")
    _run([host_python, "-m", "pip", "--disable-pip-version-check", "-q", "install", "--no-compile",
          "--target", stage, "-r", REQUIREMENTS, "-c", constraints])
    _rmtree(os.path.join(stage, "bin"))
    # Wheels built for this machine carry its extension modules. regex's is linked
    # into the app; the rest (PyYAML's libyaml binding, the mypyc builds of chardet
    # and charset_normalizer) have pure-Python fallbacks.
    for path in glob.glob(os.path.join(stage, "**", "*.so"), recursive=True):
        print("drop", os.path.relpath(path, stage))
        os.remove(path)
    for path in glob.glob(os.path.join(stage, "*.dist-info")):
        shutil.rmtree(path)
    _compile_tree(host_python, stage)
    _zip_tree(stage, os.path.join(OUT, "site-packages.zip"))


def main() -> None:
    if not sys.platform.startswith("linux"):
        sys.exit("The HarmonyOS runtime is cross-compiled on Linux (WSL works).")
    if not os.path.isfile(os.path.join(NDK, "llvm", "bin", "clang")):
        sys.exit(f"No OpenHarmony native SDK at {NDK}; set OHOS_NDK to the SDK's `native` directory.")
    abis = sys.argv[1:] or list(ABIS)
    for abi in abis:
        if abi not in ABIS:
            sys.exit(f"Unknown ABI {abi}; expected one of {', '.join(ABIS)}.")
    os.makedirs(OUT, exist_ok=True)
    host_python = build_host_python()
    regex_src = fetch_regex(host_python)
    builds = {}
    for abi in abis:
        env = toolchain(abi)
        openssl = build_openssl(abi, env)
        sqlite = build_sqlite(abi, env)
        builds[abi] = build_python(abi, env, host_python, openssl, sqlite)
        include = os.path.join(builds[abi], "install", "python", "include", f"python{PYTHON_MM}")
        regex_objs = build_regex(abi, env, regex_src, include)
        package_abi(abi, env, builds[abi], openssl, sqlite, regex_objs)
    package_stdlib(host_python, builds)
    package_site(host_python)
    print(f"Done: {OUT}")


if __name__ == "__main__":
    main()
