#!/bin/bash
set -euo pipefail

NPM_GLOBAL_PREFIX=/home/agent/.npm-global
AGENTLY_CLI_VERSION=1.0.18

export PATH="$NPM_GLOBAL_PREFIX/bin:$PATH"

has_pinned_agently_cli() {
    [ -x "$NPM_GLOBAL_PREFIX/bin/agently-cli" ] \
        && command -v node >/dev/null 2>&1 \
        && [ "$(node -p "require('$NPM_GLOBAL_PREFIX/lib/node_modules/@tencent-qqmail/agently-cli/package.json').version" 2>/dev/null || true)" = "$AGENTLY_CLI_VERSION" ]
}

if ! has_pinned_agently_cli; then
    apt-get update
    apt-get install -y --no-install-recommends curl ca-certificates
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get update
    apt-get install -y --no-install-recommends nodejs
    npm config set prefix "$NPM_GLOBAL_PREFIX"
    npm install --global --prefix "$NPM_GLOBAL_PREFIX" "@tencent-qqmail/agently-cli@${AGENTLY_CLI_VERSION}"
fi

mkdir -p /home/agent/.agently-cli /home/agent/.local/share/agently-cli "$NPM_GLOBAL_PREFIX"
chown -R agent:agent /home/agent/.agently-cli /home/agent/.local/share/agently-cli "$NPM_GLOBAL_PREFIX"

exec /entrypoint.sh
