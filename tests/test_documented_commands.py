import re
import unittest
from pathlib import Path

from fastmail_sieve.cli import cli

ROOT = Path(__file__).resolve().parent.parent
MENTION = re.compile(r"(?:`|\brun |^)fastmail-sieve ([a-z][a-z-]*)", re.MULTILINE)


def real_commands():
    return set(cli.commands)


def mentions(path):
    return {
        (word, path.name) for word in MENTION.findall(path.read_text(encoding="utf-8"))
    }


class DocumentedCommandsTest(unittest.TestCase):
    """What the README and the program's own messages tell people to run must exist."""

    def test_every_command_the_docs_and_messages_mention_is_real(self):
        files = [ROOT / "README.md", *sorted((ROOT / "src").rglob("*.py"))]
        found = set().union(*(mentions(path) for path in files))
        unknown = sorted((w, f) for w, f in found if w not in real_commands())
        self.assertEqual(unknown, [])

    def test_the_guard_does_see_the_mentions(self):
        text = "run `fastmail-sieve lint --fix` or fastmail-sieve is great\nfastmail-sieve init\n"
        path = ROOT / "tests" / "_scratch_mentions.txt"
        path.write_text(text, encoding="utf-8")
        try:
            self.assertEqual({w for w, _ in mentions(path)}, {"lint", "init"})
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
