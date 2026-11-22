from types import SimpleNamespace

import click

from fastmail_sieve.ui.tables import make_console

COLORS = ("auto", "always", "never")


def progress_console():
    """Progress goes to stderr, so stdout stays clean for the command's output."""
    return make_console(stderr=True)


def invoke(ctx, run, options):
    """Run a command: `run(args, project)` gets the options as attributes and the
    project to work on, and its return value is the exit code."""
    project = ctx.obj(ctx.command.name)
    ctx.exit(run(SimpleNamespace(**options), project) or 0)


def from_file_option(what="the script Fastmail has"):
    return click.option(
        "--from-file",
        metavar="FILE",
        help=f"read a saved copy of {what} instead of fetching it from Fastmail",
    )


def live_option(what):
    return click.option(
        "--live",
        is_flag=True,
        help=f"{what} the script exactly as Fastmail has it now, ignoring your "
        "rules/ files (the default is what a push would produce: Fastmail's "
        "script with your rules in the managed blocks)",
    )


color_option = click.option(
    "--color", type=click.Choice(COLORS), default="auto", help="colour the output"
)


def confirm(question):
    """Ask yes/no on the terminal; no answer at all (closed stdin) counts as no."""
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
