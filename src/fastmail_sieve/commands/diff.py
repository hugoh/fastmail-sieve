import difflib

from fastmail_sieve.commands._options import add_from_file, progress_console
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.script import assemble, read_fragments


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "diff", help="show what a push would change on Fastmail"
    )
    add_from_file(parser)
    parser.set_defaults(run=run)


def unified(remote, local):
    """Unified diff lines, `+` for what a push adds and `-` for what it removes."""
    return list(
        difflib.unified_diff(
            remote.splitlines(), local.splitlines(), "fastmail", "local", lineterm=""
        )
    )


def run(args):
    remote = load_remote(args.from_file, progress_console())
    lines = unified(remote, assemble(remote, *read_fragments()))
    if lines:
        print("\n".join(lines))
    return 0
