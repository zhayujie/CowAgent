# Security Policy

## Reporting a vulnerability

Please **do not** report security vulnerabilities through public issues, pull requests or discussions.

Report them privately through GitHub instead: open the [Security tab](https://github.com/zhayujie/CowAgent/security) and click **Report a vulnerability**, or go directly to [this form](https://github.com/zhayujie/CowAgent/security/advisories/new).

A useful report includes:

- the affected version or commit;
- the configuration involved (channel, permission mode, deployment form such as desktop, Docker or source);
- steps to reproduce, ideally a minimal proof of concept;
- the impact you expect an attacker to achieve.

We will acknowledge the report, keep you updated while we investigate, and credit you in the advisory and release notes unless you prefer to stay anonymous. Please give us a reasonable amount of time to release a fix before disclosing the issue publicly.

## Supported versions

Security fixes land on `master` and ship in the next release. Only the latest release is supported; please upgrade before reporting an issue that may already be fixed.

## Scope

CowAgent runs an AI agent that can execute shell commands, write files and call external services on the host it runs on. The permission modes (`read-only`, `workspace-write`, `full-access`) are argument-level checks, not an OS sandbox. Reports are in scope when they show a way around a protection CowAgent claims to provide, for example:

- running tools beyond the permission mode in force for a conversation;
- reaching the web console or its APIs without the configured password;
- reading or writing files outside the paths a feature is meant to expose;
- leaking credentials, conversation data or memory across Agents, guests or channels.

Behavior that follows from a configuration the operator chose explicitly (such as `full-access` mode, or exposing the console without a password) is not a vulnerability on its own. If you are unsure, report it privately anyway.
