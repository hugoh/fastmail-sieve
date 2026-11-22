import tempfile
import unittest
from pathlib import Path

from fastmail_sieve.sieve.format import format_errors, format_files, format_sieve

YOUR_STYLE = """# Folder filing
if allof(
  not string :is "${stop}" "Y",
  not string :is "${spam}" "Y"
) {

  # Code
  if anyof (
    address :domain "from" [
      "cloudsmith.io",
      "crates.io"
    ],
    address :is "from" "community@obsidian.md"
  ) {
    fileinto :mailboxid "Pik" "INBOX.code";
    stop;
  }
}
"""


class LowercaseTest(unittest.TestCase):
    """Sieve ignores the case of keywords, but Fastmail's validator rejects
    anything but lowercase."""

    def test_lowercases_commands_tests_and_tags(self):
        self.assertEqual(
            format_sieve('IF anyOf (TRUE, Header :IS "a" "b") { Stop; }\n'),
            'if anyof (true, header :is "a" "b") { stop; }\n',
        )

    def test_leaves_strings_and_comments_alone(self):
        text = (
            '# Keep THIS\nFileInto "INBOX.Code"; # And THIS\n'
            'if header :contains "Subject" "A \\"Quote\\" B" { /* KEEP */ stop; }\n'
        )
        formatted = format_sieve(text)
        self.assertIn('fileinto "INBOX.Code"; # And THIS', formatted)
        self.assertIn("# Keep THIS", formatted)
        self.assertIn('"A \\"Quote\\" B"', formatted)
        self.assertIn("/* KEEP */", formatted)

    def test_leaves_text_blocks_alone(self):
        text = 'if Jmapquery text:\n{"From": "A@B"}\n.\n) {\n}\n'
        formatted = format_sieve(text)
        self.assertTrue(formatted.startswith("if jmapquery text:\n"))
        self.assertIn('{"From": "A@B"}', formatted)

    def test_a_mixed_case_script_is_reported_as_not_formatted(self):
        self.assertEqual(
            len(format_errors({"middle": "if anyOf (true) { stop; }\n"})), 1
        )
        self.assertEqual(
            format_errors({"middle": "if anyof (true) {\n  stop;\n}\n"}), []
        )


class IndentTest(unittest.TestCase):
    def test_indents_nested_blocks(self):
        self.assertEqual(
            format_sieve("if true {\nif false {\nstop;\n}\n}\n"),
            "if true {\n  if false {\n    stop;\n  }\n}\n",
        )

    def test_dedents_over_indented_lines(self):
        self.assertEqual(
            format_sieve("      if true {\n            stop;\n    }\n"),
            "if true {\n  stop;\n}\n",
        )

    def test_else_and_elsif_line_up_with_their_if(self):
        text = "if a {\nstop;\n} elsif b {\nkeep;\n} else {\ndiscard;\n}\n"
        self.assertEqual(
            format_sieve(text),
            "if a {\n  stop;\n} elsif b {\n  keep;\n} else {\n  discard;\n}\n",
        )

    def test_lists_and_parentheses_indent_their_contents(self):
        text = 'if anyof (\naddress :is "from" [\n"a",\n"b"\n],\nheader :is "x" "y"\n) {\nstop;\n}\n'
        self.assertEqual(
            format_sieve(text),
            'if anyof (\n  address :is "from" [\n    "a",\n    "b"\n  ],\n  header :is "x" "y"\n) {\n  stop;\n}\n',
        )

    def test_your_existing_style_is_left_alone(self):
        self.assertEqual(format_sieve(YOUR_STYLE), YOUR_STYLE)

    def test_comments_follow_the_block_depth(self):
        self.assertEqual(
            format_sieve("if true {\n# note\nstop;\n}\n"),
            "if true {\n  # note\n  stop;\n}\n",
        )


class InlineBlockCommentTest(unittest.TestCase):
    def test_braces_inside_an_inline_block_comment_are_not_counted(self):
        text = "if true { /* { */\n  keep;\n}\nstop;"
        self.assertEqual(format_sieve(text), text)

    def test_a_closing_brace_in_an_inline_comment_does_not_close_the_block(self):
        text = "if true { /* } */\n  keep;\n}"
        self.assertEqual(format_sieve(text), text)

    def test_code_after_an_inline_comment_still_counts(self):
        text = "/* note */ if true {\n  keep;\n}"
        self.assertEqual(format_sieve(text), text)

    def test_a_block_comment_marker_inside_a_string_is_text(self):
        text = 'if header :contains "x" "/* {" {\n  keep;\n}'
        self.assertEqual(format_sieve(text), text)


