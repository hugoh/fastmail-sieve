import getpass
import os
import sys

from fastmail_sieve.commands._options import progress_console
from fastmail_sieve.fastmail.auth_input import parse_curl, validate_token
from fastmail_sieve.fastmail.credentials import (
    ENV_COOKIE,
    ENV_TOKEN,
    TIER_LABELS,
    inspect_sources,
    pick,
    store_keychain,
)
from fastmail_sieve.fastmail.jmap import SESSION_URL, jmap

DISCOVERY_NOTICE = """\
--discover reads data that belongs to other apps, to find the cookie for you:
  - it asks the macOS keychain for the "Fastmail Safe Storage" key and uses it to
    decrypt the Fastmail desktop app's cookie database;
  - it reads the fastmail.com cookies stored by Safari and Chrome.
Nothing leaves your machine except the check against Fastmail's session URL.
macOS may ask you to allow the keychain access."""


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "auth",
        help="check the Fastmail token and cookie and store them in the keychain",
        description="Store the browser session token (fma1-…) and cookie in the keychain. "
        "They are a full web session: treat them like a password. By default you are "
        "prompted for both with hidden input.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read a pasted 'Copy as cURL' command from standard input, "
        "for example `pbpaste | fastmail-sieve auth --stdin`",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="find the cookie in the Fastmail app or a browser instead of asking for it "
        "(needs the auth extra; reads other apps' stored data)",
    )
    parser.set_defaults(run=run)
    actions = parser.add_subparsers(dest="auth_command", metavar="[status]")
    status = actions.add_parser(
        "status",
        help="show which credentials are available and where each comes from",
        description="Show each credential source in the order it is tried, what it "
        "provides, and which credentials each kind of command would use. Values "
        "are never shown. Nothing is sent to Fastmail: run `doctor` to check "
        "that they work.",
    )
    status.set_defaults(run=run_status)


def discover_cookie(token, check):
    try:
        from fastmail_sieve.fastmail import auth_discovery
    except ImportError as error:
        raise RuntimeError(
            "--discover needs the auth extra: install `fastmail-sieve[auth]` "
            "(or run `uv run --extra auth fastmail-sieve auth --discover`)"
        ) from error
    return auth_discovery.discover_cookie(token, check)


def _username(token, cookie):
    return jmap(SESSION_URL, {"token": token, "cookie": cookie})["username"]


def _collect(args, console):
    if args.stdin:
        token, cookie = parse_curl(sys.stdin.read())
        return validate_token(token), cookie
    token = validate_token(
        os.environ.get(ENV_TOKEN) or getpass.getpass("Fastmail token (fma1-…): ")
    )
    cookie = os.environ.get(ENV_COOKIE)
    if cookie:
        return token, cookie
    if args.discover:
        console.print(DISCOVERY_NOTICE, markup=False)
        source, cookie = discover_cookie(token, _username)
        console.print(f"Found a cookie that Fastmail accepts ({source})", markup=False)
        return token, cookie
    return token, clean_cookie(getpass.getpass("Fastmail cookie (__Http-s_…=…): "))


def clean_cookie(raw):
    return raw.strip().removeprefix("Cookie:").strip()


def run(args):
    console = progress_console()
    token, cookie = _collect(args, console)
    username = _username(token, cookie)
    store_keychain(username, token, cookie)
    console.print(
        f"✓ Stored credentials for {username} in the keychain",
        style="green",
        markup=False,
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


def run_status(args):
    statuses = inspect_sources()
    print("Credential sources, in the order they are tried:")
    for index, status in enumerate(statuses, start=1):
        print(_row(index, status))
    gathered = [(s.name, s.found) for s in statuses if s.found]
    print("\nUsed for:")
    usable = []
    for label, session_required in USES:
        chosen, text = _use(gathered, session_required)
        usable.append(chosen is not None)
        print(f"  {label:<40} {text}")
    return 0 if any(usable) else 1
