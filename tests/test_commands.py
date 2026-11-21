import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve.cli import main
from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.script import MARKER_END, MARKER_START, fragment_files
from fastmail_sieve.steps import Result, Step
from tests.test_sieve_blocks import skeleton

BLOCK = f"{MARKER_START}\n{MARKER_END}"
REMOTE = f"{FASTMAIL_REQUIRE}{BLOCK}\n### blocked\n{BLOCK}\n### rules\n{BLOCK}\n"
FILE_A_RULE = 'if address :is "from" "a@b.c" {\n  fileinto :mailboxid "P1" "INBOX.home";\n  stop;\n}\n'


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Project(unittest.TestCase):
    """A temporary project directory: fragments, variables.toml and a saved remote script."""

    middle = ""
    variables = ""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = os.getcwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, previous)
        Path("rules").mkdir()
        for name, text in zip(fragment_files(), ("", self.middle, ""), strict=True):
            Path(name).write_text(text)
        Path("variables.toml").write_text(self.variables)
        Path("remote.sieve").write_text(REMOTE)


class FormatCommandTest(Project):
    def test_rewrites_files_in_place(self):
        Path("x.sieve").write_text("if true {\nstop;\n}\n")
        code, _, err = run("format", "x.sieve")
        self.assertEqual(code, 0)
        self.assertEqual(Path("x.sieve").read_text(), "if true {\n  stop;\n}\n")
        self.assertIn("x.sieve: formatted", err)

    def test_check_fails_without_changing_the_file(self):
        Path("x.sieve").write_text("if true {\nstop;\n}\n")
        code, _, err = run("format", "--check", "x.sieve")
        self.assertEqual(code, 1)
        self.assertEqual(Path("x.sieve").read_text(), "if true {\nstop;\n}\n")
        self.assertIn("x.sieve: needs formatting", err)

    def test_formatted_files_pass_the_check(self):
        Path("x.sieve").write_text("if true {\n  stop;\n}\n")
        self.assertEqual(run("format", "--check", "x.sieve")[0], 0)

    def test_without_files_it_formats_the_fragments(self):
        Path(fragment_files()[1]).write_text("if true {\nstop;\n}\n")
        self.assertEqual(run("format")[0], 0)
        self.assertEqual(
            Path(fragment_files()[1]).read_text(), "if true {\n  stop;\n}\n"
        )


class AssembleCommandTest(Project):
    middle = FILE_A_RULE

    def test_prints_the_full_script(self):
        code, out, _ = run("assemble", "--from-file", "remote.sieve")
        self.assertEqual(code, 0)
        self.assertIn('address :is "from" "a@b.c"', out)
        self.assertTrue(out.startswith("require"))

    def test_output_writes_a_file_instead(self):
        code, out, _ = run(
            "assemble", "--from-file", "remote.sieve", "--output", "full.sieve"
        )
        self.assertEqual((code, out), (0, ""))
        self.assertIn('address :is "from" "a@b.c"', Path("full.sieve").read_text())


class DiffCommandTest(Project):
    middle = FILE_A_RULE

    def test_shows_what_a_push_would_change(self):
        code, out, _ = run("diff", "--from-file", "remote.sieve")
        self.assertEqual(code, 0)
        self.assertIn("--- fastmail", out)
        self.assertIn("+++ local", out)
        self.assertIn('+  fileinto :mailboxid "P1" "INBOX.home";', out)

    def test_no_changes_prints_nothing(self):
        run("assemble", "--from-file", "remote.sieve", "--output", "full.sieve")
        code, out, _ = run("diff", "--from-file", "full.sieve")
        self.assertEqual((code, out), (0, ""))


class PullCommandTest(Project):
    def test_overwrites_the_fragments_with_the_remote_blocks(self):
        Path("saved.sieve").write_text(skeleton("t;\n", "m;\n", "b;\n"))
        with mock.patch(
            "fastmail_sieve.commands.pull.load_remote",
            return_value=Path("saved.sieve").read_text(),
        ):
            code, _, _ = run("pull")
        self.assertEqual(code, 0)
        self.assertEqual(
            [Path(name).read_text() for name in fragment_files()],
            ["t;\n", "m;\n", "b;\n"],
        )