class FolderNameTest(unittest.TestCase):
    def name(self, written):
        text = f'fileinto :mailboxid "P" "{written}";\n'
        return format_sieve(text).split('"')[3]

    def test_slashes_become_dots(self):
        self.assertEqual(self.name("INBOX.finance/comms"), "INBOX.finance.comms")

    def test_every_name_gets_the_inbox_prefix(self):
        self.assertEqual(self.name("finance/comms"), "INBOX.finance.comms")
        self.assertEqual(self.name("home"), "INBOX.home")

    def test_a_folder_under_inbox_keeps_inbox_as_the_second_segment(self):
        self.assertEqual(self.name("Inbox.Shopping"), "INBOX.Inbox.Shopping")
        self.assertEqual(self.name("Inbox/Shopping"), "INBOX.Inbox.Shopping")
        self.assertEqual(self.name("inbox.Shopping"), "INBOX.Inbox.Shopping")

    def test_the_case_of_inbox_as_second_segment_is_left_as_written(self):
        for written in (
            "INBOX.INBOX.Shopping",
            "INBOX.Inbox.Shopping",
            "INBOX.inbox.Shopping",
        ):
            self.assertEqual(self.name(written), written)

    def test_the_inbox_itself_is_just_inbox(self):
        self.assertEqual(self.name("Inbox"), "INBOX")
        self.assertEqual(self.name("INBOX"), "INBOX")

    def test_already_correct_names_are_unchanged(self):
        for written in ("INBOX.home", "INBOX.Inbox.Shopping", "INBOX.finance.taxes"):
            self.assertEqual(self.name(written), written)

    def test_whole_words_only(self):
        self.assertEqual(self.name("Inboxes"), "INBOX.Inboxes")

    def test_copy_and_implicit_keep_target_are_covered(self):
        self.assertEqual(
            format_sieve(
                'fileinto :copy :mailboxid "P" "a/b";\nimplicit_keep_target :mailboxid "Q" "c";\n'
            ),
            'fileinto :copy :mailboxid "P" "INBOX.a.b";\nimplicit_keep_target :mailboxid "Q" "INBOX.c";\n',
        )

    def test_ids_and_other_strings_are_left_alone(self):
        text = (
            'header :contains "subject" "a/b"; fileinto :mailboxid "P/x" "INBOX.ok";\n'
        )
        self.assertEqual(format_sieve(text), text)

    def test_text_blocks_are_left_alone(self):
        text = 'if jmapquery text:\n:mailboxid "P" "a/b"\n.\n{ stop; }\n'
        self.assertEqual(format_sieve(text), text)


class IgnoredBracketsTest(unittest.TestCase):
    def test_brackets_in_strings_are_ignored(self):
        text = 'if header :contains "x" "{" {\nstop;\n}\nkeep;\n'
        self.assertEqual(
            format_sieve(text), 'if header :contains "x" "{" {\n  stop;\n}\nkeep;\n'
        )

    def test_escaped_quotes_do_not_end_a_string(self):
        text = 'if header :contains "x" "a \\" {" {\nstop;\n}\n'
        self.assertEqual(
            format_sieve(text), 'if header :contains "x" "a \\" {" {\n  stop;\n}\n'
        )

    def test_brackets_in_comments_are_ignored(self):
        self.assertEqual(format_sieve("# { not code\nstop;\n"), "# { not code\nstop;\n")

    def test_hash_inside_a_string_is_not_a_comment(self):
        text = 'if header :contains "x" "#" {\nstop;\n}\n'
        self.assertEqual(
            format_sieve(text), 'if header :contains "x" "#" {\n  stop;\n}\n'
        )

    def test_unbalanced_closers_never_go_negative(self):
        self.assertEqual(format_sieve("}\n  stop;\n"), "}\nstop;\n")


class TextBlockTest(unittest.TestCase):
    def test_text_blocks_are_left_untouched(self):
        text = (
            "if allof(\nnot true,\njmapquery text:\n"
            '{\n      "from": "x"\n   }\n.\n\n) {\nstop;\n}\n'
        )
        self.assertEqual(
            format_sieve(text),
            "if allof(\n  not true,\n  jmapquery text:\n"
            '{\n      "from": "x"\n   }\n.\n\n) {\n  stop;\n}\n',
        )

    def test_text_in_a_string_does_not_start_a_block(self):
        text = 'if header :contains "x" "text:" {\nstop;\n}\n'
        self.assertEqual(
            format_sieve(text), 'if header :contains "x" "text:" {\n  stop;\n}\n'
        )

    def test_block_comments_are_left_untouched(self):
        text = "if true {\n/* a\n      b */\nstop;\n}\n"
        self.assertEqual(
            format_sieve(text), "if true {\n  /* a\n      b */\n  stop;\n}\n"
        )


class WhitespaceTest(unittest.TestCase):
    def test_trailing_whitespace_and_blank_line_padding_are_removed(self):
        self.assertEqual(format_sieve("stop;   \n   \nkeep;\n"), "stop;\n\nkeep;\n")

    def test_missing_final_newline_is_kept_missing(self):
        self.assertEqual(format_sieve("if true {\nstop;\n}"), "if true {\n  stop;\n}")

    def test_is_idempotent(self):
        text = (
            'if anyof (\naddress :is "from" [\n"a"\n]\n) {\n   if true {\nstop;\n}\n}\n'
        )
        once = format_sieve(text)
        self.assertEqual(format_sieve(once), once)


class FormatErrorsTest(unittest.TestCase):
    def test_names_each_unformatted_file_and_the_fix(self):
        errors = format_errors(
            {"rules/a.sieve": "if true {\nstop;\n}\n", "rules/b.sieve": "stop;\n"}
        )
        self.assertEqual(
            errors, ["rules/a.sieve is not formatted: run `fastmail-sieve lint --fix`"]
        )

    def test_formatted_files_have_no_errors(self):
        self.assertEqual(format_errors({"a.sieve": "if true {\n  stop;\n}\n"}), [])


class FormatFilesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "x.sieve"

    def test_rewrites_files_in_place(self):
        self.path.write_text("if true {\nstop;\n}\n")
        self.assertEqual(format_files([str(self.path)]), [str(self.path)])
        self.assertEqual(self.path.read_text(), "if true {\n  stop;\n}\n")

    def test_check_reports_without_changing_the_file(self):
        self.path.write_text("if true {\nstop;\n}\n")
        self.assertEqual(format_files([str(self.path)], check=True), [str(self.path)])
        self.assertEqual(self.path.read_text(), "if true {\nstop;\n}\n")

    def test_formatted_files_are_not_reported(self):
        self.path.write_text("if true {\n  stop;\n}\n")
        self.assertEqual(format_files([str(self.path)], check=True), [])


if __name__ == "__main__":
    unittest.main()
