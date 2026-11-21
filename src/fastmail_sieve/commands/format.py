import sys

from fastmail_sieve.sieve.format import format_files
from fastmail_sieve.sieve.script import fragment_files


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "format",
        help="re-indent rules by brace depth and normalise :mailboxid folder names",
    )
    parser.add_argument(
        "files", nargs="*", help="files to format (default: the rules/ fragments)"
    )
    parser.add_argument(
        "--check", action="store_true", help="only report files that need formatting"
    )
    parser.set_defaults(run=run)


def run(args):
    unformatted = format_files(args.files or list(fragment_files()), check=args.check)
    verb = "needs formatting" if args.check else "formatted"
    for name in unformatted:
        print(f"{name}: {verb}", file=sys.stderr)
    return 1 if args.check and unformatted else 0
