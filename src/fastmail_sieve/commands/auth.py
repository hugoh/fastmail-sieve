import getpass
import os
import sys

from fastmail_sieve.commands._options import progress_console
from fastmail_sieve.fastmail.auth_input import parse_curl, validate_token
from fastmail_sieve.fastmail.credentials import ENV_COOKIE, ENV_TOKEN, store_keychain
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
