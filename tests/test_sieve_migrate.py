import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from fastmail_sieve.cli import main
from fastmail_sieve.sieve.format import format_sieve
from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.migrate import migrate

FOLDERS = (
    'if string :is "${L0_home}" "Y" {\n'
    '  fileinto :copy :mailboxid "P-xSc" "INBOX.home";\n  set "hasmailbox" "Y";\n}\n'
    'if string :is "${L1_shop}" "Y" {\n'
    '  fileinto :copy :mailboxid "P-yRL" "INBOX.INBOX.Shopping 🛒";\n  set "hasmailbox" "Y";\n}\n'
)


def search(title, query_json, body):
    return (
        f'# Search: "{title}"\n'
        'if allof(\n  not string :is "${stop}" "Y",\n  jmapquery text:\n'
        f"{query_json}\n.\n\n) {{\n{body}\n}}\n"
    )


def from_query(*values):
    if len(values) == 1:
        return f'{{ "from": "{values[0]}" }}'
    conditions = ", ".join(f'{{ "from": "{v}" }}' for v in values)
    return f'{{ "conditions": [{conditions}], "operator": "OR" }}'


def folder_body(variable, *extra):
    sets = "".join(f'  set "{name}" "Y";\n' for name in (variable, *extra))
    return f'  if mailboxidexists "P" {{\n{sets}  }}'


def script(*rules):
    return FASTMAIL_REQUIRE + "".join(rules) + FOLDERS


def one(title, query, body):
    return migrate(script(search(title, query, body)))


class TranslateTest(unittest.TestCase):
    def test_label_copies_into_the_folder_and_keeps_going(self):
        result = one("from:a@b.c", from_query("a@b.c"), folder_body("L0_home"))
        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.snippet,
            "  # from:a@b.c\n"
            '  if address :is "from" "a@b.c" {\n'
            '    fileinto :copy :mailboxid "P-xSc" "INBOX.home";\n'
            "  }\n",
        )

    def test_skip_inbox_and_stop_is_a_move(self):
        body = folder_body("L1_shop", "skipinbox") + '\n  set "stop" "Y";'
        result = one("from:a@b.c", from_query("a@b.c"), body)
        self.assertIn(
            '    fileinto :mailboxid "P-yRL" "INBOX.INBOX.Shopping 🛒";\n    stop;\n',
            result.snippet,
        )
        self.assertNotIn(":copy", result.snippet)

    def test_skip_inbox_without_stop_moves_and_keeps_going(self):
        result = one("t", from_query("a@b.c"), folder_body("L0_home", "skipinbox"))
        self.assertIn('fileinto :mailboxid "P-xSc"', result.snippet)
        self.assertNotIn("stop;", result.snippet)

    def test_pin_flags_before_filing(self):
        result = one("t", from_query("a@b.c"), folder_body("L0_home", "flagged"))
        lines = result.snippet.splitlines()
        flag = next(
            i for i, line in enumerate(lines) if 'addflag "\\\\Flagged";' in line
        )
        filing = next(i for i, line in enumerate(lines) if "fileinto" in line)
        self.assertLess(flag, filing)

    def test_bare_and_at_domains_use_the_domain_test(self):
        for value in ("b.c", "@b.c"):
            result = one("t", from_query(value), folder_body("L0_home"))
            self.assertIn('if address :domain "from" "b.c" {', result.snippet)

    def test_several_addresses_become_a_list(self):
        result = one("t", from_query("a@b.c", "d@e.f"), folder_body("L0_home"))
        self.assertIn(
            '  if address :is "from" [\n    "a@b.c",\n    "d@e.f"\n  ] {\n',
            result.snippet,
        )

    def test_addresses_and_domains_are_combined_with_anyof(self):
        result = one("t", from_query("a@b.c", "e.f"), folder_body("L0_home"))
        self.assertIn(
            '  if anyof (\n    address :is "from" "a@b.c",\n    address :domain "from" "e.f"\n  ) {\n',
            result.snippet,
        )

    def test_rules_are_separated_by_a_blank_line(self):
        text = script(
            search("one", from_query("a@b.c"), folder_body("L0_home")),
            search("two", from_query("x@y.z"), folder_body("L1_shop")),
        )
        self.assertIn("  }\n\n  # two\n", migrate(text).snippet)

    def test_the_output_passes_the_linter(self):
        result = one(
            "t",
            from_query("a@b.c", "e.f"),
            folder_body("L1_shop", "flagged", "skipinbox") + '\n  set "stop" "Y";',
        )
        self.assertEqual(result.errors, [])


class UnsupportedTest(unittest.TestCase):
    def assert_unsupported(self, query, body, expected):
        result = one("from:t", query, body)
        self.assertEqual(result.snippet, "")
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn("from:t", result.errors[0])
        self.assertIn(expected, result.errors[0])

    def test_variables_it_cannot_express(self):
        self.assert_unsupported(
            from_query("a@b.c"), folder_body("L0_home", "notify"), "notify"
        )

    def test_several_folders(self):
        body = folder_body("L0_home", "L1_shop")
        self.assert_unsupported(from_query("a@b.c"), body, "several folders")

    def test_no_folder(self):
        self.assert_unsupported(
            from_query("a@b.c"), folder_body("skipinbox"), "no folder"
        )

    def test_missing_filing_block(self):
        self.assert_unsupported(from_query("a@b.c"), folder_body("L9_gone"), "l9_gone")

    def test_other_conditions(self):
        text = (
            FASTMAIL_REQUIRE
            + '# Search: "t"\nif header :contains "subject" "x" {\n'
            + folder_body("L0_home")
            + "\n}\n"
            + FOLDERS
        )
        result = migrate(text)
        self.assertEqual(result.snippet, "")
        self.assertIn("condition", result.errors[0])

    def test_every_unsupported_rule_is_reported_and_nothing_is_printed(self):
        text = script(
            search("good", from_query("a@b.c"), folder_body("L0_home")),
            search("bad one", from_query("a@b.c"), folder_body("L0_home", "mute")),
            search("bad two", from_query("a@b.c"), folder_body("L0_home", "notify")),
        )
        result = migrate(text)
        self.assertEqual(result.snippet, "")
        self.assertEqual(len(result.errors), 2)
        self.assertIn("bad one", result.errors[0])
        self.assertIn("bad two", result.errors[1])


