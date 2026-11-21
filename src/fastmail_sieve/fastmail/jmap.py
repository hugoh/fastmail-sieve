import json
import urllib.error
import urllib.parse
import urllib.request

SESSION_URL = "https://api.fastmail.com/jmap/session"
MAIL = "urn:ietf:params:jmap:mail"
TIMEOUT_SECONDS = 30
ALLOWED_DOMAIN = "fastmail.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would resend the Authorization and Cookie headers to wherever a
    redirect points, even another host: the login must never leave Fastmail."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


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


def jmap(url, credentials, body=None):
    """GET `url`, or POST `body` as JSON, with the stored token and cookie."""
    _check_url(url)
    headers = {"Authorization": f"Bearer {credentials['token']}"}
    if credentials.get("cookie"):
        headers["Cookie"] = credentials["cookie"]
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        hint = ""
        if error.code in (401, 403):
            hint = (
                " (the token or session may have expired or been revoked: for a "
                "session token, run `fastmail-sieve auth`)"
            )
        elif 300 <= error.code < 400:
            hint = (
                " (the redirect was refused so that your login is never sent elsewhere)"
            )
        raise RuntimeError(
            f"Fastmail answered HTTP {error.code} {error.reason}{hint}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Fastmail: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError(
            f"Fastmail did not answer within {TIMEOUT_SECONDS} seconds"
        ) from error
    except OSError as error:
        raise RuntimeError(f"Could not reach Fastmail: {error}") from error
    except ValueError as error:
        raise RuntimeError(
            "Fastmail did not answer with JSON: is something between you and "
            "Fastmail, such as a proxy or a captive portal?"
        ) from error


def get_session(credentials, call=jmap):
    return call(SESSION_URL, credentials)


def invoke(credentials, using, method, arguments, call=jmap):
    """Make one JMAP method call on the primary mail account and return its result."""
    session = call(SESSION_URL, credentials)
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
