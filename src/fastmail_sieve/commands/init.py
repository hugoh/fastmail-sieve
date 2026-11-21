from pathlib import Path

from fastmail_sieve.commands._options import confirm
from fastmail_sieve.fastmail.blocks import get_script, set_blocks
from fastmail_sieve.fastmail.credentials import gather, pick
from fastmail_sieve.project import scaffold


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "init",
        help="create the rules/ fragments and variables.toml; --remote also prepares Fastmail",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="also add the managed blocks to Fastmail's script if it has none yet "
        "(a one-time write; existing code is kept)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="with --remote, do not ask first"
    )
    parser.set_defaults(run=run)


def _remote(args):
    credentials = pick(gather(), session_required=True)
    script = get_script(credentials)
    if script.has_markers:
        print("✓ Fastmail already has the managed blocks")
        return 0
    print(
        "Your Fastmail Sieve script has no managed blocks yet. This adds three empty ones "
        "(start, middle and end): a one-time write. Code that is already there stays where it is."
    )
    if not args.yes and not confirm("Add the managed blocks to Fastmail?"):
        print("✗ Not changed")
        return 1
    set_blocks(credentials, script.with_markers())
    if not get_script(credentials).has_markers:
        raise RuntimeError("Fastmail still reports no managed blocks after the update")
    print("✓ Added the managed blocks to Fastmail")
    return 0


def run(args):
    created, kept = scaffold(Path.cwd())
    for name in created:
        print(f"created {name}")
    for name in kept:
        print(f"kept    {name} (already there)")
    if args.remote:
        return _remote(args)
    print(
        "\nNext: `fastmail-sieve auth` to store your credentials, then "
        "`fastmail-sieve init --remote` once to prepare Fastmail's script, then "
        "`fastmail-sieve pull`."
    )
    return 0
