from pathlib import Path

from fastmail_sieve.commands._options import add_color, add_from_file, progress_console
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.sieve.report import (
    build_full_rules,
    build_rules,
    disabled_ui_rules,
    render,
)
from fastmail_sieve.sieve.script import fragment_files, read_fragments
from fastmail_sieve.sieve.variable_docs import load_descriptions
from fastmail_sieve.sieve.variables import descriptions_file
from fastmail_sieve.ui.tables import terminal_width, use_color


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "explain",
        help="explain your rules and your Fastmail UI rules in plain language",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="show the whole assembled script in execution order, Fastmail's own rules dimmed",
    )
    parser.add_argument("--width", type=int, help="table width in columns")
    add_color(parser)
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
    script = load_assembled(args.from_file, progress_console())
    docs = load_descriptions(Path(descriptions_file()).read_text(encoding="utf-8"))
    if args.full:
        rules, sequence = build_full_rules(script, docs), True
    else:
        fragments = dict(zip(fragment_files(), read_fragments(), strict=True))
        rules, sequence = build_rules(fragments, script, docs), False
    width, color = terminal_width(args.width), use_color(args.color)
    print(render(rules, width, color, disabled_ui_rules(script), sequence))
    return 0
