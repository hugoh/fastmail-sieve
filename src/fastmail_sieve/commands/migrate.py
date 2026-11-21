import sys

from fastmail_sieve.commands._options import add_from_file, progress_console
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.migrate import migrate


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "migrate",
        help="print custom rules equivalent to your enabled Fastmail UI rules",
    )
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
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
