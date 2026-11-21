import unittest

from fastmail_sieve.fastmail.mailboxes import (
    check_ids,
    check_names,
    fetch_mailboxes,
    references,
    render,
    with_paths,
)

BOXES = [
    {"id": "P-lC0", "name": "finance", "parentId": None, "role": None},
    {"id": "P-lC2", "name": "taxes", "parentId": "P-lC0", "role": None},
    {"id": "P-in", "name": "Inbox", "parentId": None, "role": "inbox"},
    {"id": "P-sh", "name": "Shopping", "parentId": "P-in", "role": None},
]
CREDS = {"token": "fma1-x", "cookie": "c=1"}


class PathsTest(unittest.TestCase):
    def test_nested_path_and_sorting(self):
        self.assertEqual(
            [b["path"] for b in with_paths(BOXES)],
            ["finance", "finance.taxes", "Inbox", "Inbox.Shopping"],
        )

    def test_render_filters_and_shows_role(self):
        self.assertEqual(len(render(BOXES, "TAX")), 1)
        self.assertIn("[inbox]", render(BOXES)[2])
        self.assertIn("Inbox.Shopping", render(BOXES)[3])


class ReferencesTest(unittest.TestCase):
    def test_finds_fileinto_exists_and_implicit_keep(self):
        text = (
            'fileinto :copy :mailboxid "A1" "INBOX.a";\n'
            'if mailboxidexists "B2" { stop; }\n'
            'implicit_keep_target :mailboxid "C3" "x";\n'
        )
        self.assertEqual(
            references(text), [("A1", "INBOX.a"), ("B2", None), ("C3", "x")]
        )


def all_problems(boxes, files):
    return check_ids(boxes, files)[1] + check_names(boxes, files)[1]


class ListFormReferencesTest(unittest.TestCase):
    def test_every_id_of_a_mailboxidexists_list_is_found(self):
        text = 'if mailboxidexists ["A1", "B2","C3"] { keep; }'
        self.assertEqual(references(text), [("A1", None), ("B2", None), ("C3", None)])

    def test_a_single_id_and_the_list_form_can_mix(self):
        text = 'mailboxidexists "A1";\nmailboxidexists ["B2"];\nfileinto :mailboxid "C3" "x";'
        self.assertEqual([found for found, _ in references(text)], ["A1", "B2", "C3"])


class CheckTest(unittest.TestCase):
    def problems(self, text):
        return all_problems(BOXES, {"rules/middle.sieve": text})

    def test_reports_missing_ids_and_names_that_differ(self):
        text = 'fileinto :mailboxid "P-lC2" "INBOX.finance.taxes"; fileinto :mailboxid "GONE" "old";'
        [problem] = self.problems(text)
        self.assertIn('GONE does not exist (rule names it "old")', problem)

    def test_a_name_that_differs_from_the_live_path_is_a_problem(self):
        [problem] = self.problems('fileinto :mailboxid "P-lC2" "INBOX.taxes";')
        self.assertIn('names it "INBOX.taxes"', problem)
        self.assertIn('"INBOX.finance.taxes"', problem)

    def test_names_follow_the_sieve_spelling(self):
        self.assertEqual(
            self.problems('fileinto :mailboxid "P-sh" "INBOX.Inbox.Shopping";'), []
        )
        self.assertEqual(self.problems('fileinto :mailboxid "P-in" "INBOX";'), [])
        self.assertEqual(
            len(self.problems('fileinto :mailboxid "P-sh" "INBOX.INBOX.Shopping";')), 1
        )

    def test_emoji_variation_selectors_do_not_matter(self):
        boxes = [{"id": "Pik", "name": "\u2328 code", "parentId": None, "role": None}]
        text = 'fileinto :mailboxid "Pik" "INBOX.\u2328\ufe0f code";'
        self.assertEqual(all_problems(boxes, {"f": text}), [])

    def test_mailboxidexists_has_no_name_to_compare(self):
        self.assertEqual(self.problems('if mailboxidexists "P-lC2" { stop; }'), [])


class SplitChecksTest(unittest.TestCase):
    FILES = {
        "f": 'fileinto :mailboxid "GONE" "x"; fileinto :mailboxid "P-lC2" "taxes";'
        ' fileinto :mailboxid "P-lC0" "INBOX.finance";'
    }

    def test_ids_reports_only_missing_ones_and_counts_the_found(self):
        found, problems = check_ids(BOXES, self.FILES)
        self.assertEqual(found, 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("GONE does not exist", problems[0])

    def test_names_ignores_missing_ids_and_counts_the_matches(self):
        matched, problems = check_names(BOXES, self.FILES)
        self.assertEqual(matched, 1)
        self.assertEqual(len(problems), 1)
        self.assertIn('names it "taxes"', problems[0])


class FetchTest(unittest.TestCase):
    def test_uses_session_account_and_api_url(self):
        calls = []

        def call(url, credentials, body=None):
            calls.append((url, body))
            if body is None:
                return {
                    "apiUrl": "https://api/x",
                    "primaryAccounts": {"urn:ietf:params:jmap:mail": "u1"},
                }
            return {"methodResponses": [["Mailbox/get", {"list": BOXES}, "m1"]]}

        self.assertEqual(fetch_mailboxes(CREDS, call), BOXES)
        self.assertEqual(calls[1][0], "https://api/x")
        self.assertEqual(calls[1][1]["methodCalls"][0][1]["accountId"], "u1")

    def test_jmap_error_is_raised(self):
        def call(url, credentials, body=None):
            if body is None:
                return {
                    "apiUrl": "u",
                    "primaryAccounts": {"urn:ietf:params:jmap:mail": "a"},
                }
            return {"methodResponses": [["error", {"description": "nope"}, "m1"]]}

        with self.assertRaisesRegex(RuntimeError, "nope"):
            fetch_mailboxes(CREDS, call)
