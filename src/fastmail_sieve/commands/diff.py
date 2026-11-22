import difflib

import click

from fastmail_sieve.commands._options import (
    from_file_option,
    invoke,
    progress_console,
)
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.script import assemble
from fastmail_sieve.ui.tables import safe_text


@click.command("diff", short_help="show what a push would change on Fastmail")
@from_file_option()
@click.pass_context
def command(ctx, **options):
    """Show what a push would change on Fastmail."""
    invoke(ctx, run, options)


def unified(remote, local):
    """Unified diff lines, `+` for what a push adds and `-` for what it removes."""
    return list(
        difflib.unified_diff(
            remote.splitlines(), local.splitlines(), "fastmail", "local", lineterm=""
        )
    )


def run(args, project):
    remote = load_remote(args.from_file, progress_console())
    lines = unified(remote, assemble(remote, *project.read_fragments()))
    if lines:
        print(safe_text("\n".join(lines)))
    return 0
