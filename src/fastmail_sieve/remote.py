from contextlib import nullcontext
from pathlib import Path

from fastmail_sieve.fastmail.blocks import get_script
from fastmail_sieve.fastmail.credentials import load_credentials
from fastmail_sieve.sieve.script import assemble


def fetch_script():
    return get_script(load_credentials()).text


def load_remote(from_file=None, console=None):
    """The full script as Fastmail has it, or a saved copy of it with `from_file`."""
    if from_file:
        return Path(from_file).read_text(encoding="utf-8")
    progress = (
        console.status("Fetching the script from Fastmail…")
        if console
        else nullcontext()
    )
    with progress:
        return fetch_script()


def load_assembled(project, from_file=None, console=None):
    """The remote script with your local fragments in its managed blocks."""
    return assemble(load_remote(from_file, console), *project.read_fragments())
