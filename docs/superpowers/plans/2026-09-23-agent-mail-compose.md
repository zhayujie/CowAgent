# Agent Mail Optional Compose Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Docker Compose overlay that installs and persists Agent Mail CLI without changing CowAgent's default image or CI build.

**Architecture:** The overlay mounts a persistent npm prefix and Agent Mail credential directories, then replaces the image entrypoint with a small root-owned initializer. The initializer installs Node 20 and the pinned `@tencent-qqmail/agently-cli@1.0.18` only when the persistent CLI is absent, fixes volume ownership, and delegates to the image's existing `/entrypoint.sh`; the normal compose file and image remain untouched.

**Tech Stack:** Docker Compose v2 YAML, POSIX shell, Node/npm runtime install, existing CowAgent `/entrypoint.sh`.

**Spec:** GitHub issue [#2938](https://github.com/zhayujie/CowAgent/issues/2938), especially the maintainer-approved comments requesting an optional compose-only runtime install, fixed versions, and persistent volumes.

## Global Constraints

- Do not modify `docker/Dockerfile.latest`, the default `docker/docker-compose.yml`, or the CI image build.
- Install `@tencent-qqmail/agently-cli` at exactly `1.0.18`; install Node from the NodeSource `20.x` channel only when the optional overlay is used.
- Persist `/home/agent/.agently-cli`, `/home/agent/.local/share/agently-cli`, and `/home/agent/.npm-global` through host paths under the first Compose file's project directory, `./cow-data/agent-mail/` (which is `docker/cow-data/agent-mail/` in this checkout).
- Never run `agently-cli auth login` or `npx skills add` automatically; the user performs those commands after the service starts.
- The wrapper must be idempotent, run the application as the existing `agent` user, and fail before starting CowAgent if dependency installation fails.
- Do not place tokens, API keys, or generated credentials in the repository.

---

### Task 1: Add the opt-in compose overlay and initializer

**Files:**
- Create: `docker/docker-compose.agent-mail.yml`
- Create: `docker/agent-mail/entrypoint.sh`
- Create: `docs/guide/agent-mail.mdx`
- Test: `tests/test_agent_mail_compose.py`

**Interfaces:**
- Consumes: the base service from `docker/docker-compose.yml`, image entrypoint `/entrypoint.sh`, and the persistent host directory `./cow-data/agent-mail`.
- Produces: a runnable optional overlay and documented post-start authentication commands.

- [ ] **Step 1: Write failing tests for the static contract**

  Add tests that read the three new files and assert: the overlay extends the `chatgpt-on-wechat` service, uses the existing image, mounts all three persistent paths, mounts the wrapper read-only, sets the wrapper as entrypoint, pins `AGENTLY_CLI_VERSION=1.0.18`, and does not invoke `auth login` or `skills add`. Assert the wrapper contains `set -eu`, checks both the persistent `agently-cli` path and `node` before installing, exports the persistent npm `bin` directory into `PATH`, and finally executes `/entrypoint.sh`.

- [ ] **Step 2: Run the focused test to verify it fails**

  Run: `pytest tests/test_agent_mail_compose.py -q`

  Expected: FAIL because the overlay, wrapper, and documentation do not yet exist.

- [ ] **Step 3: Add the minimal overlay**

  Use a service override named `chatgpt-on-wechat` with `user: root`, the three persistent mounts, and the wrapper mount:

  ```yaml
  services:
    chatgpt-on-wechat:
      user: root
      volumes:
        - ./cow-data/agent-mail/config:/home/agent/.agently-cli
        - ./cow-data/agent-mail/share:/home/agent/.local/share/agently-cli
        - ./cow-data/agent-mail/npm-global:/home/agent/.npm-global
        - ./agent-mail/entrypoint.sh:/docker-entrypoint-init.d/agent-mail-entrypoint.sh:ro
      entrypoint: ["/bin/bash", "/docker-entrypoint-init.d/agent-mail-entrypoint.sh"]
      environment:
        PATH: /home/agent/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  ```

  The overlay is used with `docker compose -f docker/docker-compose.yml -f docker/docker-compose.agent-mail.yml up -d` and does not duplicate base environment or ports.

- [ ] **Step 4: Add the idempotent wrapper**

  Implement the wrapper with `set -euo pipefail`, `NPM_GLOBAL_PREFIX=/home/agent/.npm-global`, and `AGENTLY_CLI_VERSION=1.0.18`. If `node` or `$NPM_GLOBAL_PREFIX/bin/agently-cli` is absent, install `curl` and `ca-certificates`, run the NodeSource `20.x` setup, install `nodejs`, configure npm's global prefix, and run `npm install --global --prefix "$NPM_GLOBAL_PREFIX" "@tencent-qqmail/agently-cli@${AGENTLY_CLI_VERSION}"`. Export `PATH="$NPM_GLOBAL_PREFIX/bin:$PATH"` before the check and handoff so the `agent` user can run the persisted CLI. Then create the two config directories, chown the three mounted trees to `agent:agent`, and `exec /entrypoint.sh`.

- [ ] **Step 5: Document first-run authentication**

  Document the overlay command and these explicit, user-run post-start commands:

  ```sh
  docker compose -f docker/docker-compose.yml -f docker/docker-compose.agent-mail.yml exec -u agent chatgpt-on-wechat agently-cli auth login
  docker compose -f docker/docker-compose.yml -f docker/docker-compose.agent-mail.yml exec -u agent chatgpt-on-wechat npx -y skills add https://agent.qq.com --skill -g -y
  ```

  State that credentials and the npm prefix persist under `./cow-data/agent-mail/`, the default compose path is unchanged, and the overlay is optional.

- [ ] **Step 6: Run focused validation**

  Run: `pytest tests/test_agent_mail_compose.py -q`

  Run: `bash -n docker/agent-mail/entrypoint.sh`

  If Docker is available, run: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.agent-mail.yml config --quiet`; otherwise record that the static test and shell parser are the available validation in this environment.

- [ ] **Step 7: Commit**

  ```bash
  git add docker/docker-compose.agent-mail.yml docker/agent-mail/entrypoint.sh docs/guide/agent-mail.mdx tests/test_agent_mail_compose.py
  git commit -m "feat(docker): add optional Agent Mail compose profile"
  ```
