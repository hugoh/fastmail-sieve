import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve import config
from fastmail_sieve.cli import main
from fastmail_sieve.fastmail.blocks import RemoteScript
from fastmail_sieve.project import scaffold
from tests.test_blocks import EMPTY


class InTempDir(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = os.getcwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, previous)
        self.addCleanup(config.use, config.Config())


class ScaffoldTest(InTempDir):
    def test_creates_the_fragments_variables_and_gitignore(self):
        created, kept = scaffold(Path("."))
        self.assertEqual(kept, [])
        for name in (
            "rules/top.sieve",
            "rules/middle.sieve",
            "rules/bottom.sieve",
            "variables.toml",
            ".gitignore",
        ):
            self.assertIn(name, created)
            self.assertTrue(Path(name).is_file(), name)
        self.assertIn("rules.sieve", Path(".gitignore").read_text().splitlines())

    def test_fragments_are_valid_sieve_comments(self):
        scaffold(Path("."))
        for name in ("top", "middle", "bottom"):
            text = Path(f"rules/{name}.sieve").read_text()
            self.assertTrue(text.startswith("#"), name)
        self.assertEqual(main(["lint", "--offline"]), 0)

    def test_never_overwrites_existing_files(self):
        Path("rules").mkdir()
        Path("rules/middle.sieve").write_text("keep;\n")
        created, kept = scaffold(Path("."))
        self.assertEqual(Path("rules/middle.sieve").read_text(), "keep;\n")
        self.assertIn("rules/middle.sieve", kept)
        self.assertNotIn("rules/middle.sieve", created)

    def test_a_second_run_changes_nothing(self):
        scaffold(Path("."))
        created, kept = scaffold(Path("."))
        self.assertEqual(created, [])
        self.assertEqual(len(kept), 5)

    def test_an_existing_gitignore_gets_the_line_appended_once(self):
        Path(".gitignore").write_text("*.pyc\n")
        scaffold(Path("."))
        scaffold(Path("."))
        self.assertEqual(
            Path(".gitignore").read_text().splitlines(), ["*.pyc", "rules.sieve"]
        )

    def test_follows_the_config(self):
        Path("fastmail-sieve.toml").write_text(
            'rules-dir = "sieve"\nvariables-file = "vars.toml"\n'
        )
        created, _ = scaffold(Path("."), config.load_config(Path(".").resolve()))
        self.assertIn("sieve/top.sieve", created)
        self.assertIn("vars.toml", created)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue() + err.getvalue()


BARE = RemoteScript("R", "# my code", "B", "", "U", "")
MARKED = RemoteScript("R", EMPTY, "B", EMPTY, "U", EMPTY)


class InitCommandTest(InTempDir):
    def init(self, *argv, script=BARE, answer="y"):
        patches = [
            mock.patch(
                "fastmail_sieve.commands.init.gather",
                return_value=[
                    (
                        "t",
                        {
                            "session": {"token": "t", "cookie": "c", "username": None},
                            "api": None,
                        },
                    )
                ],
            ),
            mock.patch(
                "fastmail_sieve.commands.init.get_script", side_effect=[script, MARKED]
            ),
            mock.patch("fastmail_sieve.commands.init.set_blocks"),
            mock.patch("builtins.input", side_effect=[answer]),
        ]
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            code, output = run("init", *argv)
        return code, output, mocks[2], mocks[3]

    def test_local_init_makes_no_request_to_fastmail(self):
        with mock.patch("fastmail_sieve.commands.init.get_script") as get_script:
            code, output = run("init")
        self.assertEqual(code, 0)
        get_script.assert_not_called()
        self.assertIn("rules/top.sieve", output)
        self.assertIn("--remote", output)

    def test_init_works_in_an_empty_directory_without_a_project(self):
        self.assertEqual(run("init")[0], 0)
        self.assertTrue(Path("rules/top.sieve").is_file())

    def test_remote_adds_the_blocks_after_asking(self):
        code, output, set_blocks, ask = self.init("--remote")
        self.assertEqual(code, 0)
        ask.assert_called_once()
        [_, sent], _ = set_blocks.call_args
        self.assertTrue(sent.has_markers)
        self.assertIn("# my code", sent.start)
        self.assertIn("one-time", output)

    def test_declining_writes_nothing(self):
        code, output, set_blocks, _ = self.init("--remote", answer="n")
        self.assertEqual(code, 1)
        set_blocks.assert_not_called()

    def test_yes_skips_the_question(self):
        code, _, set_blocks, ask = self.init("--remote", "--yes")
        self.assertEqual(code, 0)
        ask.assert_not_called()
        set_blocks.assert_called_once()

    def test_already_present_blocks_are_not_rewritten(self):
        code, output, set_blocks, ask = self.init("--remote", script=MARKED)
        self.assertEqual(code, 0)
        set_blocks.assert_not_called()
        ask.assert_not_called()
        self.assertIn("already", output)


if __name__ == "__main__":
    unittest.main()
