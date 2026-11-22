import click

from fastmail_sieve.commands._options import (
    color_option,
    from_file_option,
    invoke,
    live_option,
    progress_console,
)
from fastmail_sieve.remote import load_assembled, load_remote
from fastmail_sieve.sieve.report import (
    build_full_rules,
    build_rules,
    disabled_ui_rules,
    render,
)
from fastmail_sieve.sieve.script import live_fragments
from fastmail_sieve.sieve.variables import load_report, load_variable_docs
from fastmail_sieve.sieve.variables import render as render_variables
from fastmail_sieve.ui.tables import echo, make_console

TOPICS = ("rules", "script", "variables")


@click.command(
    "explain",
    short_help="explain your rules, the whole script or its variables in plain language",
)
@click.argument("topic", type=click.Choice(TOPICS), default="rules", required=False)
@click.option("--width", type=int, help="table width in columns")
@color_option
@live_option("explain")
@from_file_option()
@click.pass_context
def command(ctx, **options):
    """Explain the script in plain language: your rules and your Fastmail UI rules
    (rules, the default), the whole script in execution order with Fastmail's own
    rules dimmed (script), or the variables and where they are set and read
    (variables)."""
    invoke(ctx, run, options)


def run(args, project):
    console = progress_console()
    script = (
        load_remote(args.from_file, console)
        if args.live
        else load_assembled(project, args.from_file, console)
    )
    table_console = make_console(args.color, args.width)
    if args.topic == "variables":
        report = load_report(
            project, script, live_fragments(script) if args.live else None
        )
        echo(render_variables(report, table_console))
        for warning in report.warnings:
            echo(f"warning: {warning}", err=True)
        for error in report.errors:
            echo(f"error: {error}", err=True)
        return 0
    if args.topic == "script":
        rules, sequence = build_full_rules(script, load_variable_docs(project)), True
    else:
        texts = live_fragments(script) if args.live else project.read_fragments()
        fragments = dict(zip(project.fragment_files, texts, strict=True))
        rules, sequence = (
            build_rules(fragments, script, load_variable_docs(project)),
            False,
        )
    echo(render(rules, table_console, disabled_ui_rules(script), sequence))
    return 0