CONTACT = '{ "fromContactCardUid": "abc-123" }'


def convert(*rules):
    return migrate(script(*rules))


class JmapqueryTest(unittest.TestCase):
    def test_a_short_search_is_a_one_line_quoted_string(self):
        result = convert(search("from:Contact", CONTACT, folder_body("L0_home")))
        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.snippet,
            "  # from:Contact\n"
            '  if jmapquery "{\\"fromContactCardUid\\":\\"abc-123\\"}" {\n'
            '    fileinto :copy :mailboxid "P-xSc" "INBOX.home";\n'
            "  }\n",
        )

    def test_a_long_search_falls_back_to_a_text_block(self):
        long_value = "x" * 90
        result = convert(
            search("t", f'{{ "subject": "{long_value}" }}', folder_body("L0_home"))
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.snippet.splitlines()[:6],
            [
                "  # t",
                "  if jmapquery text:",
                "{",
                f'   "subject": "{long_value}"',
                "}",
                ".",
            ],
        )
        self.assertEqual(result.snippet.splitlines()[6], "  {")

    def test_both_forms_are_already_formatted_when_pasted_into_a_block(self):
        for query in (CONTACT, f'{{ "subject": "{"y" * 90}" }}'):
            result = convert(search("t", query, folder_body("L0_home")))
            pasted = "if true {\n" + result.snippet + "}\n"
            self.assertEqual(format_sieve(pasted), pasted)

    def test_other_searches_pass_through_too(self):
        result = convert(
            search("t", '{ "subject": "invoice" }', folder_body("L0_home"))
        )
        self.assertEqual(result.errors, [])
        self.assertIn('\\"subject\\":\\"invoice\\"', result.snippet)

    def test_and_searches_pass_through_unchanged(self):
        query = (
            '{ "conditions": [{ "from": "a@b.c" }, { "to": "x" }], "operator": "AND" }'
        )
        result = convert(search("t", query, folder_body("L0_home")))
        self.assertEqual(result.errors, [])
        self.assertIn('\\"operator\\":\\"AND\\"', result.snippet)

    def test_plain_from_searches_still_use_address_tests(self):
        result = convert(search("t", from_query("a@b.c"), folder_body("L0_home")))
        self.assertIn('if address :is "from" "a@b.c" {', result.snippet)
        self.assertNotIn("jmapquery", result.snippet)

    def test_actions_are_translated_as_usual(self):
        body = folder_body("L1_shop", "flagged", "skipinbox") + '\n  set "stop" "Y";'
        result = convert(search("t", CONTACT, body))
        self.assertIn('addflag "\\\\Flagged";', result.snippet)
        self.assertIn('fileinto :mailboxid "P-yRL"', result.snippet)
        self.assertIn("stop;", result.snippet)

    def test_other_unsupported_things_are_still_errors(self):
        result = convert(search("t", CONTACT, folder_body("L0_home", "notify")))
        self.assertEqual(result.snippet, "")
        self.assertIn("notify", result.errors[0])

    def test_unreadable_searches_are_still_errors(self):
        text = script(search("t", "not json at all", folder_body("L0_home")))
        result = migrate(text)
        self.assertEqual(result.snippet, "")
        self.assertIn("could not be read", result.errors[0])


class CliTest(unittest.TestCase):
    def run_main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["migrate", "--from-file", *args])
        return code, out.getvalue(), err.getvalue()

    def test_contact_searches_convert_without_any_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.sieve"
            path.write_text(script(search("t", CONTACT, folder_body("L0_home"))))
            code, out, err = self.run_main([str(path)])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("jmapquery", out)

    def test_untranslatable_rules_exit_1_with_a_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.sieve"
            path.write_text(
                script(search("t", CONTACT, folder_body("L0_home", "notify")))
            )
            code, out, err = self.run_main([str(path)])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("notify", err)


class DisabledAndEmptyTest(unittest.TestCase):
    def test_disabled_rules_are_skipped_and_reported(self):
        disabled = (
            '# Search: "from:old@x.y"\n# if true {\n#   set "L0_home" "Y";\n# }\n'
        )
        text = script(
            disabled, search("from:a@b.c", from_query("a@b.c"), folder_body("L0_home"))
        )
        result = migrate(text)
        self.assertEqual(result.skipped, ["from:old@x.y"])
        self.assertIn("# from:a@b.c", result.snippet)
        self.assertNotIn("old@x.y", result.snippet)

    def test_no_ui_rules(self):
        result = migrate(FASTMAIL_REQUIRE + "stop;\n")
        self.assertEqual((result.snippet, result.errors), ("", []))


if __name__ == "__main__":
    unittest.main()
