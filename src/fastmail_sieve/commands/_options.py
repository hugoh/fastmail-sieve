from rich.console import Console

COLORS = ("auto", "always", "never")


def progress_console():
    """Progress goes to stderr, so stdout stays clean for the command's output."""
    return Console(stderr=True, highlight=False)


def add_from_file(parser, what="the script Fastmail has"):
    parser.add_argument(
        "--from-file",
        metavar="FILE",
        help=f"read a saved copy of {what} instead of fetching it from Fastmail",
    )


def add_live(parser, what):
    parser.add_argument(
        "--live",
        action="store_true",
        help=f"{what} the script exactly as Fastmail has it now, ignoring your "
        "rules/ files (the default is what a push would produce: Fastmail's "
        "script with your rules in the managed blocks)",
    )


def add_color(parser):
    parser.add_argument(
        "--color", choices=COLORS, default="auto", help="colour the output"
    )


def confirm(question):
    """Ask yes/no on the terminal; no answer at all (closed stdin) counts as no."""
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
