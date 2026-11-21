from rich.console import Console

from fastmail_sieve.steps import lint_steps, offline_steps, run_steps


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "lint",
        help="check format, syntax, markers, folder stable ids and folder names",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="only the checks that need no Fastmail access (format and syntax of your rules)",
    )
    parser.set_defaults(run=run)


def run(args):
    steps = offline_steps() if args.offline else lint_steps()
    return run_steps(steps, Console(highlight=False))
