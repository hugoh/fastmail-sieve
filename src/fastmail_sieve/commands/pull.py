from pathlib import Path

from fastmail_sieve.commands._options import progress_console
from fastmail_sieve.fastmail.blocks import NO_BLOCKS
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.script import fragment_files, split


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "pull",
        help="overwrite the rules/ fragments with Fastmail's managed blocks "
        "(commit local work first)",
    )
    parser.set_defaults(run=run)


def run(args):
    console = progress_console()
    try:
        blocks = split(load_remote(console=console))
    except ValueError as error:
        raise RuntimeError(f"{NO_BLOCKS} ({error})") from error
    for name, content in zip(fragment_files(), blocks, strict=True):
        Path(name).write_text(content, encoding="utf-8")
    console.print(
        f"✓ Pulled the managed blocks into {', '.join(fragment_files())}",
        style="green",
        markup=False,
    )
    return 0
