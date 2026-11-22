import sys

import click

from fastmail_sieve.commands._options import (
    from_file_option,
    invoke,
    progress_console,
)
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.migrate import migrate


@click.command(
    "migrate",
    short_help="print custom rules equivalent to your enabled Fastmail UI rules",
)
@from_file_option()
@click.pass_context
def command(ctx, **options):
    """Print custom rules equivalent to your enabled Fastmail UI rules."""
    invoke(ctx, run, options)


def run(args, project):
    result = migrate(load_remote(args.from_file, progress_console()))
    for title in result.skipped:
        print(f"skipped (disabled in Fastmail): {title}", file=sys.stderr)
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    if result.errors:
        return 1
    if not result.snippet:
        print("No enabled UI rules to migrate.", file=sys.stderr)
        return 0
    print(result.snippet, end="")
    return 0
