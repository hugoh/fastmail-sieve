"""Opt-in cookie discovery (`fastmail-sieve auth --discover`).

This reads data that belongs to other applications: the Fastmail desktop app's
cookie database (decrypted with the "Fastmail Safe Storage" key from the macOS
keychain) and Safari's and Chrome's cookies for fastmail.com. It needs the
`auth` extra and is never run unless asked for.
"""

import contextlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import browser_cookie3
from Cryptodome.Cipher import AES
from Cryptodome.Protocol.KDF import PBKDF2

DOMAIN = "fastmail.com"
COOKIE_PREFIXES = ("__Http-s_", "__Host-s_")
APP_COOKIES = Path.home() / "Library/Application Support/Fastmail/Cookies"
APP_KEYCHAIN_SERVICE = "Fastmail Safe Storage"
HOST_HASH_META_VERSION = 24
DECRYPT_FAILED = (
    "the Fastmail app cookie could not be decrypted: the keychain password or the "
    "cookie format is not what this tool expects"
)


def decrypt_chromium_value(encrypted, password, strip_host_hash):
    key = PBKDF2(password, b"saltysalt", 16, count=1003)
    body = encrypted[3:]
    if not body or len(body) % 16:
        raise ValueError(DECRYPT_FAILED)
    plain = AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(body)
    padding = plain[-1]
    if not 1 <= padding <= 16 or plain[-padding:] != bytes([padding]) * padding:
        raise ValueError(DECRYPT_FAILED)
    plain = plain[:-padding]
    try:
        return (plain[32:] if strip_host_hash else plain).decode()
    except UnicodeDecodeError as error:
        raise ValueError(DECRYPT_FAILED) from error


def app_cookie():
    if not APP_COOKIES.exists():
        return None
    password = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", APP_KEYCHAIN_SERVICE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        shutil.copy(APP_COOKIES, copy)
        with contextlib.closing(sqlite3.connect(copy)) as db:
            version = int(
                db.execute("select value from meta where key='version'").fetchone()[0]
            )
            rows = db.execute(
                "select name, encrypted_value from cookies where host_key like '%fastmail.com'"
            ).fetchall()
    for name, encrypted in rows:
        if name.startswith(COOKIE_PREFIXES):
            value = decrypt_chromium_value(
                encrypted, password.encode(), version >= HOST_HASH_META_VERSION
            )
            return f"{name}={value}"
    return None


def browser_cookies():
    for loader in (browser_cookie3.safari, browser_cookie3.chrome):
        try:
            jar = loader(domain_name=DOMAIN)
        except Exception as error:
            print(f"{loader.__name__}: {error}", file=sys.stderr)
            continue
        for cookie in jar:
            if cookie.name.startswith(COOKIE_PREFIXES):
                yield loader.__name__, f"{cookie.name}={cookie.value}"


def candidate_cookies():
    try:
        app = app_cookie()
    except Exception as error:
        print(f"Fastmail app: {error}", file=sys.stderr)
        app = None
    if app:
        yield "Fastmail app", app
    yield from browser_cookies()


def discover_cookie(token, check):
    """The first cookie `check(token, cookie)` accepts, as (source, cookie)."""
    tried = []
    for source, cookie in candidate_cookies():
        try:
            check(token, cookie)
        except RuntimeError as error:
            tried.append(f"{source}: {error}")
            continue
        return source, cookie
    raise RuntimeError(
        "Fastmail rejected the token with every cookie found:\n  "
        + "\n  ".join(tried or ["no session cookie found"])
        + "\nThe token is tied to the session that minted it: paste the token and cookie "
        "from the same browser request instead."
    )
