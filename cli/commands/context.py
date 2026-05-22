"""cow context - Context management commands."""

import click


CHAT_HINT = (
    "Context commands operate on the running agent's memory.\n"
    "Please send the command in a chat conversation instead:\n\n"
    "  /context        - View current context info\n"
    "  /context clear  - Clear conversation context"
)


@click.group(invoke_without_command=True)
@click.pass_context
def context(ctx):
    """View or manage conversation context.

    Context commands need access to the running agent's memory.
    Use them in chat conversations: /context or /context clear
    """
    if ctx.invoked_subcommand is None:
        click.echo(f"\n  {CHAT_HINT}\n")


@context.command()
def clear():
    """Clear conversation context (messages history)."""
    click.echo(f"\n  {CHAT_HINT}\n")
