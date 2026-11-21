import unittest

from fastmail_sieve.sieve.lint import check_fragments, check_markers, check_syntax
from fastmail_sieve.sieve.script import MARKER_START

REQUIRE = (
    'require ["fileinto", "variables", "vnd.cyrus.jmapquery", "mailboxid", '
    '"special-use", "relational", "vnd.cyrus.implicit_keep_target", "processcalendar", '
    '"imap4flags", "mailbox", "copy", "editheader", "comparator-i;ascii-numeric"];\n'
)
START = "#### Managed by Sieve Sync Start ####\n#### Managed by Sieve Sync End ####\n"

FASTMAIL_BODY = r"""
if header :contains "X-FM-Masked-Email" " state=disabled" {
  fileinto :specialuse "\\Trash" "INBOX.Trash";
  stop;
}
if allof(not string :is "${stop}" "Y", jmapquery text:
{
   "from": "reply@mail.acculynx.com"
}
.
) {
  if mailboxidexists "P-xSc" { set "L0" "Y"; }
  fileinto :copy :mailboxid "P-xSc" "INBOX.home";
}
if header :comparator "i;ascii-numeric" :value "ge" "X-Spam-score" "5" { stop; }
addheader "X-Test" "v";
implicit_keep_target :mailboxid "P-Lmg" "INBOX.INBOX.whugoh";
processcalendar :allowpublic :calendarid "CCF" :deletecancelled :outcome "o" :reason "r";
"""


class SyntaxTest(unittest.TestCase):
    def test_accepts_fastmail_extensions(self):
        self.assertIsNone(check_syntax(REQUIRE + FASTMAIL_BODY))

    def test_rejects_syntax_error(self):
        self.assertIsNotNone(check_syntax(REQUIRE + "if true { stop;\n"))

    def test_rejects_unknown_command(self):
        self.assertIsNotNone(check_syntax(REQUIRE + 'bogus "x";\n'))


class FragmentsTest(unittest.TestCase):
    def test_accepts_valid_fragments(self):
        self.assertIsNone(check_fragments("", 'set "a" "Y";\n', "stop;\n"))

    def test_rejects_syntax_error_in_fragment(self):
        self.assertIsNotNone(check_fragments("", "if true { stop;\n", ""))

    def test_rejects_markers_inside_fragment(self):
        self.assertIsNotNone(check_fragments("", START, ""))


NEW_START = "#### Managed by fastmail-sieve: start ####\n#### Managed by fastmail-sieve: end ####\n"


class MarkerStylesLintTest(unittest.TestCase):
    def test_accepts_three_pairs_of_the_new_style(self):
        self.assertIsNone(check_markers(REQUIRE + NEW_START * 3))

    def test_accepts_a_mix_of_styles_pair_by_pair(self):
        self.assertIsNone(check_markers(REQUIRE + START + NEW_START + START))

    def test_rejects_a_pair_that_starts_in_one_style_and_ends_in_the_other(self):
        crossed = "#### Managed by Sieve Sync Start ####\n#### Managed by fastmail-sieve: end ####\n"
        self.assertIsNotNone(check_markers(REQUIRE + crossed + START * 2))

    def test_rejects_a_new_end_before_its_start(self):
        swapped = "#### Managed by fastmail-sieve: end ####\n#### Managed by fastmail-sieve: start ####\n"
        self.assertIsNotNone(check_markers(REQUIRE + swapped + NEW_START * 2))

    def test_fragments_may_not_contain_either_style(self):
        for text in (NEW_START, START):
            self.assertRegex(check_fragments("", text, ""), "managed-block markers")


class OddMarkerCountTest(unittest.TestCase):
    def test_an_odd_number_of_markers_is_a_message_not_an_exception(self):
        for count in (1, 3, 5):
            text = "\n".join([MARKER_START] * count)
            with self.subTest(count=count):
                self.assertIn("expected 3 start/end marker pairs", check_markers(text))


class MarkersTest(unittest.TestCase):
    def test_accepts_three_pairs(self):
        self.assertIsNone(check_markers(REQUIRE + START * 3))

    def test_rejects_missing_pair(self):
        self.assertIsNotNone(check_markers(REQUIRE + START * 2))

    def test_rejects_extra_pair(self):
        self.assertIsNotNone(check_markers(REQUIRE + START * 4))

    def test_rejects_end_before_start(self):
        swapped = "#### Managed by Sieve Sync End ####\n#### Managed by Sieve Sync Start ####\n"
        self.assertIsNotNone(check_markers(REQUIRE + swapped + START * 2))


if __name__ == "__main__":
    unittest.main()
