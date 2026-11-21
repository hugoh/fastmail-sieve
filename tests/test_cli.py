import contextlib
import io
import unittest
from unittest import mock

from fastmail_sieve.cli import build_parser, main

COMMANDS = {
    "assemble",
    "auth",
    "diff",
    "doctor",
    "explain",
    "folders",
    "init",
    "lint",
    "migrate",
    "pull",
    "push",
}


def parse(*argv):
    return build_parser().parse_args(argv)


class ParserTest(unittest.TestCase):
    def test_every_command_is_registered(self):
        subparsers = next(
            action for action in build_parser()._actions if action.dest == "command"
        )
        self.assertEqual(set(subparsers.choices), COMMANDS)

    def test_lint_options(self):
        plain = parse("lint")
        self.assertEqual(
            (plain.offline, plain.fix, plain.strict), (False, False, False)
        )
        args = parse("lint", "--offline", "--fix", "--strict", "--from-file", "f")
        self.assertEqual(
            (args.offline, args.fix, args.strict, args.from_file),
            (True, True, True, "f"),
        )

    def test_push_asks_unless_told_not_to(self):
        self.assertFalse(parse("push").yes)
        self.assertTrue(parse("push", "--yes").yes)

    def test_explain_takes_a_topic_and_display_options(self):
        args = parse("explain", "script", "--width", "90", "--color", "never")
        self.assertEqual((args.topic, args.width, args.color), ("script", 90, "never"))
        self.assertEqual(parse("explain").topic, "rules")
        self.assertEqual(parse("explain", "variables").topic, "variables")

    def test_commands_that_read_the_script_accept_from_file(self):
        for command in (
            "assemble",
            "diff",
            "explain",
            "lint",
            "migrate",
        ):
            self.assertEqual(
                parse(command, "--from-file", "x.sieve").from_file, "x.sieve", command
            )
            self.assertIsNone(parse(command).from_file, command)

    def test_push_strict_and_folders_filter(self):
        self.assertTrue(parse("push", "--strict").strict)
        self.assertFalse(parse("push").strict)
        self.assertEqual(parse("folders", "tax").filter, "tax")
        self.assertIsNone(parse("folders").filter)

    def test_init_options(self):
        args = parse("init", "--remote", "--yes")
        self.assertEqual((args.remote, args.yes), (True, True))
        self.assertEqual((parse("init").remote, parse("init").yes), (False, False))

    def test_the_project_option(self):
        self.assertEqual(parse("-C", "somewhere", "lint").project, "somewhere")

    def test_assemble_output(self):
        self.assertEqual(
            parse("assemble", "--output", "rules.sieve").output, "rules.sieve"
        )
        self.assertIsNone(parse("assemble").output)


class MainTest(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def test_version_prints_the_program_and_package_version(self):
        with mock.patch("fastmail_sieve.cli.package_version", return_value="1.2.3"):
            code, out, _ = self.run_main("--version")
        self.assertEqual((code, out.strip()), (0, "fastmail-sieve 1.2.3"))

    def test_an_uninstalled_package_reports_unknown(self):
        from importlib.metadata import PackageNotFoundError

        from fastmail_sieve.cli import package_version

        with mock.patch("fastmail_sieve.cli.version", side_effect=PackageNotFoundError):
            self.assertEqual(package_version(), "unknown")

    def test_help_groups_the_commands_by_what_they_are_for(self):
        code, out, _ = self.run_main("--help")
        self.assertEqual(code, 0)
        groups = ["Set up", "Sync with Fastmail", "Check", "Understand", "Tools"]
        positions = [out.index(group) for group in groups]
        self.assertEqual(positions, sorted(positions))
        for command in COMMANDS:
            self.assertEqual(out.count(f"\n  {command} "), 1, command)

    def test_a_command_still_has_its_own_help(self):
        code, out, _ = self.run_main("lint", "--help")
        self.assertEqual(code, 0)
        self.assertIn("--fix", out)
        self.assertIn("--strict", out)

    def test_no_command_prints_help_and_fails(self):
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("usage: fastmail-sieve", err)

    def test_unknown_command_is_a_usage_error(self):
        code, _, err = self.run_main("nope")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_a_runtime_error_becomes_a_one_line_failure(self):
        with mock.patch(
            "fastmail_sieve.commands.folders.load_credentials",
            side_effect=RuntimeError("Missing token in the keychain"),
        ):
            code, out, err = self.run_main("folders")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err.strip(), "✗ Missing token in the keychain")

    def test_a_command_exit_code_is_returned(self):
        with mock.patch("fastmail_sieve.commands.lint.run_steps", return_value=1):
            self.assertEqual(self.run_main("lint", "--offline")[0], 1)


if __name__ == "__main__":
    unittest.main()
