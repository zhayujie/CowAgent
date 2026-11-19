#!/usr/bin/env bash
#
# Keep the backend's version in step with the installer's.
#
# The desktop shell takes its version from desktop/package.json (stamped by
# `npm version` in the release workflows), but the bundled backend reports
# cli/VERSION through /api/version. A build dispatched before cli/VERSION was
# bumped would otherwise ship a backend that reports the previous release.
#
# Usage (from the repo root):
#   bash desktop/build/stamp-backend-version.sh <version>           # before PyInstaller
#   bash desktop/build/stamp-backend-version.sh --verify <version>  # after PyInstaller
#
# An empty version leaves cli/VERSION untouched.
set -euo pipefail

verify=0
if [ "${1:-}" = "--verify" ]; then
  verify=1
  shift
fi

ver="$(printf '%s' "${1:-}" | tr -d '[:space:]')"
ver="${ver#v}"
if [ -z "$ver" ]; then
  echo "No version given; leaving cli/VERSION as is."
  exit 0
fi

if [ "$verify" = 1 ]; then
  bundled="$(find desktop/build/dist -type f -path '*/cli/VERSION' 2>/dev/null | head -n 1 || true)"
  if [ -z "$bundled" ]; then
    echo "::warning::cli/VERSION not found in desktop/build/dist; skipping the version check."
    exit 0
  fi
  got="$(tr -d '[:space:]' < "$bundled")"
  if [ "$got" != "$ver" ]; then
    echo "::error::Bundled backend reports $got but the release is $ver ($bundled)."
    exit 1
  fi
  echo "Bundled backend version: $got"
  exit 0
fi

current="$(tr -d '[:space:]' 2>/dev/null < cli/VERSION || true)"
if [ "$current" != "$ver" ]; then
  echo "::warning::cli/VERSION is '$current' in this checkout; stamping '$ver' so the backend matches the installer."
fi
printf '%s\n' "$ver" > cli/VERSION
echo "cli/VERSION -> $ver"
