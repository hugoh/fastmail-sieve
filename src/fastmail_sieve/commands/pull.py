from pathlib import Path

from fastmail_sieve.commands._options import confirm, progress_console
from fastmail_sieve.fastmail.blocks import NO_BLOCKS
from fastmail_sieve.project import FRAGMENT_HEADERS
from fastmail_sieve.remote import load_remote
from fastmail_sieve.sieve.script import fragment_files, split


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "pull",
        help="overwrite the rules/ fragments with Fastmail's managed blocks "
        "(asks first when that would replace local changes)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="replace local changes without asking"
    )
    parser.set_defaults(run=run)


def _local_changes(names, blocks):
    """Files whose content differs from Fastmail's and is more than an empty or
    untouched scaffold file."""
    changed = []
    for name, header, content in zip(
        names, FRAGMENT_HEADERS.values(), blocks, strict=True
    ):
        path = Path(name)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if existing in (content, header) or not existing.strip():
            continue
        changed.append(name)
    return changed


def run(args):
    console = progress_console()
    try:
        blocks = split(load_remote(console=console))
    except ValueError as error:
        raise RuntimeError(f"{NO_BLOCKS} ({error})") from error
    names = list(fragment_files())
    at_risk = _local_changes(names, blocks)
    if at_risk and not args.yes:
        print("Pulling would replace local changes in:")
        for name in at_risk:
            print(f"  {name}")
        if not confirm("Replace them with Fastmail's blocks?"):
            print("✗ Not pulled")
            return 1
    current = [
        Path(name).read_text(encoding="utf-8") if Path(name).is_file() else None
        for name in names
    ]
    if tuple(current) == tuple(blocks):
        console.print("✓ Already up to date", style="green", markup=False)
        return 0
    for name, content in zip(names, blocks, strict=True):
        Path(name).write_text(content, encoding="utf-8")
    console.print(
        f"✓ Pulled the managed blocks into {', '.join(names)}",
        style="green",
        markup=False,
    )
    return 0
