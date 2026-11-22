import json
import random
import re
import urllib.parse
from importlib.metadata import PackageNotFoundError, version

import requests
import requests.cookies
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase
from urllib3.util.retry import Retry

SESSION_URL = "https://api.fastmail.com/jmap/session"
MAIL = "urn:ietf:params:jmap:mail"
CONNECT_TIMEOUT_SECONDS = 10
TIMEOUT_SECONDS = 30
ALLOWED_DOMAIN = "fastmail.com"

MAX_RETRIES = 3
BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

# A read can be repeated freely. A write is repeated only when Fastmail has
# plainly not acted on it: the connection never opened, or it answered 429.
READ_RETRY_STATUSES = (429, 502, 503, 504)
WRITE_RETRY_STATUSES = (429,)
READ_ONLY_METHODS = re.compile(r"/(get|query|changes|queryChanges)$|^Validate/sieve$")


class _Retry(Retry):
    """Retry with a real pause before every retry (urllib3 retries a connection
    error at once), jitter so runs do not all come back together, and a ceiling
    on how long a `Retry-After` can make us wait."""

    def get_backoff_time(self):
        tries = len(self.history)
        if tries == 0:
            return 0
        ceiling = min(MAX_BACKOFF_SECONDS, BACKOFF_SECONDS * 2 ** (tries - 1))
        return random.uniform(ceiling / 2, ceiling)

    def get_retry_after(self, response):
        wait = super().get_retry_after(response)
        return None if wait is None else min(wait, MAX_RETRY_AFTER_SECONDS)


def _policy(read_only):
    return _Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES if read_only else 0,
        status=MAX_RETRIES,
        other=0,
        redirect=0,
        status_forcelist=READ_RETRY_STATUSES if read_only else WRITE_RETRY_STATUSES,
        allowed_methods=None,
        respect_retry_after_header=True,
        raise_on_status=False,
    )


class _Bearer(AuthBase):
    """An explicit `auth` also stops requests from replacing the token with
    whatever ~/.netrc says about this host."""

    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


class _NoCookies(requests.cookies.RequestsCookieJar):
    """The cookie is sent by hand; never store or resend what Fastmail sets."""

    def set_cookie(self, cookie, *args, **kwargs):
        return None


def _user_agent():
    try:
        return f"fastmail-sieve/{version('fastmail-sieve')}"
    except PackageNotFoundError:
        return "fastmail-sieve"


_sessions_by_policy = {}


def _http(read_only):
    """One pooled connection set per policy, shared by every call in the run."""
    if read_only not in _sessions_by_policy:
        session = requests.Session()
        session.cookies = _NoCookies()
        session.headers.update(
            {"User-Agent": _user_agent(), "Accept": "application/json"}
        )
        session.mount("https://", HTTPAdapter(max_retries=_policy(read_only)))
        _sessions_by_policy[read_only] = session
    return _sessions_by_policy[read_only]


def is_read_only(body):
    """Whether a request can safely be repeated: a GET, or only methods that read."""
    if body is None:
        return True
    try:
        names = [call[0] for call in body["methodCalls"]]
    except (KeyError, IndexError, TypeError):
        return False
    return bool(names) and all(READ_ONLY_METHODS.search(str(n)) for n in names)


def _check_url(url):
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise RuntimeError(
            "Refusing to send the Fastmail login over "
            f"{parts.scheme or 'an unknown scheme'}: only https is allowed"
        )
    if host != ALLOWED_DOMAIN and not host.endswith("." + ALLOWED_DOMAIN):
        raise RuntimeError(
            f"Refusing to send the Fastmail login to {host or 'an unknown host'}: "
            f"it is not a {ALLOWED_DOMAIN} address"
        )


def _problem(raw):
    """The `type` and `detail` of a JMAP problem answer, as one short safe line."""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    text = ": ".join(
        str(data[key]) for key in ("type", "detail", "description") if data.get(key)
    )
    return re.sub(r"[^\x20-\x7e]", "?", text)[:200]


