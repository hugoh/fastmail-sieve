from pathlib import Path

from rich.console import Console

from fastmail_sieve.commands._options import add_from_file, progress_console
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.sieve.report import build_rules, disabled_ui_rules
from fastmail_sieve.sieve.script import fragment_files, read_fragments
from fastmail_sieve.sieve.variable_docs import load_descriptions
from fastmail_sieve.sieve.variables import descriptions_file, load_report
from fastmail_sieve.sieve.warnings import collect_warnings
from fastmail_sieve.sieve.warnings import run as print_warnings


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "warnings",
        help="list only the warnings (overlaps, duplicates, disabled rules, stale variable docs)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when there are warnings"
    )
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
    script = load_assembled(args.from_file, progress_console())
    docs = load_descriptions(Path(descriptions_file()).read_text(encoding="utf-8"))
    fragments = dict(zip(fragment_files(), read_fragments(), strict=True))
    rules = build_rules(fragments, script, docs)
    warnings = collect_warnings(
        rules, disabled_ui_rules(script), load_report(script).warnings
    )
    return print_warnings(warnings, args.strict, Console(highlight=False))
