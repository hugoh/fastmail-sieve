import click
from rich.console import Console

from fastmail_sieve.commands._options import confirm, invoke
from fastmail_sieve.commands.diff import unified
from fastmail_sieve.steps import Session, lint_steps, run_steps, write_steps
from fastmail_sieve.ui.tables import safe_text


@click.command(
    "push",
    short_help="check everything, show what changes, then push your rules to Fastmail",
)
@click.option("--yes", is_flag=True, help="push without asking for confirmation")
@click.option("--strict", is_flag=True, help="do not push while there are warnings")
@click.pass_context
def command(ctx, **options):
    """Check everything, show what changes, then push your rules to Fastmail."""
    invoke(ctx, run, options)


def _show(lines, console):
    for line in lines:
        style = (
            "green"
            if line.startswith("+") and not line.startswith("+++")
            else (
                "red" if line.startswith("-") and not line.startswith("---") else "dim"
            )
        )
        console.print(safe_text(line), style=style, markup=False)


def run(args, project):
    console = Console(highlight=False)
    session = Session(project)
    code = run_steps(lint_steps(project, session, strict=args.strict), console)
    if code:
        return code
    changes = unified(session.remote, session.assembled)
    if not changes:
        console.print(
            "Nothing to push: Fastmail already has these rules.", markup=False
        )
        return 0
    console.print()
    _show(changes, console)
    console.print()
    if not args.yes and not confirm("Push these changes to Fastmail?"):
        console.print("✗ Not pushed", style="red", markup=False)
        return 1
    return run_steps(write_steps(session), console)
