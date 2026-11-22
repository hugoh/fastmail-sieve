import sys
from pathlib import Path

from fastmail_sieve.commands._options import add_from_file, progress_console
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.ui.tables import safe_text


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "assemble", help="print the full script: Fastmail's parts plus your fragments"
    )
    add_from_file(parser)
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="write the script to FILE instead of printing it",
    )
    parser.set_defaults(run=run)


def run(args):
    text = load_assembled(args.from_file, progress_console())
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        # Piped output is the script byte for byte; on a terminal it must not be
        # able to drive it.
        sys.stdout.write(safe_text(text) if sys.stdout.isatty() else text)
    return 0
