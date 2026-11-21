import re

TOKEN_PREFIX = "fma1-"
BEARER = re.compile(r"[Aa]uthorization:\s*Bearer\s+([^\s'\"\\]+)")
COOKIE_HEADER = re.compile(r"""(?:-H|--header)\s+\$?(['"])\s*[Cc]ookie:\s*(.*?)\1""")
COOKIE_FLAG = re.compile(r"""(?:-b|--cookie)\s+\$?(['"])(.*?)\1""")


def clean_token(raw):
    return (
        raw.strip()
        .removeprefix("Authorization:")
        .strip()
        .removeprefix("Bearer ")
        .strip()
    )


def validate_token(raw):
    token = clean_token(raw)
    if not token.startswith(TOKEN_PREFIX):
        raise RuntimeError(
            f"That does not look like a session token: it should start with {TOKEN_PREFIX}"
        )
    return token


def parse_curl(text):
    """The bearer token and cookie from a 'Copy as cURL' command (never echoed back)."""
    text = text.replace("\\\n", " ")
    bearer = BEARER.search(text)
    if not bearer:
        raise RuntimeError(
            "No `Authorization: Bearer …` header found in the pasted command"
        )
    cookie = COOKIE_HEADER.search(text) or COOKIE_FLAG.search(text)
    if not cookie:
        raise RuntimeError(
            "No Cookie header (or -b/--cookie option) found in the pasted command"
        )
    return clean_token(bearer.group(1)), cookie.group(2).strip()
