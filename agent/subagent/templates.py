"""Sub agent types: what kinds of worker the main Agent can spawn.

A template is a role, not an identity. It carries a system prompt and a tool
allowlist, and nothing else: no memory, no channel, no place in the Agent
registry. Users add their own as markdown files under ``<workspace>/subagents``,
the same shape skills already use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.log import logger

# Denied to every sub agent regardless of template.
#
# Each of these reaches outside the delegated task: `send` and `scheduler` act
# on the user's channel in the parent's name, and `env_config` and
# `evolution_undo` mutate the Agent itself. The `subagent` tool itself is denied
# so that a template granting "all tools" cannot recurse; the depth limit
# governs the nesting that is actually allowed.
#
# Memory tools are intentionally NOT blocked: a sub agent should be able to
# search and read the shared knowledge base to ground its work. It still owns no
# memory of its own (memory_manager is None), so it can read but never persist.
BLOCKED_TOOLS = frozenset(
    {
        "subagent",
        "send",
        "scheduler",
        "env_config",
        "evolution_undo",
    }
)

READ_ONLY_TOOLS = (
    "read", "ls", "search_files", "web_search", "web_fetch", "vision",
    "memory_search", "memory_get", "time",
)

_ALL_TOOLS = "*"


@dataclass(frozen=True)
class SubagentTemplate:
    """One spawnable role."""

    name: str
    # Shown to the main Agent in the spawn tool's description. This sentence is
    # what it routes on, so it says when to pick this type, not what the type is.
    description: str
    prompt: str
    # Tool names, or ["*"] for everything the parent has. BLOCKED_TOOLS is
    # subtracted from both.
    tools: List[str] = field(default_factory=lambda: [_ALL_TOOLS])
    source: str = "builtin"

    def allows_all_tools(self) -> bool:
        return _ALL_TOOLS in self.tools

    def inherits_skills(self) -> bool:
        """Whether the parent's skills are worth putting in front of this type.

        A skill is a workflow written end to end, and most of them finish by
        writing something down. Shown to a sub agent that had those tools
        taken away, it reads as an instruction that cannot be carried out: the
        agent spends turns preparing for a step it will never reach, then says
        so in the report the parent has to read. Full tool set, full skills;
        anything narrower, none.
        """
        return self.allows_all_tools()

    def select_tools(self, available: List) -> List:
        """Pick this template's tools out of the parent's set."""
        allowed = []
        for tool in available:
            if tool.name in BLOCKED_TOOLS:
                continue
            if self.allows_all_tools() or tool.name in self.tools:
                allowed.append(tool)
        return allowed


GENERAL_PURPOSE = SubagentTemplate(
    name="general-purpose",
    description=(
        "Multi-step work that needs both investigation and action: search, read, "
        "run commands, write files. Use when you know the goal but not how many "
        "steps it takes to get there."
    ),
    prompt=(
        "You are a focused sub agent. You have been given one task by the agent "
        "that spawned you, and you cannot see its conversation or ask the user "
        "anything, so work from the task and context you were given. You can "
        "search and read the shared memory / knowledge base for background you "
        "need.\n\n"
        "Finish the task and nothing beyond it, then reply with what you found "
        "or changed, the paths of any files you touched, and anything you could "
        "not resolve. Your reply is the only thing that reaches the agent that "
        "spawned you: intermediate steps are discarded, so leave nothing "
        "important out. Do not pad it either — it lands in that agent's "
        "context window."
    ),
)

EXPLORE = SubagentTemplate(
    name="explore",
    description=(
        "Read-only investigation: find files, search code or documents, gather "
        "facts from the web. Use when the answer is somewhere and needs finding, "
        "and nothing needs to change."
    ),
    prompt=(
        "You are a read-only sub agent. You investigate and report; you never "
        "modify anything. You cannot see the conversation of the agent that "
        "spawned you and cannot ask the user anything, but you can search and "
        "read the shared memory / knowledge base.\n\n"
        "Report what you found, with concrete file paths, line numbers, URLs or "
        "quotes so the answer can be checked without redoing your search. Say so "
        "plainly when you did not find something, rather than guessing."
    ),
    tools=list(READ_ONLY_TOOLS),
)

BUILTIN_TEMPLATES = (GENERAL_PURPOSE, EXPLORE)
DEFAULT_TEMPLATE_NAME = GENERAL_PURPOSE.name


def _parse_tools(raw) -> List[str]:
    if raw is None:
        return [_ALL_TOOLS]
    if isinstance(raw, str):
        names = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        names = [str(part).strip() for part in raw]
    else:
        return [_ALL_TOOLS]
    names = [name for name in names if name]
    return names or [_ALL_TOOLS]


def parse_template(content: str, fallback_name: str, source: str) -> Optional[SubagentTemplate]:
    """Parse one markdown template. Returns None when it is unusable."""
    from agent.skills.frontmatter import parse_frontmatter

    frontmatter = parse_frontmatter(content) or {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    body = body.strip()

    name = str(frontmatter.get("name") or fallback_name).strip()
    description = str(frontmatter.get("description") or "").strip()
    if not name or not description or not body:
        # All three are load-bearing: without a description the main Agent has
        # no basis to route to this type, and without a body it has no
        # instructions to run under.
        return None

    return SubagentTemplate(
        name=name,
        description=description,
        prompt=body,
        tools=_parse_tools(frontmatter.get("tools")),
        source=source,
    )


def load_templates(workspace_dir: Optional[str] = None) -> Dict[str, SubagentTemplate]:
    """Built-in types plus any the user defined, keyed by name.

    A user file reusing a built-in name replaces it, which is how a built-in
    gets customized rather than worked around.
    """
    templates: Dict[str, SubagentTemplate] = {t.name: t for t in BUILTIN_TEMPLATES}

    from common.state_dir import subagents_dir

    directory = subagents_dir(base=workspace_dir) if workspace_dir else subagents_dir()
    if not os.path.isdir(directory):
        return templates

    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".md"):
            continue
        # The shipped format guide lives here too. It is documentation, not a
        # type: loading it would put a bogus entry in front of the Agent on
        # every turn.
        if entry.lower() == "readme.md":
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError as e:
            logger.warning(f"[SubAgent] Cannot read template {path}: {e}")
            continue

        template = parse_template(content, os.path.splitext(entry)[0], source=path)
        if template is None:
            logger.warning(
                f"[SubAgent] Ignoring {path}: a template needs a 'description' "
                f"in its frontmatter and a non-empty body"
            )
            continue
        templates[template.name] = template

    return templates
