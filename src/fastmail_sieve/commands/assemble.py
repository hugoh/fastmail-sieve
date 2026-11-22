import sys
from pathlib import Path

import click

from fastmail_sieve.commands._options import (
    from_file_option,
    invoke,
    progress_console,
)
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.ui.tables import safe_text


@click.command(
    "assemble",
    short_help="print the full script: Fastmail's parts plus your fragments",
)
@from_file_option()
@click.option(
    "--output",
    metavar="FILE",
    help="write the script to FILE instead of printing it",
)
@click.pass_context
def command(ctx, **options):
    """Print the full script: Fastmail's parts plus your fragments."""
    invoke(ctx, run, options)


def run(args, project):
    text = load_assembled(project, args.from_file, progress_console())
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        # Piped output is the script byte for byte; on a terminal it must not be
        # able to drive it.
        sys.stdout.write(safe_text(text) if sys.stdout.isatty() else text)
    return 0
