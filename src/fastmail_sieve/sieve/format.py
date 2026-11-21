import re
from pathlib import Path

INDENT = "  "
OPENERS = "{(["
CLOSERS = "})]"
TEXT_BLOCK_START = re.compile(r"\btext:\s*$")
MAILBOX_NAME = re.compile(r'(:mailboxid\s+"[^"]*"\s+")([^"]*)(")')
FOLDER_SEPARATOR = "."
INBOX = "INBOX"
INBOX_PREFIX = INBOX + FOLDER_SEPARATOR
INBOX_FOLDER = "Inbox"
INBOX_UNDER_INBOX = re.compile(rf"^{INBOX_PREFIX}inbox(?=\.|$)", re.IGNORECASE)


def sieve_folder_name(name):
    """Fastmail's Sieve spelling: `INBOX.` in front of the folder's path, so a
    folder inside Inbox is `INBOX.Inbox.<name>`."""
    name = name.replace("/", FOLDER_SEPARATOR)
    if name.lower() == "inbox":
        return INBOX
    if not name.startswith(INBOX_PREFIX):
        name = INBOX_PREFIX + name
    return INBOX_UNDER_INBOX.sub(INBOX_PREFIX + INBOX_FOLDER, name)


def _normalize_folder_names(line):
    return MAILBOX_NAME.sub(lambda m: m[1] + sieve_folder_name(m[2]) + m[3], line)


def _code(line):
    """The line with string contents blanked and any # comment removed."""
    out = []
    in_string = False
    escaped = False
    for char in line:
        if in_string:
            if escaped:
                escaped = False
                out.append(" ")
            elif char == "\\":
                escaped = True
                out.append(" ")
            elif char == '"':
                in_string = False
                out.append(char)
            else:
                out.append(" ")
        elif char == '"':
            in_string = True
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
    return "".join(out)


def _leading_closers(code):
    count = 0
    for char in code.lstrip():
        if char in CLOSERS:
            count += 1
        elif char != " ":
            break
    return count


def format_sieve(text):
    lines = []
    depth = 0
    in_text_block = False
    in_block_comment = False
    for line in text.split("\n"):
        if in_text_block:
            lines.append(line)
            in_text_block = line.strip() != "."
            continue
        if in_block_comment:
            lines.append(line)
            in_block_comment = "*/" not in line
            continue
        stripped = _normalize_folder_names(line.strip())
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            lines.append(f"{INDENT * depth}{stripped}")
            in_block_comment = True
            continue
        code = _code(stripped)
        level = max(0, depth - _leading_closers(code))
        lines.append(f"{INDENT * level}{stripped}")
        depth = max(
            0, depth + sum(c in OPENERS for c in code) - sum(c in CLOSERS for c in code)
        )
        in_text_block = bool(TEXT_BLOCK_START.search(code))
    return "\n".join(lines)


def format_errors(files):
    return [
        f"{name} is not formatted: run `fastmail-sieve format`"
        for name, text in files.items()
        if format_sieve(text) != text
    ]


def format_files(paths, check=False):
    """Format files in place (or only look, with `check`); return the ones that differ."""
    unformatted = []
    for name in paths:
        path = Path(name)
        original = path.read_text(encoding="utf-8")
        formatted = format_sieve(original)
        if formatted == original:
            continue
        unformatted.append(name)
        if not check:
            path.write_text(formatted, encoding="utf-8")
    return unformatted
