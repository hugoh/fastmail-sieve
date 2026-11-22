import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve.cli import main
from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.script import (
    MARKER_END,
    MARKER_START,
    assemble,
    fragment_files,
)
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


class TerminalSafetyTest(Project):
    def hostile_remote(self, outside_the_blocks=False):
        if outside_the_blocks:  # what `assemble` prints is Fastmail's own text
            Path("remote.sieve").write_text(REMOTE + "# \x1b[2Jowned\n")
            return
        hostile = f"{MARKER_START}\n# \x1b[2Jowned\n{MARKER_END}"
        Path("remote.sieve").write_text(REMOTE.replace(BLOCK, hostile, 1))

    def test_diff_never_prints_control_characters(self):
        self.hostile_remote()
        code, out, _ = run("diff", "--from-file", "remote.sieve")
        self.assertNotIn("\x1b", out)
        self.assertIn("owned", out)

    def test_assemble_to_a_terminal_strips_them(self):
        self.hostile_remote(outside_the_blocks=True)
        out = io.StringIO()
        out.isatty = lambda: True
        with contextlib.redirect_stdout(out):
            main(["assemble", "--from-file", "remote.sieve"])
        self.assertNotIn("\x1b", out.getvalue())

    def test_assemble_into_a_pipe_is_byte_for_byte(self):
        self.hostile_remote(outside_the_blocks=True)
        code, out, _ = run("assemble", "--from-file", "remote.sieve")
        self.assertIn("\x1b[2J", out)


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


REMOTE_BLOCKS = skeleton("t;\n", "m;\n", "b;\n")


class PullCommandTest(Project):
    def pull(self, *argv, answer="y"):
        with (
            mock.patch(
                "fastmail_sieve.commands.pull.load_remote", return_value=REMOTE_BLOCKS
            ),
            mock.patch(
                "builtins.input",
                side_effect=[answer] if answer != "EOF" else EOFError(),
            ) as ask,
        ):
            code, out, err = run("pull", *argv)
        return code, out + err, ask

    def files(self):
        return [Path(name).read_text() for name in fragment_files()]

    def test_empty_fragments_are_filled_without_asking(self):
        code, _, ask = self.pull()
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), ["t;\n", "m;\n", "b;\n"])
        ask.assert_not_called()

    def test_the_untouched_scaffold_is_replaced_without_asking(self):
        from fastmail_sieve.project import scaffold

        for name in fragment_files():
            Path(name).unlink()
        scaffold(Path("."))
        code, _, ask = self.pull()
        self.assertEqual((code, self.files()), (0, ["t;\n", "m;\n", "b;\n"]))
        ask.assert_not_called()

    def test_missing_files_are_created_without_asking(self):
        Path(fragment_files()[2]).unlink()
        code, _, ask = self.pull()
        self.assertEqual((code, self.files()[2]), (0, "b;\n"))
        ask.assert_not_called()

    def test_nothing_to_do_when_they_already_match(self):
        for name, text in zip(fragment_files(), ("t;\n", "m;\n", "b;\n"), strict=True):
            Path(name).write_text(text)
        code, out, ask = self.pull()
        self.assertEqual(code, 0)
        self.assertIn("Already up to date", out)
        ask.assert_not_called()

    def test_local_changes_are_listed_and_need_a_yes(self):
        Path(fragment_files()[1]).write_text("# my uncommitted edit\n")
        code, out, ask = self.pull(answer="y")
        self.assertEqual(code, 0)
        ask.assert_called_once()
        self.assertIn(fragment_files()[1], out)
        self.assertEqual(self.files()[1], "m;\n")

    def test_declining_leaves_every_file_untouched(self):
        Path(fragment_files()[1]).write_text("# my uncommitted edit\n")
        code, out, _ = self.pull(answer="n")
        self.assertEqual(code, 1)
        self.assertIn("Not pulled", out)
        self.assertEqual(self.files(), ["", "# my uncommitted edit\n", ""])

    def test_no_answer_at_all_counts_as_no(self):
        Path(fragment_files()[0]).write_text("# mine\n")
        code, _, _ = self.pull(answer="EOF")
        self.assertEqual((code, self.files()[0]), (1, "# mine\n"))

    def test_yes_replaces_without_asking(self):
        Path(fragment_files()[1]).write_text("# my uncommitted edit\n")
        code, _, ask = self.pull("--yes")
        self.assertEqual((code, self.files()[1]), (0, "m;\n"))
        ask.assert_not_called()


