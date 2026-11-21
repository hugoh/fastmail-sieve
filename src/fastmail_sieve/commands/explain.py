import sys

from fastmail_sieve.commands._options import add_color, add_from_file, progress_console
from fastmail_sieve.remote import load_assembled
from fastmail_sieve.sieve.report import (
    build_full_rules,
    build_rules,
    disabled_ui_rules,
    render,
)
from fastmail_sieve.sieve.script import fragment_files, read_fragments
from fastmail_sieve.sieve.variables import load_report, load_variable_docs
from fastmail_sieve.sieve.variables import render as render_variables
from fastmail_sieve.ui.tables import terminal_width, use_color

TOPICS = ("rules", "script", "variables")


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "explain",
        help="explain your rules, the whole script or its variables in plain language",
        description="Explain the script in plain language: your rules and your "
        "Fastmail UI rules (rules, the default), the whole script in execution "
        "order with Fastmail's own rules dimmed (script), or the variables and "
        "where they are set and read (variables).",
    )
    parser.add_argument(
        "topic", nargs="?", choices=TOPICS, default="rules", help="what to explain"
    )
    parser.add_argument("--width", type=int, help="table width in columns")
    add_color(parser)
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
    script = load_assembled(args.from_file, progress_console())
    width, color = terminal_width(args.width), use_color(args.color)
    if args.topic == "variables":
        report = load_report(script)
        print(render_variables(report, width, color))
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        for error in report.errors:
            print(f"error: {error}", file=sys.stderr)
        return 0
    if args.topic == "script":
        rules, sequence = build_full_rules(script, load_variable_docs()), True
    else:
        fragments = dict(zip(fragment_files(), read_fragments(), strict=True))
        rules, sequence = build_rules(fragments, script, load_variable_docs()), False
    print(render(rules, width, color, disabled_ui_rules(script), sequence))
    return 0
