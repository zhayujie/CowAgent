from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_mail_overlay_persists_the_runtime_and_wraps_the_base_entrypoint():
    """Removing any mount or entrypoint override would lose the opt-in runtime."""
    overlay = (ROOT / "docker/docker-compose.agent-mail.yml").read_text()
    base_compose = (ROOT / "docker/docker-compose.yml").read_text()

    assert "chatgpt-on-wechat:" in overlay
    assert "image: zhayujie/chatgpt-on-wechat" in base_compose
    assert "user: root" in overlay
    assert "./cow-data/agent-mail/config:/home/agent/.agently-cli" in overlay
    assert "./cow-data/agent-mail/share:/home/agent/.local/share/agently-cli" in overlay
    assert "./cow-data/agent-mail/npm-global:/home/agent/.npm-global" in overlay
    assert (
        "./agent-mail/entrypoint.sh:"
        "/docker-entrypoint-init.d/agent-mail-entrypoint.sh:ro" in overlay
    )
    assert "./docker/agent-mail/entrypoint.sh" not in overlay
    assert (
        "PATH: /home/agent/.npm-global/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin" in overlay
    )
    assert (
        'entrypoint: ["/bin/bash", '
        '"/docker-entrypoint-init.d/agent-mail-entrypoint.sh"]' in overlay
    )


def test_agent_mail_initializer_installs_a_pinned_cli_without_interactive_setup():
    """A missing runtime must trigger the pinned install, never an interactive login."""
    wrapper = (ROOT / "docker/agent-mail/entrypoint.sh").read_text()

    assert "set -euo pipefail" in wrapper
    assert "AGENTLY_CLI_VERSION=1.0.18" in wrapper
    assert 'PATH="$NPM_GLOBAL_PREFIX/bin:$PATH"' in wrapper
    assert 'command -v node' in wrapper
    assert '"$NPM_GLOBAL_PREFIX/bin/agently-cli"' in wrapper
    assert "nodesource.com/setup_20.x" in wrapper
    assert (
        'npm install --global --prefix "$NPM_GLOBAL_PREFIX" '
        '"@tencent-qqmail/agently-cli@${AGENTLY_CLI_VERSION}"' in wrapper
    )
    assert "auth login" not in wrapper
    assert "skills add" not in wrapper
    assert "exec /entrypoint.sh" in wrapper


def test_agent_mail_initializer_reinstalls_an_unverified_persistent_cli_version():
    """An old executable must not bypass the pinned package version check."""
    wrapper = (ROOT / "docker/agent-mail/entrypoint.sh").read_text()

    assert "has_pinned_agently_cli" in wrapper
    assert "@tencent-qqmail/agently-cli/package.json" in wrapper
    assert '"$AGENTLY_CLI_VERSION"' in wrapper
    assert "if ! has_pinned_agently_cli; then" in wrapper


def test_agent_mail_guide_keeps_authentication_as_a_user_run_step():
    """The guide must expose opt-in startup and explicit post-start authentication."""
    guide = (ROOT / "docs/guide/agent-mail.mdx").read_text()

    assert (
        "docker compose -f docker/docker-compose.yml "
        "-f docker/docker-compose.agent-mail.yml up -d" in guide
    )
    assert (
        "docker compose -f docker/docker-compose.yml "
        "-f docker/docker-compose.agent-mail.yml exec -u agent "
        "chatgpt-on-wechat agently-cli auth login" in guide
    )
    assert (
        "docker compose -f docker/docker-compose.yml "
        "-f docker/docker-compose.agent-mail.yml exec -u agent chatgpt-on-wechat "
        "npx -y skills add https://agent.qq.com --skill -g -y" in guide
    )
    assert "./cow-data/agent-mail/" in guide
    assert "docker/cow-data/agent-mail/" in guide
    assert "optional" in guide.lower()
    assert "default" in guide.lower()


def test_agent_mail_guide_is_listed_in_the_english_installation_navigation():
    """The new English guide must be discoverable from the established installation pages."""
    docs_config = (ROOT / "docs/docs.json").read_text()

    assert '"guide/agent-mail"' in docs_config


def test_agent_mail_persistent_credentials_are_ignored_by_git():
    """Generated Agent Mail credentials must not be staged with source changes."""
    gitignore = (ROOT / ".gitignore").read_text()

    assert "docker/cow-data/agent-mail/" in gitignore
