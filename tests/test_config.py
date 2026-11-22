import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve import config
from fastmail_sieve.cli import main
from fastmail_sieve.config import Config, find_root, load_config


class InTempDir(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        self.addCleanup(config.use, Config())


class FindRootTest(InTempDir):
    def test_a_config_file_marks_the_root(self):
        (self.root / "fastmail-sieve.toml").write_text("")
        (self.root / "a" / "b").mkdir(parents=True)
        self.assertEqual(find_root(self.root / "a" / "b"), self.root)

    def test_a_fragment_file_marks_the_root(self):
        (self.root / "rules").mkdir()
        (self.root / "rules" / "middle.sieve").write_text("")
        (self.root / "docs").mkdir()
        self.assertEqual(find_root(self.root / "docs"), self.root)

    def test_an_empty_rules_directory_is_not_a_project(self):
        (self.root / "rules").mkdir()
        (self.root / "docs").mkdir()
        self.assertIsNone(find_root(self.root / "docs"))

    def test_other_files_in_a_rules_directory_do_not_make_a_project(self):
        (self.root / "rules").mkdir()
        (self.root / "rules" / "notes.txt").write_text("")
        self.assertIsNone(find_root(self.root))

    def test_the_nearest_project_wins(self):
        (self.root / "rules").mkdir()
        (self.root / "rules" / "top.sieve").write_text("")
        (self.root / "inner" / "rules").mkdir(parents=True)
        (self.root / "inner" / "rules" / "top.sieve").write_text("")
        self.assertEqual(find_root(self.root / "inner"), self.root / "inner")

    def test_no_project_gives_none(self):
        self.assertIsNone(find_root(self.root))


class LoadConfigTest(InTempDir):
    def test_defaults_without_a_file(self):
        loaded = load_config(self.root)
        self.assertEqual(
            loaded.fragment_files,
            ("rules/top.sieve", "rules/middle.sieve", "rules/bottom.sieve"),
        )
        self.assertEqual(loaded.variables_file, "variables.toml")

    def test_reads_the_two_options(self):
        (self.root / "fastmail-sieve.toml").write_text(
            'rules-dir = "sieve"\nvariables-file = "docs/vars.toml"\n'
        )
        loaded = load_config(self.root)
        self.assertEqual(loaded.fragment_files[1], "sieve/middle.sieve")
        self.assertEqual(loaded.variables_file, "docs/vars.toml")

    def test_an_unknown_key_names_itself_and_the_known_ones(self):
        (self.root / "fastmail-sieve.toml").write_text('rule-dir = "x"\n')
        with self.assertRaisesRegex(
            RuntimeError, r"rule-dir.*rules-dir.*variables-file"
        ):
            load_config(self.root)

    def test_a_value_of_the_wrong_type_is_an_error(self):
        (self.root / "fastmail-sieve.toml").write_text("rules-dir = 3\n")
        with self.assertRaisesRegex(RuntimeError, "rules-dir must be a string"):
            load_config(self.root)

    def test_a_broken_file_is_an_error_naming_the_file(self):
        (self.root / "fastmail-sieve.toml").write_text("rules-dir = \n")
        with self.assertRaisesRegex(RuntimeError, "fastmail-sieve.toml"):
            load_config(self.root)


class PathsStayInsideTheProjectTest(InTempDir):
    def load(self, text):
        (self.root / "fastmail-sieve.toml").write_text(text)
        return load_config(self.root)

    def test_unsafe_paths_are_refused_for_both_options(self):
        for option in ("rules-dir", "variables-file"):
            for value in ("/etc", "../outside", "a/../../b", ""):
                with (
                    self.subTest(option=option, value=value),
                    self.assertRaisesRegex(
                        RuntimeError, rf"{option}.*relative.*inside the project"
                    ),
                ):
                    self.load(f"{option} = {value!r}\n")

    def test_a_symlink_out_of_the_project_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.root / "link").symlink_to(outside.name)
        with self.assertRaisesRegex(RuntimeError, "rules-dir.*inside the project"):
            self.load('rules-dir = "link"\n')

    def test_nested_relative_paths_are_fine(self):
        loaded = self.load('rules-dir = "a/b"\nvariables-file = "c/d.toml"\n')
        self.assertEqual(loaded.fragment_files[0], "a/b/top.sieve")


