import getpass
import os
import sys

import click

from fastmail_sieve.commands._options import invoke, progress_console
from fastmail_sieve.fastmail.auth_input import parse_curl, validate_token
from fastmail_sieve.fastmail.credentials import (
    ENV_COOKIE,
    ENV_TOKEN,
    TIER_LABELS,
    delete_keychain,
    inspect_sources,
    keychain_backend,
    pick,
    store_keychain,
)
from fastmail_sieve.fastmail.jmap import SESSION_URL, jmap


@click.group(
    "auth",
    invoke_without_command=True,
    short_help="check the Fastmail token and cookie and store them in the keychain",
)
@click.option(
    "--stdin",
    is_flag=True,
    help="read a pasted 'Copy as cURL' command from standard input, "
    "for example `pbpaste | fastmail-sieve auth --stdin`",
)
@click.pass_context
def command(ctx, stdin):
    """Store the browser session token (fma1-…) and cookie in the keychain. They
    are a full web session: treat them like a password. By default you are
    prompted for both with hidden input."""
    if ctx.invoked_subcommand is None:
        invoke(ctx, run, {"stdin": stdin})


@command.command(
    "status",
    short_help="show which credentials are available and where each comes from",
)
@click.pass_context
def status_command(ctx):
    """Show each credential source in the order it is tried, what it provides,
    and which credentials each kind of command would use. Values are never
    shown. Nothing is sent to Fastmail: run `doctor` to check that they work."""
    invoke(ctx, run_status, {})


@command.command("clear", short_help="remove the stored credentials from the keychain")
@click.pass_context
def clear_command(ctx):
    """Delete the token, cookie and username that `auth` stored in the keychain.
    Credentials in environment variables or from a credential command are not
    touched. Log out of Fastmail's web session as well if you want the token
    itself revoked."""
    invoke(ctx, run_clear, {})


def _username(token, cookie):
    session = jmap(SESSION_URL, {"token": token, "cookie": cookie})
    username = session.get("username") if isinstance(session, dict) else None
    if not isinstance(username, str) or not username:
        raise RuntimeError(
            "Fastmail's answer had no username: these credentials were not stored"
        )
    return username


def _collect(args):
    if args.stdin:
        token, cookie = parse_curl(sys.stdin.read())
        return validate_token(token), cookie
    token = validate_token(
        os.environ.get(ENV_TOKEN) or getpass.getpass("Fastmail token (fma1-…): ")
    )
    cookie = os.environ.get(ENV_COOKIE)
    if cookie:
        return token, cookie
    return token, clean_cookie(getpass.getpass("Fastmail cookie (__Http-s_…=…): "))


def clean_cookie(raw):
    return raw.strip().removeprefix("Cookie:").strip()


def run(args, project):
    console = progress_console()
    token, cookie = _collect(args)
    username = _username(token, cookie)
    store_keychain(username, token, cookie)
    console.print(
        f"✓ Stored credentials for {username} in the keychain",
        style="green",
        markup=False,
    )
    return 0


def run_clear(args, project):
    removed = delete_keychain()
    if removed:
        print(f"✓ Removed {removed} stored credential entries from the keychain")
    else:
        print("Nothing was stored in the keychain.")
    print(
        "Credentials in the environment or from a credential command are not "
        "touched, and the Fastmail session itself stays valid until you log out "
        "in Fastmail."
    )
    return 0


MARKS = {"found": "✓", "incomplete": "!", "failed": "✗"}
USES = (
    ("script (pull, push, diff, explain, ...)", True),
    ("folders (folders, lint's folder checks)", False),
)


def _row(index, status):
    mark = MARKS.get(status.state, "·")
    if status.state == "found":
        provides = ", ".join(TIER_LABELS[kind] for kind in status.tiers)
        text = f"found: {provides}"
        if status.detail:
            text += f" ({status.detail})"
    else:
        text = status.state + (f" ({status.detail})" if status.detail else "")
    return f"  {mark} {index}. {status.name:<18} {text}"


def _use(gathered, session_required):
    try:
        chosen = pick(gathered, session_required)
    except RuntimeError:
        only_api = any(found["api"] for _, found in gathered)
        if session_required and only_api:
            return None, (
                "not available: only an API token is available, which cannot read "
                "the script (run `fastmail-sieve auth`)"
            )
        return None, "not available (run `fastmail-sieve auth`)"
    return chosen, f"{TIER_LABELS[chosen['kind']]} from {chosen['source']}"


def run_status(args, project):
    statuses = inspect_sources()
    print("Credential sources, in the order they are tried:")
    for index, status in enumerate(statuses, start=1):
        print(_row(index, status))
    name, kind = keychain_backend()
    note = {
        "file": " (stores credentials in a file: weaker than the OS keychain)",
        "none": " (no usable keychain)",
    }.get(kind, "")
    print(f"\nKeychain backend: {name or 'none'}{note}")
    gathered = [(s.name, s.found) for s in statuses if s.found]
    print("\nUsed for:")
    usable = []
    for label, session_required in USES:
        chosen, text = _use(gathered, session_required)
        usable.append(chosen is not None)
        print(f"  {label:<40} {text}")
    return 0 if any(usable) else 1
