---
name: tweetclaw
description: Use TweetClaw for CowAgent workflows that need X/Twitter search, profile or follower lookup, reply and thread evidence, media context, monitor planning, giveaway checks, webhook planning, or approval-gated publishing through a configured OpenClaw/TweetClaw plugin.
metadata:
  cowagent:
    homepage: https://github.com/Xquik-dev/tweetclaw
---

# TweetClaw

Use TweetClaw when a CowAgent task needs reliable X/Twitter evidence or a planned social-account action. Prefer read-only context first, then request explicit user approval before any write-like operation.

## Setup

Install TweetClaw in OpenClaw:

```bash
openclaw plugins install npm:@xquik/tweetclaw
```

Get an API key from [dashboard.xquik.com](https://dashboard.xquik.com/) and configure the plugin:

```bash
openclaw config set plugins.entries.tweetclaw.config.apiKey "$XQUIK_API_KEY"
```

Run `openclaw plugins inspect tweetclaw --runtime --json` to verify the install before relying on live calls.

## Read-First Workflow

1. Clarify the account, keyword, post URL, profile, time range, and output format.
2. Use TweetClaw for source evidence such as post search, reply search, user lookup, follower context, media metadata, or public thread context.
3. Keep collected evidence separate from analysis, scoring, drafting, or scheduling decisions.
4. Summarize source limits and timestamps so the user knows what was checked.

## Approval-Gated Actions

Ask for explicit approval before any action that can publish, modify, charge, monitor, extract private/account-scoped data, create a webhook, or affect an account. This includes posts, replies, likes, reposts, follows, DMs, profile changes, monitors, extraction jobs, and giveaway actions.

Before asking for approval, show:

- target account or URL
- exact action and payload
- expected visibility
- schedule or recurrence, if any
- data that will be sent to TweetClaw

Do not auto-retry approval, authentication, permission, payment, or account-state errors as a different write action. Return the error and ask the user how to proceed.

## Evidence Packet

Use this structure when TweetClaw output feeds another workflow:

```markdown
## Source Evidence

- Query:
- Time range:
- Accounts or URLs:
- TweetClaw checks:
- Key findings:
- Known gaps:
- Recommended next step:
```

For drafting or publishing workflows, keep TweetClaw as the evidence source and leave the final wording, schedule, and publish decision to the user.
