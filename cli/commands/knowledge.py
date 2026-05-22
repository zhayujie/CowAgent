"""cow knowledge - Knowledge base management commands."""

import os

import click

from cli.utils import get_project_root


def _get_knowledge_dir():
    """Resolve the knowledge directory path from config or default."""
    try:
        import sys
        sys.path.insert(0, get_project_root())
        from config import conf
        from common.utils import expand_path
        workspace = expand_path(conf().get("agent_workspace", "~/cow"))
    except Exception:
        workspace = os.path.expanduser("~/cow")
    return os.path.join(workspace, "knowledge")


def _get_knowledge_enabled():
    try:
        import sys
        sys.path.insert(0, get_project_root())
        from config import conf
        return conf().get("knowledge", True)
    except Exception:
        return True


@click.group(invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Manage CowAgent knowledge base."""
    if ctx.invoked_subcommand is None:
        click.echo(_stats())


@knowledge.command("list")
def knowledge_list():
    """Display knowledge base file tree."""
    click.echo(_tree())


def _stats() -> str:
    knowledge_dir = _get_knowledge_dir()
    if not os.path.isdir(knowledge_dir):
        return "Knowledge base directory not found."

    enabled = _get_knowledge_enabled()
    total_files = 0
    total_bytes = 0
    cat_count = {}

    for root, dirs, files in os.walk(knowledge_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_root = os.path.relpath(root, knowledge_dir)
        category = rel_root.split(os.sep)[0] if rel_root != "." else "root"
        for f in files:
            if f.endswith(".md") and f not in ("index.md", "log.md"):
                total_files += 1
                total_bytes += os.path.getsize(os.path.join(root, f))
                cat_count[category] = cat_count.get(category, 0) + 1

    status_icon = click.style("enabled", fg="green") if enabled else click.style("disabled", fg="red")
    lines = [
        f"\n  Knowledge Base  [{status_icon}]",
        "",
        f"  Pages:  {total_files}",
        f"  Size:   {total_bytes / 1024:.1f} KB",
        "",
    ]
    if cat_count:
        lines.append("  Categories:")
        for cat in sorted(cat_count.keys()):
            lines.append(f"    {cat}/  ({cat_count[cat]} pages)")
        lines.append("")

    lines.append(f"  Path: {knowledge_dir}")
    lines.append("")
    return "\n".join(lines)


def _tree() -> str:
    knowledge_dir = _get_knowledge_dir()
    if not os.path.isdir(knowledge_dir):
        return "Knowledge base directory not found."

    tree_lines = ["  knowledge/"]

    subdirs = sorted([
        d for d in os.listdir(knowledge_dir)
        if os.path.isdir(os.path.join(knowledge_dir, d)) and not d.startswith(".")
    ])

    for i, subdir in enumerate(subdirs):
        is_last_dir = (i == len(subdirs) - 1)
        branch = "└── " if is_last_dir else "├── "
        subdir_path = os.path.join(knowledge_dir, subdir)
        md_files = sorted([
            f for f in os.listdir(subdir_path)
            if f.endswith(".md") and not f.startswith(".")
        ])
        tree_lines.append(f"  {branch}{subdir}/ ({len(md_files)})")

        child_prefix = "      " if is_last_dir else "  │   "
        max_show = 15
        for j, fname in enumerate(md_files[:max_show]):
            is_last_file = (j == len(md_files[:max_show]) - 1) and len(md_files) <= max_show
            fb = "└── " if is_last_file else "├── "
            name = fname.replace(".md", "")
            tree_lines.append(f"{child_prefix}{fb}{name}")
        if len(md_files) > max_show:
            tree_lines.append(f"{child_prefix}└── ... +{len(md_files) - max_show} more")

    if not subdirs:
        tree_lines.append("  (empty)")

    return "\n" + "\n".join(tree_lines) + "\n"
