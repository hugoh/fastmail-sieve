import sys

from fastmail_sieve.commands._options import add_color, add_from_file, progress_console
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.sieve.variables import load_report, render
from fastmail_sieve.ui.tables import terminal_width, use_color


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "variables",
        help="explain the script's variables; fail if one is undefined, unused or undocumented",
    )
    add_color(parser)
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
    report = load_report(load_assembled(args.from_file, progress_console()))
    print(render(report, terminal_width(), use_color(args.color)))
    for warning in report.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if report.errors else 0
