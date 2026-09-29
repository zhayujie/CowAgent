#!/usr/bin/env bash
#
# Build the desktop backend into a self-contained onedir bundle via PyInstaller.
# Run from anywhere; paths are resolved relative to the repo root.
#
# Usage:
#   bash desktop/build/build-backend.sh            # build
#   PYTHON=python3.11 bash desktop/build/build-backend.sh   # pick interpreter
#
# Output: desktop/build/dist/cowagent-backend/  (folder with the executable)
set -euo pipefail

# --- resolve paths --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"
VENV_DIR="$BUILD_DIR/.venv-build"

# Prefer Python 3.11 when available: it has the best PyInstaller support.
if [ -z "${PYTHON:-}" ]; then
  for cand in \
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11" \
    "python3.11" \
    "python3.12" \
    "python3"; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYTHON="$cand"
      break
    fi
  done
fi
# Prefer Python 3.11 for PyInstaller support. Override with PYTHON=... if needed.
pick_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for c in python3.11 python3.12 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return; fi
  done
  echo python3
}
PYTHON="$(pick_python)"

echo "==> Repo root: $ROOT"
echo "==> Using Python: $($PYTHON --version 2>&1) ($PYTHON)"

# --- isolated build venv --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating build venv at $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Installing build dependencies"
pip install -q --upgrade pip
# Don't leave a half-populated venv behind if deps fail (e.g. flaky network):
# the next run would otherwise reuse a broken venv.
if ! pip install -q -r "$BUILD_DIR/requirements-desktop.txt"; then
  echo "!! Dependency install failed. Removing the build venv so a retry starts clean." >&2
  deactivate || true
  rm -rf "$VENV_DIR"
  exit 1
fi
pip install -q pyinstaller

# --- run pyinstaller from repo root so relative datas resolve -------------
cd "$ROOT"
echo "==> Running PyInstaller (onedir)"
pyinstaller "$BUILD_DIR/cowagent-backend.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work"

echo ""
echo "==> Done. Bundle at: $BUILD_DIR/dist/cowagent-backend/"
du -sh "$BUILD_DIR/dist/cowagent-backend/" 2>/dev/null || true
echo "==> Smoke test: COW_DESKTOP=1 \"$BUILD_DIR/dist/cowagent-backend/cowagent-backend\""
