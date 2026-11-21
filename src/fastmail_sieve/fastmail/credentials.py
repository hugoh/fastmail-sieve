import json
import os
import shlex
import subprocess

KEYCHAIN_SERVICE = "fastmail-sieve-rules"
CREDENTIAL_FIELDS = ("username", "token", "cookie")
ENV_TOKEN = "FASTMAIL_SIEVE_TOKEN"
ENV_COOKIE = "FASTMAIL_SIEVE_COOKIE"
ENV_API_TOKEN = "FASTMAIL_API_TOKEN"
ENV_COMMAND = "FASTMAIL_SIEVE_CREDENTIAL_COMMAND"
COMMAND_TIMEOUT_SECONDS = 60


def check_credentials(values):
    missing = [field for field in ("token", "cookie") if not values.get(field)]
    if missing:
        raise RuntimeError(
            f"Missing {', '.join(missing)} in the keychain: run `fastmail-sieve auth`"
        )
    return values


def read_keychain():
    """The stored values, or None where there is no usable keychain (headless Linux, CI)."""
    try:
        import keyring

        return {f: keyring.get_password(KEYCHAIN_SERVICE, f) for f in CREDENTIAL_FIELDS}
    except Exception:
        return None


def store_keychain(username, token, cookie):
    try:
        import keyring

        for field, value in zip(
            CREDENTIAL_FIELDS, (username, token, cookie), strict=True
        ):
            keyring.set_password(KEYCHAIN_SERVICE, field, value)
    except Exception as error:
        raise RuntimeError(
            "Fastmail accepted the credentials, but nothing was stored: there is no usable "
            f"keychain here ({type(error).__name__}). Set {ENV_TOKEN} and {ENV_COOKIE}, "
            f"or {ENV_COMMAND}, instead."
        ) from error


def _session(token, cookie, username=None):
    if not (token and cookie):
        return None
    return {"token": token, "cookie": cookie, "username": username}


def _api(token):
    return {"token": token, "cookie": None, "username": None} if token else None


def _found(session, api):
    return {"session": session, "api": api} if session or api else None


def _from_environment(environ):
    return _found(
        _session(environ.get(ENV_TOKEN), environ.get(ENV_COOKIE)),
        _api(environ.get(ENV_API_TOKEN)),
    )


def _from_command(command, run):
    try:
        completed = run(
            shlex.split(command),
            stdout=subprocess.PIPE,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, PermissionError) as error:
        raise RuntimeError(
            f"The credential command could not be run: {error.strerror or 'not executable'}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"The credential command did not finish within {COMMAND_TIMEOUT_SECONDS} seconds"
        ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            f"The credential command failed with exit status {completed.returncode}"
        )
    try:
        data = json.loads(completed.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise RuntimeError(
            'The credential command must print JSON such as {"token": "...", "cookie": "..."}'
        )
    return _found(
        _session(data.get("token"), data.get("cookie"), data.get("username")),
        _api(data.get("api_token")),
    )


def _from_keychain(read):
    values = read()
    if not values:
        return None
    return _found(
        _session(values.get("token"), values.get("cookie"), values.get("username")),
        None,
    )


def _sources(environ, keychain, run):
    """Where credentials may come from, in precedence order, read lazily."""
    yield "environment", _from_environment(environ)
    command = environ.get(ENV_COMMAND)
    if command:
        yield "credential command", _from_command(command, run)
    yield "keychain", _from_keychain(keychain)


def gather(environ=None, keychain=None, run=subprocess.run):
    """Every source that has credentials, as (source, {"session": ..., "api": ...})."""
    environ = os.environ if environ is None else environ
    keychain = keychain or read_keychain
    return [(name, found) for name, found in _sources(environ, keychain, run) if found]


def _chosen(source, credentials, kind):
    return {**credentials, "source": source, "kind": kind}


def _missing(session_required, have_api_token):
    if session_required and have_api_token:
        return (
            "This needs the browser session token and cookie: a Fastmail API token cannot "
            "read or write the Sieve script. Run `fastmail-sieve auth`, or set "
            f"{ENV_TOKEN} and {ENV_COOKIE}."
        )
    message = (
        "No Fastmail credentials found. Run `fastmail-sieve auth` to store them in the "
        f"keychain, or set {ENV_TOKEN} and {ENV_COOKIE}, or set {ENV_COMMAND} to a "
        "command that prints them as JSON"
    )
    if not session_required:
        message += f" ({ENV_API_TOKEN} also works for folder lookups)"
    return message + "."


def pick(gathered, session_required=True):
    """The credentials to use. The script needs the session pair; a folder lookup
    prefers a scoped API token when there is one."""
    seen = []
    for source, found in gathered:
        seen.append((source, found))
        if session_required and found["session"]:
            return _chosen(source, found["session"], "session")
        if not session_required and found["api"]:
            return _chosen(source, found["api"], "api")
    if not session_required:
        for source, found in seen:
            if found["session"]:
                return _chosen(source, found["session"], "session")
    raise RuntimeError(
        _missing(session_required, any(found["api"] for _, found in seen))
    )


def load_credentials(
    session_required=True, environ=None, keychain=None, run=subprocess.run
):
    environ = os.environ if environ is None else environ
    keychain = keychain or read_keychain
    sources = (
        (name, found) for name, found in _sources(environ, keychain, run) if found
    )
    return pick(sources, session_required)
