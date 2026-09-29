#!/bin/bash
# No `set -e`: a failed Agent Mail install must never keep CowAgent from starting.
set -uo pipefail

# Node itself lives in the persistent prefix, so npm's default global prefix is
# the same directory and `npm install -g` run by the agent stays persistent too.
PREFIX=/home/agent/.npm-global
NODE_VERSION=22.23.3
AGENTLY_CLI_VERSION=1.0.18
NODE_MIRROR=${NODE_MIRROR:-https://nodejs.org/dist}
CLI_PACKAGE_JSON="$PREFIX/lib/node_modules/@tencent-qqmail/agently-cli/package.json"

export PATH="$PREFIX/bin:$PATH"

log() {
    echo "[agent-mail] $*" >&2
}

# Succeeds when version $1 is at least $2, so newer versions installed by the
# user are kept instead of being downgraded on every restart.
version_at_least() {
    [ -n "$1" ] && [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

has_node() {
    local installed
    installed=$("$PREFIX/bin/node" --version 2>/dev/null) || return 1
    version_at_least "${installed#v}" "$NODE_VERSION"
}

has_agently_cli() {
    local installed
    installed=$("$PREFIX/bin/node" -p "require('$CLI_PACKAGE_JSON').version" 2>/dev/null) || return 1
    [ -x "$PREFIX/bin/agently-cli" ] && version_at_least "$installed" "$AGENTLY_CLI_VERSION"
}

install_node() {
    local arch url
    case "$(uname -m)" in
        x86_64) arch=x64 ;;
        aarch64 | arm64) arch=arm64 ;;
        *) log "unsupported architecture: $(uname -m)"; return 1 ;;
    esac
    url="$NODE_MIRROR/v$NODE_VERSION/node-v$NODE_VERSION-linux-$arch.tar.gz"
    log "installing Node.js $NODE_VERSION from $url"
    # The slim base image has no curl; Python is always available.
    python3 -c '
import shutil, sys, urllib.request
try:
    shutil.copyfileobj(urllib.request.urlopen(sys.argv[1], timeout=60), sys.stdout.buffer)
except Exception as e:
    sys.exit(f"[agent-mail] download failed: {e}")
' "$url" | tar -xzf - --strip-components=1 --no-same-owner -C "$PREFIX"
}

install_agently_cli() {
    log "installing @tencent-qqmail/agently-cli@$AGENTLY_CLI_VERSION"
    "$PREFIX/bin/npm" install --global --prefix "$PREFIX" "@tencent-qqmail/agently-cli@$AGENTLY_CLI_VERSION"
}

mkdir -p /home/agent/.agently-cli /home/agent/.local/share/agently-cli "$PREFIX"

if ! has_node && ! install_node; then
    log "Node.js install failed; starting CowAgent without Agent Mail"
elif ! has_agently_cli && ! install_agently_cli; then
    log "agently-cli install failed; starting CowAgent without Agent Mail"
fi

chown -R agent:agent /home/agent/.agently-cli /home/agent/.local "$PREFIX"

exec /entrypoint.sh