class UntrustedParentTest(InTempDir):
    """A project found by walking up must be one this user controls: running the
    tool in a subdirectory of someone else's directory must not adopt its rules."""

    def make_parent(self, mode=0o700):
        parent = self.root / "parent"
        (parent / "rules").mkdir(parents=True)
        (parent / "rules" / "top.sieve").write_text("# planted\n")
        parent.chmod(mode)
        child = parent / "child"
        child.mkdir()
        return parent, child

    def test_a_world_writable_parent_is_not_adopted(self):
        parent, child = self.make_parent(0o777)
        self.assertIsNone(find_root(child))

    def test_a_parent_owned_by_someone_else_is_not_adopted(self):
        parent, child = self.make_parent()
        with mock.patch("fastmail_sieve.config.os.getuid", return_value=424242):
            self.assertIsNone(find_root(child))

    def test_your_own_private_parent_is_adopted(self):
        parent, child = self.make_parent(0o755)
        self.assertEqual(find_root(child), parent)

    def test_the_starting_directory_is_always_yours_to_choose(self):
        parent, _ = self.make_parent(0o777)
        self.assertEqual(find_root(parent), parent)

    def test_a_trusted_project_beyond_an_untrusted_one_is_still_found(self):
        parent, child = self.make_parent(0o777)
        (self.root / "fastmail-sieve.toml").write_text("")
        self.assertEqual(find_root(child), self.root)


class CurrentTest(InTempDir):
    def test_use_switches_what_the_rest_of_the_code_sees(self):
        from fastmail_sieve.sieve.script import fragment_files

        config.use(Config(rules_dir="elsewhere"))
        self.assertEqual(fragment_files()[0], "elsewhere/top.sieve")


class CliProjectTest(InTempDir):
    def make_project(self):
        (self.root / "rules").mkdir()
        for name in ("top", "middle", "bottom"):
            (self.root / "rules" / f"{name}.sieve").write_text("")
        (self.root / "docs").mkdir()

    def test_runs_from_a_subdirectory_of_the_project(self):
        self.make_project()
        os.chdir(self.root / "docs")
        self.assertEqual(main(["lint", "--offline"]), 0)
        self.assertEqual(Path.cwd().resolve(), self.root)

    def test_it_says_which_project_it_moved_to(self):
        self.make_project()
        os.chdir(self.root / "docs")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            main(["lint", "--offline"])
        self.assertIn(f"using the project at {self.root}", err.getvalue())

    def test_it_says_nothing_when_already_in_the_project(self):
        self.make_project()
        os.chdir(self.root)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            main(["lint", "--offline"])
        self.assertNotIn("using the project", err.getvalue())

    def test_project_option_runs_elsewhere(self):
        self.make_project()
        self.assertEqual(main(["-C", str(self.root), "lint", "--offline"]), 0)

    def test_the_config_file_moves_the_fragments(self):
        (self.root / "fastmail-sieve.toml").write_text('rules-dir = "sieve"\n')
        (self.root / "sieve").mkdir()
        for name in ("top", "middle", "bottom"):
            (self.root / "sieve" / f"{name}.sieve").write_text("")
        self.assertEqual(main(["-C", str(self.root), "lint", "--offline"]), 0)

    def test_a_missing_directory_is_a_clear_failure(self):
        self.assertEqual(main(["-C", str(self.root / "nope"), "lint", "--offline"]), 1)

    def test_outside_a_project_the_missing_file_is_explained(self):
        os.chdir(self.root)
        with self.assertRaisesRegex(RuntimeError, r"rules/top.sieve.*init"):
            from fastmail_sieve.sieve.script import read_fragments

            read_fragments()


if __name__ == "__main__":
    unittest.main()
