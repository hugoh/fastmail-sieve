import re
import unittest

from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.variables import (
    analyze,
    fragment_variable_names,
    load_descriptions,
    render,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")
DESCRIBED = {
    "stop": {"description": "Stop all later rules."},
    "flag": {"description": "Flag the message."},
}


def run(body, descriptions=DESCRIBED):
    return analyze(FASTMAIL_REQUIRE + body, descriptions)


class AnalyzeTest(unittest.TestCase):
    def test_set_and_read_is_clean(self):
        report = run('set "stop" "Y";\nif string :is "${stop}" "Y" { stop; }\n')
        self.assertEqual(report.errors, [])
        self.assertEqual(report.variables["stop"].description, "Stop all later rules.")

    def test_read_but_never_set_is_an_error(self):
        report = run('if string :is "${stop}" "Y" { stop; }\n')
        self.assertEqual(report.errors, ["stop: read but never set"])

    def test_set_but_never_read_is_an_error(self):
        report = run('set "stop" "Y";\n')
        self.assertEqual(report.errors, ["stop: set but never read"])

    def test_may_be_unset_allows_read_without_set(self):
        described = {"stop": {"description": "x", "may_be_unset": True}}
        report = run('if string :is "${stop}" "Y" { stop; }\n', described)
        self.assertEqual(report.errors, [])

    def test_undocumented_variable_is_an_error(self):
        report = run('set "mystery" "Y";\nif string :is "${mystery}" "Y" { stop; }\n')
        self.assertEqual(report.errors, ["mystery: no description in variables.toml"])

    def test_folder_label_variables_are_described_automatically(self):
        report = run(
            'set "L0_home" "Y";\nif string :is "${L0_home}" "Y" { fileinto "INBOX.home"; }\n'
        )
        self.assertEqual(report.errors, [])
        self.assertIn("home", report.variables["l0_home"].description)

    def test_names_are_case_insensitive(self):
        report = run('set "Stop" "Y";\nif string :is "${STOP}" "Y" { stop; }\n')
        self.assertEqual(report.errors, [])

    def test_processcalendar_outputs_count_as_set(self):
        described = {"outcome": {"description": "x"}, "why": {"description": "y"}}
        report = run(
            'processcalendar :outcome "outcome" :reason "why";\n'
            'if string :is "${outcome}${why}" "z" { stop; }\n',
            described,
        )
        self.assertEqual(report.errors, [])

    def test_reads_inside_action_arguments_count(self):
        described = {"stop": {"description": "x"}}
        report = run('set "stop" "Y";\naddheader "X-A" "${stop}";\n', described)
        self.assertEqual(report.errors, [])

    def test_description_for_absent_variable_is_only_a_warning(self):
        report = run('set "stop" "Y";\nif string :is "${stop}" "Y" { stop; }\n')
        self.assertEqual(
            report.warnings, ["flag: described in variables.toml but not in the script"]
        )
        self.assertEqual(report.errors, [])

    def test_records_where_variables_are_set_and_read(self):
        report = run(
            '# Noise\nset "stop" "Y";\n# Later\nif string :is "${stop}" "Y" { stop; }\n'
        )
        variable = report.variables["stop"]
        self.assertEqual(variable.set_by, ["Noise"])
        self.assertEqual(variable.read_by, ["Later"])

    def test_sync_markers_are_not_used_as_labels(self):
        report = run(
            '#### Managed by Sieve Sync Start ####\n# Noise\nset "stop" "Y";\n'
            'if string :is "${stop}" "Y" { stop; }\n'
        )
        self.assertEqual(report.variables["stop"].set_by, ["Noise"])

    def test_the_new_markers_are_not_used_as_labels_either(self):
        report = run(
            '#### Managed by fastmail-sieve: start ####\n# Noise\nset "stop" "Y";\n'
            'if string :is "${stop}" "Y" { stop; }\n'
        )
        self.assertEqual(report.variables["stop"].set_by, ["Noise"])

    def test_syntax_error_raises(self):
        with self.assertRaises(ValueError):
            run("if true { stop;\n")


class ScopeTest(unittest.TestCase):
    def test_variables_only_fastmail_touches_are_not_errors(self):
        report = analyze(
            FASTMAIL_REQUIRE + 'if string :is "${fm}" "Y" { stop; }\n', {}, scope=set()
        )
        self.assertEqual(report.errors, [])
        self.assertIn("fm", report.variables)

    def test_variables_your_rules_touch_are_checked(self):
        body = 'if string :is "${mine}" "Y" { stop; }\n'
        report = analyze(FASTMAIL_REQUIRE + body, {}, scope={"mine"})
        self.assertIn("mine: read but never set", report.errors)
        self.assertIn("mine: no description in variables.toml", report.errors)

    def test_a_variable_you_set_but_nothing_reads_is_an_error(self):
        report = analyze(
            FASTMAIL_REQUIRE + 'set "mine" "Y";\n',
            {"mine": {"description": "x"}},
            scope={"mine"},
        )
        self.assertEqual(report.errors, ["mine: set but never read"])

    def test_fragment_names_include_sets_and_reads_lowercased(self):
        names = fragment_variable_names(
            ['set "A" "Y";\nif string :is "${B}${c}" "Y" { stop; }\n', ""]
        )
        self.assertEqual(names, {"a", "b", "c"})

    def test_fragment_syntax_error_raises(self):
        with self.assertRaises(ValueError):
            fragment_variable_names(["if true { stop;\n"])


class RenderTest(unittest.TestCase):
    def render(self, **kwargs):
        report = run(
            '# Noise\nset "stop" "Y";\n# Later\nif string :is "${stop}" "Y" { stop; }\n'
        )
        return render(report, **kwargs)

    def test_is_a_table_with_one_row_per_variable(self):
        text = self.render()
        self.assertIn("╭", text)
        self.assertRegex(
            text, r"│\s+Variable\s+│\s+Meaning\s+│\s+Set by\s+│\s+Read by\s+│"
        )
        self.assertRegex(
            text, r"│\s+stop\s+│\s+Stop all later rules\.\s+│\s+Noise\s+│\s+Later\s+│"
        )

    def test_many_locations_are_listed_one_per_line_with_a_count(self):
        body = "".join(f'# S{i}\nset "stop" "Y";\n' for i in range(6)) + (
            'if string :is "${stop}" "Y" { stop; }\n'
        )
        text = render(run(body))
        self.assertIn("S0", text)
        self.assertIn("and 2 more", text)
        self.assertNotIn("S4", text)

    def test_unset_or_unread_shows_nowhere(self):
        text = render(run('set "stop" "Y";\n'))
        self.assertIn("nowhere", text)

    def test_colour_only_adds_escape_codes(self):
        plain = self.render()
        coloured = self.render(color=True)
        self.assertIn("\x1b[", coloured)
        self.assertEqual(ANSI.sub("", coloured), plain)


class LoadDescriptionsTest(unittest.TestCase):
    def test_reads_toml_tables(self):
        descriptions = load_descriptions(
            '[stop]\ndescription = "d"\nmay_be_unset = true\n'
        )
        self.assertEqual(
            descriptions, {"stop": {"description": "d", "may_be_unset": True}}
        )

    def test_keys_are_lowercased(self):
        self.assertIn("abc", load_descriptions('[ABC]\ndescription = "d"\n'))


class VariableDocsFileTest(unittest.TestCase):
    def test_a_missing_file_says_how_to_create_it(self):
        import tempfile
        from pathlib import Path

        from fastmail_sieve.config import Project
        from fastmail_sieve.sieve.variables import load_variable_docs

        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(
                RuntimeError, r"variables\.toml.*fastmail-sieve init"
            ),
        ):
            load_variable_docs(Project(Path(directory)))


if __name__ == "__main__":
    unittest.main()
