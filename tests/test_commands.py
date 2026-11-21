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


class LintFixTest(Project):
    middle = "if true {\nstop;\n}\n"

    def test_lint_reports_unformatted_rules_without_changing_them(self):
        code, out, _ = run("lint", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("lint --fix", out)
        self.assertEqual(Path(fragment_files()[1]).read_text(), self.middle)

    def test_fix_rewrites_the_fragments_and_then_checks_them(self):
        code, out, _ = run("lint", "--offline", "--fix")
        self.assertEqual(code, 0)
        self.assertEqual(
            Path(fragment_files()[1]).read_text(), "if true {\n  stop;\n}\n"
        )
        self.assertIn("Format your rules", out)
        self.assertIn(fragment_files()[1], out)

    def test_fix_on_formatted_rules_says_so_and_changes_nothing(self):
        run("lint", "--offline", "--fix")
        code, out, _ = run("lint", "--offline", "--fix")
        self.assertEqual(code, 0)
        self.assertIn("already formatted", out)


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


FORMAT_AND_SYNTAX = "Valid format and syntax in your rules"
FROM_FILE = ["Read the saved script", "Assemble the full script"]
SCRIPT_CHECKS = [
    "Valid syntax in the assembled script",
    "Valid markers in the assembled script",
    "Valid variables",
]
FOLDER_CHECKS = ["Valid folder stable ids", "Valid folder names"]


class LintCommandTest(Project):
    def steps_for(self, *argv):
        with mock.patch(
            "fastmail_sieve.commands.lint.run_steps", return_value=0
        ) as run_steps:
            run("lint", *argv)
        return [step.name for step in run_steps.call_args.args[0]]

    def test_offline_runs_only_the_checks_that_need_no_fastmail(self):
        self.assertEqual(self.steps_for("--offline"), [FORMAT_AND_SYNTAX])

    def test_fix_adds_a_formatting_step_first(self):
        self.assertEqual(
            self.steps_for("--offline", "--fix"),
            ["Format your rules", FORMAT_AND_SYNTAX],
        )

    def test_online_runs_every_check_and_ends_with_the_warnings(self):
        names = self.steps_for()
        self.assertEqual(names[0], FORMAT_AND_SYNTAX)
        self.assertEqual(names[1], "Fetch Fastmail's generated script")
        for check in (*SCRIPT_CHECKS, *FOLDER_CHECKS):
            self.assertIn(check, names)
        self.assertEqual(names[-1], "Warnings")

    def test_from_file_reads_the_saved_script_but_still_checks_folders(self):
        names = self.steps_for("--from-file", "remote.sieve")
        self.assertNotIn("Fetch Fastmail's generated script", names)
        self.assertEqual(names[1:3], FROM_FILE)
        for check in FOLDER_CHECKS:
            self.assertIn(check, names)

    def test_offline_from_file_checks_the_script_without_any_fastmail_access(self):
        self.assertEqual(
            self.steps_for("--offline", "--from-file", "remote.sieve"),
            [FORMAT_AND_SYNTAX, *FROM_FILE, *SCRIPT_CHECKS, "Warnings"],
        )


class LintOfflineFromFileTest(Project):
    middle = FILE_A_RULE

    def lint(self, *extra):
        return run("lint", "--offline", "--from-file", "remote.sieve", *extra)

    def test_every_check_passes_on_a_clean_project(self):
        code, out, _ = self.lint()
        self.assertEqual(code, 0)
        for name in (FORMAT_AND_SYNTAX, *SCRIPT_CHECKS, "Warnings"):
            self.assertIn(f"✓ {name}", out)
        self.assertNotIn("folder", out)

    def test_warnings_are_shown_but_do_not_fail_by_default(self):
        with mock.patch(
            "fastmail_sieve.steps.collect_warnings", return_value=[("overlap", "x")]
        ):
            code, out, _ = self.lint()
        self.assertEqual(code, 0)
        self.assertIn("! Warnings", out)
        self.assertIn("overlap: x", out)

    def test_strict_turns_warnings_into_a_failure(self):
        with mock.patch(
            "fastmail_sieve.steps.collect_warnings", return_value=[("overlap", "x")]
        ):
            code, out, _ = self.lint("--strict")
        self.assertEqual(code, 1)
        self.assertIn("✗ Warnings", out)
        self.assertIn("overlap: x", out)

    def test_strict_is_fine_when_there_is_nothing_to_warn_about(self):
        self.assertEqual(self.lint("--strict")[0], 0)


class LintVariablesTest(Project):
    middle = 'set "stop" "Y";\nif string :is "${stop}" "Y" { stop; }\n'
    variables = '[stop]\ndescription = "Stop every later rule."\n'

    def test_documented_variables_pass(self):
        code, out, _ = run("lint", "--offline", "--from-file", "remote.sieve")
        self.assertEqual(code, 0)
        self.assertIn("✓ Valid variables", out)

    def test_an_undocumented_variable_fails_the_lint(self):
        Path("variables.toml").write_text("")
        code, out, _ = run("lint", "--offline", "--from-file", "remote.sieve")
        self.assertEqual(code, 1)
        self.assertIn("✗ Valid variables", out)
        self.assertIn("no description", out)

    def test_a_missing_variables_file_says_how_to_create_it(self):
        Path("variables.toml").unlink()
        code, out, _ = run("lint", "--offline", "--from-file", "remote.sieve")
        self.assertEqual(code, 1)
        self.assertIn("fastmail-sieve init", out)


class ExplainCommandTest(Project):
    middle = FILE_A_RULE

    def explain(self, *args):
        return run("explain", *args, "--from-file", "remote.sieve", "--color", "never")

    def test_rules_are_the_default_topic(self):
        code, out, _ = self.explain("--width", "100")
        self.assertEqual(code, 0)
        self.assertIn("a@b.c", out)

    def test_the_script_topic_shows_the_whole_script(self):
        code, out, _ = self.explain("script", "--width", "100")
        self.assertEqual(code, 0)
        self.assertIn("a@b.c", out)

    def test_a_broken_variables_file_names_the_file(self):
        Path("variables.toml").write_text("this is = = not toml\n")
        code, _, err = self.explain()
        self.assertEqual(code, 1)
        self.assertIn("variables.toml", err)
        self.assertNotIn("Traceback", err)

    def test_a_missing_variables_file_says_how_to_create_it(self):
        Path("variables.toml").unlink()
        code, _, err = self.explain()
        self.assertEqual(code, 1)
        self.assertIn("fastmail-sieve init", err)

    def test_a_mistyped_from_file_is_a_clear_failure(self):
        code, _, err = run("diff", "--from-file", "nope.sieve")
        self.assertEqual(code, 1)
        self.assertIn("nope.sieve", err)

    def test_an_unknown_topic_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            self.explain("nope")
        self.assertEqual(raised.exception.code, 2)


class ExplainVariablesTest(Project):
    middle = 'set "stop" "Y";\nif string :is "${stop}" "Y" { stop; }\n'
    variables = '[stop]\ndescription = "Stop every later rule."\n'

    def test_describes_the_variables(self):
        code, out, _ = run(
            "explain", "variables", "--from-file", "remote.sieve", "--color", "never"
        )
        self.assertEqual(code, 0)
        self.assertIn("Stop every later rule.", out)

    def test_problems_are_shown_but_explain_is_a_report_and_does_not_fail(self):
        Path("variables.toml").write_text("")
        code, _, err = run(
            "explain", "variables", "--from-file", "remote.sieve", "--color", "never"
        )
        self.assertEqual(code, 0)
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
                "fastmail_sieve.commands.push.lint_steps", return_value=[check]
            ) as lint,
            mock.patch(
                "fastmail_sieve.commands.push.write_steps", return_value=[write]
            ),
            mock.patch(
                "builtins.input", side_effect=[answer] if answer != "EOF" else EOFError
            ) as ask,
        ):
            code, out, err = run("push", *argv)
        self.lint_steps = lint
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

    def test_strict_makes_warnings_block_the_push(self):
        self.push("--strict")
        self.assertTrue(self.lint_steps.call_args.kwargs["strict"])

    def test_without_strict_warnings_do_not_block(self):
        self.push()
        self.assertFalse(self.lint_steps.call_args.kwargs["strict"])

    def test_a_failed_check_stops_before_the_diff(self):
        code, output, written, ask = self.push(checks=1)
        self.assertEqual((code, written), (1, []))
        self.assertNotIn("+b", output)
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
