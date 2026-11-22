import click
from rich.console import Console

from fastmail_sieve.commands._options import (
    from_file_option,
    invoke,
    live_option,
)
from fastmail_sieve.steps import lint_steps, run_steps


@click.command(
    "lint",
    short_help="check everything: format, syntax, markers, variables, folder ids "
    "and names, then warnings",
)
@click.option(
    "--fix",
    is_flag=True,
    help="reformat your rules first (indentation and :mailboxid folder names)",
)
@click.option(
    "--offline",
    is_flag=True,
    help="skip everything that needs Fastmail: only your rules are checked, "
    "or, with --from-file, the saved script too but not the folders",
)
@click.option("--strict", is_flag=True, help="fail when there are warnings")
@live_option("check")
@from_file_option()
@click.pass_context
def command(ctx, **options):
    """Run every check as a checklist that stops at the first failure: format and
    syntax of your rules, then the assembled script (syntax, markers, variables),
    then the folder stable ids and names, and finally the warnings, which are
    shown but do not fail unless --strict."""
    invoke(ctx, run, options)


def run(args, project):
    steps = lint_steps(
        project,
        offline=args.offline,
        from_file=args.from_file,
        fix=args.fix,
        strict=args.strict,
        live=args.live,
    )
    return run_steps(steps, Console(highlight=False))
