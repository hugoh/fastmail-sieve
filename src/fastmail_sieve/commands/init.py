import click

from fastmail_sieve.commands._options import confirm, invoke
from fastmail_sieve.fastmail.blocks import CHANGED, get_script, set_blocks
from fastmail_sieve.fastmail.credentials import LazySources, pick
from fastmail_sieve.project import scaffold
from fastmail_sieve.ui.tables import echo


@click.command(
    "init",
    short_help="create the rules/ fragments and variables.toml; --remote also "
    "prepares Fastmail",
)
@click.option(
    "--remote",
    is_flag=True,
    help="also add the managed blocks to Fastmail's script if it has none yet "
    "(a one-time write; existing code is kept)",
)
@click.option(
    "--convert-markers",
    is_flag=True,
    help="with --remote, also replace Fastmail-Sieve-Sync's marker comments "
    "around your blocks with this tool's own (one way: Sieve-Sync no longer "
    "recognises the blocks afterwards; your rules are untouched)",
)
@click.option("--yes", is_flag=True, help="with --remote, do not ask first")
@click.pass_context
def command(ctx, **options):
    """Create the rules/ fragments and variables.toml; --remote also prepares
    Fastmail."""
    invoke(ctx, run, options)


def _ensure_unchanged(credentials, script):
    if not get_script(credentials).same_blocks(script):
        raise RuntimeError(CHANGED)


def _remote(args):
    credentials = pick(LazySources(), session_required=True)
    script = get_script(credentials)
    if script.has_markers:
        if args.convert_markers:
            return _convert_markers(args, credentials, script)
        echo("✓ Fastmail already has the managed blocks", style="green")
        return 0
    echo(
        "Your Fastmail Sieve script has no managed blocks yet. This adds three empty ones "
        "(start, middle and end): a one-time write. Code that is already there stays where it is."
    )
    if not args.yes and not confirm("Add the managed blocks to Fastmail?"):
        echo("✗ Not changed", style="red")
        return 1
    _ensure_unchanged(credentials, script)
    set_blocks(credentials, script.with_markers())
    if not get_script(credentials).has_markers:
        raise RuntimeError("Fastmail still reports no managed blocks after the update")
    echo("✓ Added the managed blocks to Fastmail", style="green")
    return 0


def _convert_markers(args, credentials, script):
    if not script.uses_legacy_markers:
        echo(
            "✓ The managed blocks already use fastmail-sieve's own markers",
            style="green",
        )
        return 0
    echo(
        'This replaces the "Managed by Sieve Sync" comments around your three '
        "managed blocks with fastmail-sieve's own. Your rules stay exactly as "
        "they are. Fastmail-Sieve-Sync no longer recognises the blocks afterwards, "
        "so do not run both tools on the same script."
    )
    if not args.yes and not confirm("Convert the markers on Fastmail?"):
        echo("✗ Not changed", style="red")
        return 1
    _ensure_unchanged(credentials, script)
    set_blocks(credentials, script.convert_markers())
    after = get_script(credentials)
    if after.uses_legacy_markers or after.fragments != script.fragments:
        echo(
            "✗ Fastmail's script does not look as expected after the update: "
            "check it with `fastmail-sieve diff`"
        )
        return 1
    echo("✓ Converted the markers", style="green")
    return 0


def run(args, project):
    if args.convert_markers and not args.remote:
        raise RuntimeError("--convert-markers needs --remote")
    created, kept = scaffold(project)
    for name in created:
        echo(f"created {name}")
    for name in kept:
        echo(f"kept    {name} (already there)")
    if args.remote:
        return _remote(args)
    echo(
        "\nNext: `fastmail-sieve auth` to store your credentials, then "
        "`fastmail-sieve init --remote` once to prepare Fastmail's script, then "
        "`fastmail-sieve pull`."
    )
    return 0