class LintCommandTest(Project):
    def steps_for(self, *argv):
        with mock.patch(
            "fastmail_sieve.commands.lint.run_steps", return_value=0
        ) as run_steps:
            run("lint", *argv)
        return [step.name for step in run_steps.call_args.args[0]]

    def test_offline_runs_only_the_checks_that_need_no_fastmail(self):
        self.assertEqual(
            self.steps_for("--offline"), ["Valid format and syntax in your rules"]
        )

    def test_online_runs_the_whole_checklist(self):
        names = self.steps_for()
        self.assertEqual(names[0], "Valid format and syntax in your rules")
        self.assertIn("Valid folder stable ids", names)


class ExplainWarningsVariablesTest(Project):
    middle = FILE_A_RULE

    def test_explain_shows_the_rules(self):
        code, out, _ = run(
            "explain",
            "--from-file",
            "remote.sieve",
            "--color",
            "never",
            "--width",
            "100",
        )
        self.assertEqual(code, 0)
        self.assertIn("a@b.c", out)

    def test_warnings_with_nothing_to_warn_about(self):
        code, out, _ = run("warnings", "--from-file", "remote.sieve", "--strict")
        self.assertEqual((code, out.strip()), (0, "No warnings."))


class VariablesCommandTest(Project):
    middle = 'set "stop" "Y";\nif string :is "${stop}" "Y" { stop; }\n'
    variables = '[stop]\ndescription = "Stop every later rule."\n'

    def test_describes_the_variables(self):
        code, out, _ = run(
            "variables", "--from-file", "remote.sieve", "--color", "never"
        )
        self.assertEqual(code, 0)
        self.assertIn("Stop every later rule.", out)

    def test_an_undocumented_variable_fails(self):
        Path("variables.toml").write_text("")
        code, _, err = run(
            "variables", "--from-file", "remote.sieve", "--color", "never"
        )
        self.assertEqual(code, 1)
        self.assertIn("error:", err)


class PushCommandTest(unittest.TestCase):
    def push(self, *argv, answer="y", remote="a\n", assembled="a\nb\n", checks=0):
        written = []
        session = mock.Mock(remote=remote, assembled=assembled)
        check = Step("Check", lambda: Result(errors=["broken"] if checks else []))
        write = Step("Write", lambda: written.append("yes") or Result())
        with (
            mock.patch("fastmail_sieve.commands.push.Session", return_value=session),
            mock.patch(
                "fastmail_sieve.commands.push.check_steps", return_value=[check]
            ),
            mock.patch(
                "fastmail_sieve.commands.push.write_steps", return_value=[write]
            ),
            mock.patch(
                "builtins.input", side_effect=[answer] if answer != "EOF" else EOFError
            ) as ask,
        ):
            code, out, err = run("push", *argv)
        return code, out + err, written, ask

    def test_shows_the_diff_asks_and_pushes_on_yes(self):
        code, output, written, ask = self.push()
        self.assertEqual((code, written), (0, ["yes"]))
        self.assertIn("+b", output)
        ask.assert_called_once()

    def test_declining_pushes_nothing(self):
        code, output, written, _ = self.push(answer="n")
        self.assertEqual((code, written), (1, []))
        self.assertIn("Not pushed", output)

    def test_no_answer_at_all_counts_as_no(self):
        code, _, written, _ = self.push(answer="EOF")
        self.assertEqual((code, written), (1, []))

    def test_yes_skips_the_question(self):
        code, _, written, ask = self.push("--yes")
        self.assertEqual((code, written), (0, ["yes"]))
        ask.assert_not_called()

    def test_nothing_to_push_when_nothing_changed(self):
        code, output, written, ask = self.push(remote="a\n", assembled="a\n")
        self.assertEqual((code, written), (0, []))
        self.assertIn("Nothing to push", output)
        ask.assert_not_called()

    def test_a_failed_check_stops_before_the_diff(self):
        code, output, written, ask = self.push(checks=1)
        self.assertEqual((code, written), (1, []))
        self.assertNotIn("+b", output)
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
