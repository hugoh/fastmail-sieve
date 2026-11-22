import re

from fastmail_sieve.fastmail.jmap import MAIL, invoke, jmap
from fastmail_sieve.sieve.format import canonical_inbox, sieve_folder_name
from fastmail_sieve.ui.tables import safe_text, strip_variation_selectors

USING = ["urn:ietf:params:jmap:core", MAIL]
REFERENCE = re.compile(
    r':mailboxid\s+"([^"]+)"(?:\s+"([^"]*)")?'
    r'|mailboxidexists\s+(\[[^\]]*\]|"[^"]+")'
)
QUOTED = re.compile(r'"([^"]+)"')


def fetch_mailboxes(credentials, call=jmap):
    result = invoke(
        credentials,
        USING,
        "Mailbox/get",
        {"ids": None, "properties": ["id", "name", "parentId", "role"]},
        call,
    )
    return result["list"]


def with_paths(mailboxes):
    """Add a `path` ("finance.taxes") to each mailbox, sorted by path."""
    by_id = {box["id"]: box for box in mailboxes}

    def path(box):
        parent = by_id.get(box.get("parentId"))
        return f"{path(parent)}.{box['name']}" if parent else box["name"]

    return sorted(
        ({**box, "path": path(box)} for box in mailboxes),
        key=lambda b: b["path"].lower(),
    )


def references(text):
    """Return (id, fallback name or None) for every mailbox id the script uses."""
    found = []
    for match in REFERENCE.finditer(text):
        if match.group(1):
            found.append((match.group(1), match.group(2)))
        else:
            found.extend((ident, None) for ident in QUOTED.findall(match.group(3)))
    return found


def _plain(name):
    return strip_variation_selectors(name)


def _lookups(mailboxes, fragments):
    """Yield (file, id, fallback name, live mailbox or None) per reference."""
    by_id = {box["id"]: box for box in with_paths(mailboxes)}
    for name, text in fragments.items():
        for mailbox_id, fallback in references(text):
            yield name, mailbox_id, fallback, by_id.get(mailbox_id)


def _missing(name, mailbox_id, fallback):
    hint = f' (rule names it "{fallback}")' if fallback else ""
    return f"{name}: mailbox id {mailbox_id} does not exist{hint}"


def _misnamed(name, mailbox_id, fallback, box):
    expected = sieve_folder_name(box["path"])
    if fallback is None or _plain(canonical_inbox(fallback)) == _plain(expected):
        return None
    return (
        f'{name}: mailbox id {mailbox_id} ({box["path"]}) names it "{fallback}",'
        f' expected "{expected}"'
    )


def check_ids(mailboxes, fragments):
    """Return (how many ids exist, problems for the ones that do not)."""
    found, problems = 0, []
    for name, mailbox_id, fallback, box in _lookups(mailboxes, fragments):
        if box is None:
            problems.append(_missing(name, mailbox_id, fallback))
        else:
            found += 1
    return found, problems


def check_names(mailboxes, fragments):
    """Return (how many names match the live path, problems for the others).

    References to missing ids are left to `check_ids`."""
    matched, problems = 0, []
    for name, mailbox_id, fallback, box in _lookups(mailboxes, fragments):
        if box is None:
            continue
        problem = _misnamed(name, mailbox_id, fallback, box)
        if problem:
            problems.append(problem)
        else:
            matched += 1
    return matched, problems


def render(mailboxes, needle=None):
    lines = []
    for box in with_paths(mailboxes):
        if needle and needle.lower() not in box["path"].lower():
            continue
        role = f"  [{safe_text(box['role'])}]" if box.get("role") else ""
        lines.append(f"{safe_text(box['id']):<10} {safe_text(box['path'])}{role}")
    return lines
