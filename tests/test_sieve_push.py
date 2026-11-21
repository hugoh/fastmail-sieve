import io
import unittest
from unittest import mock

from rich.console import Console

from fastmail_sieve.fastmail.blocks import RemoteScript
from fastmail_sieve.steps import (
    FolderChecks,
    Result,
    Session,
    Step,
    _lint_fragments,
    build_steps,
    lint_steps,
    run_steps,
)
from tests.test_blocks import block


def console():
    return Console(file=io.StringIO(), force_terminal=False, width=80, emoji=False)


def output(c):
    return c.file.getvalue()


class RunStepsTest(unittest.TestCase):
    def test_all_passing_steps_print_a_checklist(self):
        c = console()
        code = run_steps(
            [Step("One", lambda: Result()), Step("Two", lambda: Result())], c
        )
        self.assertEqual(code, 0)
        self.assertEqual(output(c).splitlines(), ["✓ One", "✓ Two"])

    def test_a_failing_step_stops_the_run_and_shows_the_errors(self):
        c = console()
        ran = []

        def third():
            ran.append("three")
            return Result()

        steps = [
            Step("One", lambda: Result()),
            Step("Two", lambda: Result(errors=["bad thing", "worse thing"])),
            Step("Three", third),
        ]
        code = run_steps(steps, c)
        self.assertEqual(code, 1)
        self.assertEqual(ran, [])
        lines = output(c).splitlines()
        self.assertEqual(lines[0], "✓ One")
        self.assertEqual(lines[1], "✗ Two")
        self.assertIn("    bad thing", lines)
        self.assertIn("    worse thing", lines)
        self.assertNotIn("Three", output(c))

    def test_an_exception_is_reported_as_a_failure(self):
        c = console()

        def boom():
            raise RuntimeError("no credentials")

        self.assertEqual(run_steps([Step("Fetch", boom)], c), 1)
        self.assertIn("✗ Fetch", output(c))
        self.assertIn("    no credentials", output(c))

    def test_details_are_shown_after_a_passing_step(self):
        c = console()
        step = Step("Push", lambda: Result(detail="no change so far; skip pushing"))
        run_steps([step], c)
        self.assertEqual(
            output(c).splitlines(), ["✓ Push", "    no change so far; skip pushing"]
        )

    def test_slow_steps_still_report_normally(self):
        c = console()
        self.assertEqual(run_steps([Step("Fetch", lambda: Result(), slow=True)], c), 0)
        self.assertIn("✓ Fetch", output(c))


class LintFragmentsTest(unittest.TestCase):
    def lint(self, top="", middle="", bottom=""):
        with mock.patch(
            "fastmail_sieve.steps.read_fragments", return_value=(top, middle, bottom)
        ):
            return _lint_fragments()

    def test_unformatted_fragments_fail_with_the_fix(self):
        result = self.lint(top="if true {\nstop;\n}\n")
        self.assertEqual(
            result.errors,
            ["rules/top.sieve is not formatted: run `fastmail-sieve format`"],
        )

    def test_formatted_valid_fragments_pass(self):
        self.assertEqual(self.lint(top="if true {\n  stop;\n}\n").errors, [])

    def test_syntax_errors_still_fail(self):
        self.assertTrue(self.lint(top="if true {\n  stop;\n").errors)


