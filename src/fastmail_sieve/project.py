from fastmail_sieve.config import FRAGMENT_NAMES

FRAGMENT_HEADERS = {
    "top": "# Rules that run first, before Fastmail's blocked-sender and spam handling.\n",
    "middle": "# Folder filing and other rules that run before your Fastmail UI rules.\n",
    "bottom": "# Rules that run last, after your Fastmail UI rules.\n",
}
VARIABLES_TEMPLATE = """\
# Plain-English meaning of the variables in the assembled Fastmail script.
# `fastmail-sieve lint` fails when a variable is undefined, unused or
# undocumented: add an entry here when it reports a new one, for example:
#
# [stop]
# description = "Once Y, no later rule runs on this message."
# when_yes = "an earlier rule already handled the message"
# when_no = "no earlier rule has handled the message"
# set_yes = "stop applying further rules"
"""
IGNORED = "rules.sieve"


def _gitignore(root):
    path = root / ".gitignore"
    if not path.exists():
        path.write_text(f"{IGNORED}\n", encoding="utf-8")
        return True
    text = path.read_text(encoding="utf-8")
    if IGNORED in text.splitlines():
        return False
    path.write_text(
        text + ("" if text.endswith("\n") or not text else "\n") + f"{IGNORED}\n",
        encoding="utf-8",
    )
    return True


def scaffold(project):
    """Create the files of a rules project that do not exist yet; never overwrite one."""
    root = project.root
    files = {
        path: FRAGMENT_HEADERS[name]
        for name, path in zip(FRAGMENT_NAMES, project.fragment_files, strict=True)
    }
    files[project.variables_file] = VARIABLES_TEMPLATE
    created, kept = [], []
    for relative, content in files.items():
        target = project.path(relative)
        if target.exists():
            kept.append(relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(relative)
    (created if _gitignore(root) else kept).append(".gitignore")
    return created, kept
