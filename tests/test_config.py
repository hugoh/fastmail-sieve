import os
import tempfile
import unittest
from pathlib import Path

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

    def test_a_rules_directory_marks_the_root(self):
        (self.root / "rules").mkdir()
        (self.root / "docs").mkdir()
        self.assertEqual(find_root(self.root / "docs"), self.root)

    def test_the_nearest_project_wins(self):
        (self.root / "rules").mkdir()
        (self.root / "inner" / "rules").mkdir(parents=True)
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
