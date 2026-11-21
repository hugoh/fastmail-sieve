import argparse
import os
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


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Keep Fastmail Sieve rules in git: lint, explain, migrate and sync.",
    )
    parser.add_argument(
        "--version", action="version", version=f"{PROG} {package_version()}"
    )
    parser.add_argument(
        "-C",
        "--project",
        metavar="DIR",
        help="run as if started in DIR (default: the current directory, or the "
        "nearest parent that has a rules/ directory or a fastmail-sieve.toml)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in commands.ALL:
        command.add_parser(subparsers)
    return parser


def enter_project(args):
    """Move to the project root and load its config; `init` starts where it is told."""
    if args.project:
        target = Path(args.project)
        if not target.is_dir():
            raise RuntimeError(f"{args.project} is not a directory")
        os.chdir(target)
    if args.command == "init":
        config.use(config.load_config(Path.cwd()))
        return
    root = config.find_root(Path.cwd())
    if root:
        os.chdir(root)
        config.use(config.load_config(root))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        enter_project(args)
        return args.run(args)
    except RuntimeError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
