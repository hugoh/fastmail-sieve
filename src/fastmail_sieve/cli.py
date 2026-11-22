import argparse
import http.client
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastmail_sieve import commands, config

PROG = "fastmail-sieve"


def package_version():
    try:
        return version(PROG)
    except PackageNotFoundError:
        return "unknown"


class CommandRegistry:
    """Registers each command but keeps it out of argparse's flat list, remembering
    its summary so the help can show the commands grouped by purpose."""

    def __init__(self, subparsers):
        self._subparsers = subparsers
        self.summaries = {}

    def add_parser(self, name, help=None, **kwargs):
        self.summaries[name] = help
        kwargs.setdefault("description", help)
        return self._subparsers.add_parser(name, help=argparse.SUPPRESS, **kwargs)


def grouped_help(summaries):
    lines = []
    for title, modules in commands.GROUPS:
        lines.append(f"{title}:")
        for module in modules:
            name = module.__name__.rsplit(".", 1)[-1]
            lines.append(f"  {name:<10} {summaries[name]}")
        lines.append("")
    lines.append("Run `fastmail-sieve COMMAND --help` for a command's options.")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Keep Fastmail Sieve rules in git: lint, explain, migrate and sync.",
        usage=f"{PROG} [-h] [--version] [-C DIR] COMMAND ...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"{PROG} {package_version()}"
    )
    parser.add_argument(
        "-C",
        "--project",
        metavar="DIR",
        help="run as if started in DIR (default: the current directory, or the "
        "nearest parent that has rules fragments or a fastmail-sieve.toml)",
    )
    registry = CommandRegistry(
        parser.add_subparsers(
            dest="command", metavar="COMMAND", help=argparse.SUPPRESS, prog=PROG
        )
    )
    for command in commands.ALL:
        command.add_parser(registry)
    parser.epilog = grouped_help(registry.summaries)
    return parser


def find_project(args):
    """The project to work on, without changing directory: where `-C` says (or the
    current directory), or, except for `init`, the nearest project above it."""
    start = Path.cwd()
    if args.project:
        start = Path(args.project)
        if not start.is_dir():
            raise RuntimeError(f"{args.project} is not a directory")
        start = start.resolve()
    if args.command == "init":
        return config.Project.load(start)
    root = config.find_root(start)
    if root is None:
        return config.Project(start)
    if root != start:
        print(f"using the project at {root}", file=sys.stderr)
    return config.Project.load(root)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.run(args, find_project(args))
    except (RuntimeError, OSError, ValueError, http.client.HTTPException) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