class FolderChecksTest(unittest.TestCase):
    BOXES = [{"id": "P1", "name": "home", "parentId": None, "role": None}]

    def checks(self, middle):
        self.fetch = mock.Mock(return_value=self.BOXES)
        patches = (
            mock.patch(
                "fastmail_sieve.steps.read_fragments", return_value=("", middle, "")
            ),
            mock.patch("fastmail_sieve.steps.gather", return_value=SOURCES),
            mock.patch("fastmail_sieve.steps.fetch_mailboxes", self.fetch),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return FolderChecks()

    def test_existing_ids_pass(self):
        result = self.checks('fileinto :mailboxid "P1" "INBOX.home";').check_ids()
        self.assertEqual((result.errors, result.detail), ([], "1 stable id exists"))

    def test_a_missing_id_fails(self):
        result = self.checks('fileinto :mailboxid "GONE" "x";').check_ids()
        self.assertIn("GONE does not exist", result.errors[0])

    def test_a_wrong_name_passes_the_ids_but_fails_the_names(self):
        checks = self.checks('fileinto :mailboxid "P1" "home";')
        self.assertEqual(checks.check_ids().errors, [])
        self.assertIn('expected "INBOX.home"', checks.check_names().errors[0])

    def test_correct_names_pass(self):
        result = self.checks('fileinto :mailboxid "P1" "INBOX.home";').check_names()
        self.assertEqual((result.errors, result.detail), ([], "1 folder name matches"))

    def test_both_steps_share_one_fetch(self):
        checks = self.checks('fileinto :mailboxid "P1" "INBOX.home";')
        checks.check_ids()
        checks.check_names()
        self.assertEqual(self.fetch.call_count, 1)


LINT_NAMES = [
    "Valid format and syntax in your rules",
    "Fetch Fastmail's generated script",
    "Assemble the full script",
    "Valid syntax in the assembled script",
    "Valid markers in the assembled script",
    "Valid folder stable ids",
    "Valid folder names",
]


class StepListTest(unittest.TestCase):
    def test_lint_is_a_checklist_of_valid_things(self):
        self.assertEqual([step.name for step in lint_steps()], LINT_NAMES)

    def test_push_runs_every_lint_step_first_then_pushes(self):
        names = [step.name for step in build_steps()]
        self.assertEqual(names[: len(LINT_NAMES)], LINT_NAMES)
        self.assertEqual(
            names[len(LINT_NAMES) :],
            ["Valid variables", "Push the managed blocks", "Verify with a fresh pull"],
        )


SOURCES = [
    ("test", {"session": {"token": "t", "cookie": "c", "username": None}, "api": None})
]


def remote_script(start="old;\n", middle="", end=""):
    return RemoteScript(
        require='require ["fileinto"];',
        start=block(start),
        blocked="### blocked",
        middle=block(middle),
        rules="### rules",
        end=block(end),
    )


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.script = remote_script()
        self.fresh = [self.script]
        self.get_script = mock.Mock(
            side_effect=lambda credentials: (
                self.fresh.pop(0) if self.fresh else self.script
            )
        )
        self.set_blocks = mock.Mock()
        for name, value in (
            ("get_script", self.get_script),
            ("set_blocks", self.set_blocks),
            ("gather", mock.Mock(return_value=SOURCES)),
            ("read_fragments", mock.Mock(return_value=("new;\n", "", ""))),
        ):
            patcher = mock.patch(f"fastmail_sieve.steps.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetched(self):
        session = Session()
        session.fetch()
        return session

    def test_fetch_keeps_the_remote_script_and_its_text(self):
        session = self.fetched()
        self.assertEqual(session.remote, self.script.text)

    def test_assemble_puts_the_local_fragments_in_without_touching_disk(self):
        session = self.fetched()
        session.assemble()
        self.assertIn("new;\n", session.assembled)
        self.assertNotIn("old;", session.assembled)

    def test_the_assembled_checks_look_at_the_assembled_script(self):
        session = self.fetched()
        session.assemble()
        with (
            mock.patch(
                "fastmail_sieve.steps.check_syntax", return_value="bad"
            ) as syntax,
            mock.patch(
                "fastmail_sieve.steps.check_markers", return_value=None
            ) as markers,
        ):
            self.assertEqual(session.check_syntax().errors, ["bad"])
            self.assertEqual(session.check_markers().errors, [])
        syntax.assert_called_once_with(session.assembled)
        markers.assert_called_once_with(session.assembled)

    def test_push_writes_the_changed_blocks(self):
        session = self.fetched()
        result = session.push()
        self.assertEqual(result.errors, [])
        [_, sent], _ = self.set_blocks.call_args
        self.assertEqual(sent.fragments, ("new;\n", "", ""))
        self.assertEqual(
            (sent.require, sent.blocked, sent.rules),
            (self.script.require, "### blocked", "### rules"),
        )

    def test_push_with_nothing_to_change_writes_nothing(self):
        self.script = remote_script(start="new;\n")
        self.fresh = [self.script]
        result = self.fetched().push()
        self.set_blocks.assert_not_called()
        self.assertIn("nothing to push", result.detail)

    def test_verify_passes_when_fastmail_now_has_the_local_fragments(self):
        session = self.fetched()
        self.fresh = [remote_script(start="new;\n")]
        self.assertEqual(session.verify().errors, [])

    def test_verify_fails_when_the_blocks_still_differ(self):
        session = self.fetched()
        self.fresh = [remote_script(start="old;\n")]
        self.assertEqual(
            session.verify().errors,
            ["Fastmail's managed blocks differ from the local fragments"],
        )


if __name__ == "__main__":
    unittest.main()
