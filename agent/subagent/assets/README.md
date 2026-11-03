# Sub agent types

A sub agent is an extra pair of hands for your Agent. It gets one task, works in
its own context, and reports back a single answer — everything it read or ran on
the way is discarded instead of filling up your Agent's context window.

A sub agent is **not** a second Agent. It has no IM account, no workspace and no
memory of its own, and it lives only as long as the task.

Two types ship built in:

| Type | What it is for | Tools |
| --- | --- | --- |
| `general-purpose` | Multi-step work that needs investigating *and* doing | all |
| `explore` | Read-only investigation: find, search, gather facts | read-only |

Drop a markdown file in this directory to add your own.

## Start from the example

`example.md.template` in this directory is a complete, working type. To use it:

```bash
cp example.md.template research-report.md   # now live, no restart needed
```

The `.template` suffix is what keeps it switched off — only `.md` files are
loaded — so rename it, or copy it and edit, and you have your own type.

## File format

Every `.md` file here becomes one type. The filename is yours to choose (it is
only used as a fallback name); what matters is the frontmatter.

```markdown
---
name: research-report
description: Dig through many web sources on one topic and come back with a short sourced report.
tools: web_search, web_fetch, read, write
---
You are a research assistant. You are given one topic and you return one report.
...
```

### Frontmatter

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | How the Agent refers to this type. Falls back to the filename. |
| `description` | yes | **When to pick this type.** See below — this is the important one. |
| `tools` | no | Comma-separated tool names. Omit to inherit every tool the Agent has. |

Reusing a built-in name (`general-purpose`, `explore`) replaces it, which is how
you customize a built-in rather than working around it.

`README.md` is ignored, so this file does not become a type.

### Body

The body is the sub agent's instructions. It is **appended to** a base prompt
that already covers the workspace path rules, the available tools and the
reply language, so do not repeat those. Write only what makes this type
different: what to produce, what to check, what never to do.

The body does *not* inherit `AGENT.md`, `RULE.md` or `MEMORY.md`. A sub agent
reports to your Agent rather than to the user, so the persona stays with your
Agent. If a rule matters for the work, restate it here.

## Writing a good `description`

Your Agent sees every type's `description` and nothing else when it decides
which to use. Write it as *when to pick me*, not *who I am*.

```yaml
# Good — describes the situation that should trigger it
description: Read-only investigation across code and docs. Use when the answer exists somewhere and needs finding, and nothing needs to change.

# Poor — describes the sub agent, gives the Agent nothing to match on
description: A helpful research assistant.
```

## Tools

Some tools are denied to every sub agent no matter what `tools` says:

`subagent`, `send`, `scheduler`, `task`, `env_config`, `evolution_undo`,
`memory_search`, `memory_get`

They all reach outside the delegated task — messaging the user, scheduling work
in your Agent's name, editing its configuration, or touching memory a sub agent
is deliberately not given.

A type that lists `tools` gets no skills either. A skill is a workflow written
end to end and most of them finish by writing something down, so handing one to
a sub agent that had those tools taken away just costs it turns. Omit `tools`
when the type needs skills, and scope the work in the body instead.

Listing tools explicitly is worth it when a type should not be able to change
anything: `tools: read, ls, search_files, web_search, web_fetch` cannot write,
by construction rather than by instruction.

Note that a tool allowlist matches by exact name, so it excludes MCP tools.
Omit `tools` if the type needs them.

## Settings

Sub agents are on by default. To turn them off, or to change the limits, in
`config.json`:

```json
"subagent": {
  "enabled": true,
  "max_depth": 1,
  "max_concurrent": 3,
  "timeout_seconds": 300
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Whether the Agent is offered the `subagent` tool at all |
| `max_depth` | `1` | `1` means only your Agent may spawn; a sub agent cannot spawn another |
| `max_concurrent` | `3` | How many sub agents one call may run in parallel |
| `timeout_seconds` | `300` | Budget for one call, covering all its parallel tasks |

Templates are re-read on every turn, so a file added here takes effect on the
next message — no restart.
