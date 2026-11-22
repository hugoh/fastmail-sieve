from fastmail_sieve.commands._options import confirm
from fastmail_sieve.fastmail.blocks import CHANGED, get_script, set_blocks
from fastmail_sieve.fastmail.credentials import LazySources, pick
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
        "--convert-markers",
        action="store_true",
        help="with --remote, also replace Fastmail-Sieve-Sync's marker comments "
        "around your blocks with this tool's own (one way: Sieve-Sync no longer "
        "recognises the blocks afterwards; your rules are untouched)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="with --remote, do not ask first"
    )
    parser.set_defaults(run=run)


def _ensure_unchanged(credentials, script):
    if not get_script(credentials).same_blocks(script):
        raise RuntimeError(CHANGED)


def _remote(args):
    credentials = pick(LazySources(), session_required=True)
    script = get_script(credentials)
    if script.has_markers:
        if args.convert_markers:
            return _convert_markers(args, credentials, script)
        print("✓ Fastmail already has the managed blocks")
        return 0
    print(
        "Your Fastmail Sieve script has no managed blocks yet. This adds three empty ones "
        "(start, middle and end): a one-time write. Code that is already there stays where it is."
    )
    if not args.yes and not confirm("Add the managed blocks to Fastmail?"):
        print("✗ Not changed")
        return 1
    _ensure_unchanged(credentials, script)
    set_blocks(credentials, script.with_markers())
    if not get_script(credentials).has_markers:
        raise RuntimeError("Fastmail still reports no managed blocks after the update")
    print("✓ Added the managed blocks to Fastmail")
    return 0


def _convert_markers(args, credentials, script):
    if not script.uses_legacy_markers:
        print("✓ The managed blocks already use fastmail-sieve's own markers")
        return 0
    print(
        'This replaces the "Managed by Sieve Sync" comments around your three '
        "managed blocks with fastmail-sieve's own. Your rules stay exactly as "
        "they are. Fastmail-Sieve-Sync no longer recognises the blocks afterwards, "
        "so do not run both tools on the same script."
    )
    if not args.yes and not confirm("Convert the markers on Fastmail?"):
        print("✗ Not changed")
        return 1
    _ensure_unchanged(credentials, script)
    set_blocks(credentials, script.convert_markers())
    after = get_script(credentials)
    if after.uses_legacy_markers or after.fragments != script.fragments:
        print(
            "✗ Fastmail's script does not look as expected after the update: "
            "check it with `fastmail-sieve diff`"
        )
        return 1
    print("✓ Converted the markers")
    return 0


def run(args, project):
    if args.convert_markers and not args.remote:
        raise RuntimeError("--convert-markers needs --remote")
    created, kept = scaffold(project)
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