def _http_error(response, raw, attempts_made):
    code = response.status_code
    hint = ""
    if code in (401, 403):
        hint = (
            " (the token or session may have expired or been revoked: for a "
            "session token, run `fastmail-sieve auth`)"
        )
    elif 300 <= code < 400:
        hint = " (the redirect was refused so that your login is never sent elsewhere)"
    elif code in READ_RETRY_STATUSES and attempts_made:
        hint = " (still busy after retrying: wait a while before trying again)"
    problem = _problem(raw)
    detail = f" [{problem}]" if problem else ""
    return RuntimeError(
        f"Fastmail answered HTTP {code} {response.reason}{detail}{hint}"
    )


def _read_body(response):
    content = b""
    for chunk in response.iter_content(64 * 1024):
        content += chunk
        if len(content) > MAX_RESPONSE_BYTES:
            raise RuntimeError(
                "Fastmail's answer is larger than expected: not reading it"
            )
    return content


def _retried(response):
    return bool(getattr(response.raw.retries, "history", ()))


def jmap(url, credentials, body=None):
    """GET `url`, or POST `body` as JSON, with the stored token and cookie.

    Reads are retried with backoff when Fastmail is busy or unreachable; a write
    is retried only when it provably did not happen."""
    _check_url(url)
    headers = {}
    if credentials.get("cookie"):
        headers["Cookie"] = credentials["cookie"]
    method, kwargs = "GET", {}
    if body is not None:
        method, kwargs = "POST", {"json": body}
    read_only = is_read_only(body)
    try:
        response = _http(read_only).request(
            method,
            url,
            headers=headers,
            auth=_Bearer(credentials["token"]),
            timeout=(CONNECT_TIMEOUT_SECONDS, TIMEOUT_SECONDS),
            allow_redirects=False,
            stream=True,
            **kwargs,
        )
        with response:
            raw = _read_body(response)
            if response.status_code >= 300:
                raise _http_error(response, raw, _retried(response))
            return json.loads(raw)
    except requests.exceptions.Timeout as error:
        raise RuntimeError(
            f"Fastmail did not answer within {TIMEOUT_SECONDS} seconds"
        ) from error
    except requests.exceptions.RequestException as error:
        raise RuntimeError(f"Could not reach Fastmail: {_reason(error)}") from error
    except OSError as error:
        raise RuntimeError(f"Could not reach Fastmail: {error}") from error
    except ValueError as error:
        raise RuntimeError(_NOT_JSON) from error


_NOT_JSON = (
    "Fastmail did not answer with JSON: is something between you and "
    "Fastmail, such as a proxy or a captive portal?"
)


def _reason(error):
    """The readable cause under requests' and urllib3's wrapping."""
    inner = error.args[0] if error.args else error
    inner = getattr(inner, "reason", None) or inner
    return str(inner)


_sessions = {}


def get_session(credentials, call=jmap):
    """The session for this login: asked for once per run when talking to Fastmail."""
    if call is not jmap:
        return call(SESSION_URL, credentials)
    key = (credentials["token"], credentials.get("cookie"))
    if key not in _sessions:
        _sessions[key] = jmap(SESSION_URL, credentials)
    return _sessions[key]


def invoke(credentials, using, method, arguments, call=jmap):
    """Make one JMAP method call on the primary mail account and return its result."""
    session = get_session(credentials, call)
    account = _accounts(session).get(MAIL)
    if account is None:
        raise RuntimeError(
            "Fastmail offered no mail account to these credentials: "
            "an API token needs the Email scope"
        )
    reply = call(
        session["apiUrl"],
        credentials,
        {
            "using": list(using),
            "methodCalls": [[method, {"accountId": account, **arguments}, "0"]],
        },
    )
    try:
        name, result, _ = reply["methodResponses"][0]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"Fastmail's answer to {method} was not in the expected form"
        ) from error
    if name == "error":
        reason = result.get("description") or result.get("type") or result
        raise RuntimeError(
            f"Fastmail rejected {method}: {result.get('type', 'error')}: {reason}"
        )
    return result


def _accounts(session):
    accounts = session.get("primaryAccounts") if isinstance(session, dict) else None
    return accounts if isinstance(accounts, dict) else {}