LIVE_RULE = 'if address :is "from" "live@x.y" {\n  fileinto "INBOX.live";\n  stop;\n}\n'


class LiveTargetTest(Project):
    """--live checks Fastmail's script exactly as it is; your rules play no part."""

    middle = "if true {\n  stop;\n"

    def save_live(self, middle=LIVE_RULE, name="live.sieve"):
        Path(name).write_text(assemble(REMOTE, "", middle, ""))

    def test_your_rules_are_not_checked_and_do_not_matter(self):
        self.save_live()
        code, out, _ = run("lint", "--live", "--offline", "--from-file", "live.sieve")
        self.assertEqual(code, 0, out)
        self.assertNotIn("your rules", out)

    def test_the_default_still_checks_your_rules(self):
        self.save_live()
        code, out, _ = run("lint", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("✗ Valid format and syntax in your rules", out)

    def test_a_problem_in_the_live_script_is_reported(self):
        self.save_live("if {\n")
        code, out, _ = run("lint", "--live", "--offline", "--from-file", "live.sieve")
        self.assertEqual(code, 1)
        self.assertIn("✗ Valid syntax in the live script", out)

    def test_live_folder_checks_name_the_live_script(self):
        self.save_live('fileinto :mailboxid "GONE" "x";\n')
        boxes = [{"id": "P1", "name": "home", "parentId": None, "role": None}]
        with (
            mock.patch(
                "fastmail_sieve.steps.pick", return_value={"token": "t", "cookie": "c"}
            ),
            mock.patch("fastmail_sieve.steps.fetch_mailboxes", return_value=boxes),
            mock.patch("fastmail_sieve.steps.validate_sieve", return_value=None),
        ):
            code, out, _ = run("lint", "--live", "--from-file", "live.sieve")
        self.assertEqual(code, 1)
        self.assertIn("✗ Valid folder stable ids", out)
        self.assertIn("GONE does not exist", out)
        self.assertIn("Fastmail's script", out)
        self.assertNotIn("rules/", out)

    def test_live_without_a_file_needs_fastmail_so_offline_is_refused(self):
        code, _, err = run("lint", "--live", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("--live needs Fastmail", err)

    def test_live_cannot_fix_because_it_never_touches_your_files(self):
        self.save_live()
        code, _, err = run("lint", "--live", "--fix", "--from-file", "live.sieve")
        self.assertEqual(code, 1)
        self.assertIn("--fix", err)
        self.assertEqual(Path(fragment_files()[1]).read_text(), self.middle)

    def test_explain_live_shows_what_is_live_not_your_rules(self):
        Path(fragment_files()[1]).write_text(FILE_A_RULE)
        self.save_live()
        code, out, _ = run(
            "explain", "--live", "--from-file", "live.sieve", "--color", "never"
        )
        self.assertEqual(code, 0)
        self.assertIn("live@x.y", out)
        self.assertNotIn("a@b.c", out)

    def test_explain_without_live_shows_your_rules(self):
        Path(fragment_files()[1]).write_text(FILE_A_RULE)
        self.save_live()
        _, out, _ = run("explain", "--from-file", "live.sieve", "--color", "never")
        self.assertIn("a@b.c", out)
        self.assertNotIn("live@x.y", out)

    def test_explain_live_of_a_script_without_blocks_still_explains_its_rules(self):
        Path("bare.sieve").write_text('require ["fileinto"];\nfileinto "INBOX.x";\n')
        code, _, err = run(
            "explain", "--live", "--from-file", "bare.sieve", "--color", "never"
        )
        self.assertEqual(code, 0, err)


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
                "builtins.input",
                side_effect=[answer] if answer != "EOF" else EOFError(),
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
