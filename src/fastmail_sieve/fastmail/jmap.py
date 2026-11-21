import json
import urllib.error
import urllib.request

SESSION_URL = "https://api.fastmail.com/jmap/session"
MAIL = "urn:ietf:params:jmap:mail"
TIMEOUT_SECONDS = 30


def jmap(url, credentials, body=None):
    """GET `url`, or POST `body` as JSON, with the stored token and cookie."""
    headers = {"Authorization": f"Bearer {credentials['token']}"}
    if credentials.get("cookie"):
        headers["Cookie"] = credentials["cookie"]
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        hint = (
            " (the token or session may have expired or been revoked: for a session token, "
            "run `fastmail-sieve auth`)"
            if error.code in (401, 403)
            else ""
        )
        raise RuntimeError(
            f"Fastmail answered HTTP {error.code} {error.reason}{hint}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Fastmail: {error.reason}") from error


def get_session(credentials, call=jmap):
    return call(SESSION_URL, credentials)


def invoke(credentials, using, method, arguments, call=jmap):
    """Make one JMAP method call on the primary mail account and return its result."""
    session = call(SESSION_URL, credentials)
    account = session["primaryAccounts"][MAIL]
    reply = call(
        session["apiUrl"],
        credentials,
        {
            "using": list(using),
            "methodCalls": [[method, {"accountId": account, **arguments}, "0"]],
        },
    )
    name, result, _ = reply["methodResponses"][0]
    if name == "error":
        reason = result.get("description") or result.get("type") or result
        raise RuntimeError(
            f"Fastmail rejected {method}: {result.get('type', 'error')}: {reason}"
        )
    return result
