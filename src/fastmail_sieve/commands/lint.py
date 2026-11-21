from rich.console import Console

from fastmail_sieve.commands._options import add_from_file, add_live
from fastmail_sieve.steps import lint_steps, run_steps


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "lint",
        help="check everything: format, syntax, markers, variables, folder ids "
        "and names, then warnings",
        description="Run every check as a checklist that stops at the first failure: "
        "format and syntax of your rules, then the assembled script (syntax, "
        "markers, variables), then the folder stable ids and names, and finally "
        "the warnings, which are shown but do not fail unless --strict.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="reformat your rules first (indentation and :mailboxid folder names)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip everything that needs Fastmail: only your rules are checked, "
        "or, with --from-file, the saved script too but not the folders",
    )
    parser.add_argument(
        "--strict", action="store_true", help="fail when there are warnings"
    )
    add_live(parser, "check")
    add_from_file(parser)
    parser.set_defaults(run=run)


def run(args):
    steps = lint_steps(
        offline=args.offline,
        from_file=args.from_file,
        fix=args.fix,
        strict=args.strict,
        live=args.live,
    )
    return run_steps(steps, Console(highlight=False))
