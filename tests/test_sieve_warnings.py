import unittest

from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.report import build_rules
from fastmail_sieve.sieve.warnings import collect_warnings

DOCS = {
    "stop": {"when_no": "no earlier rule has handled the message"},
    "spam": {"when_no": "Fastmail does not consider the message spam"},
}
LABEL = 'if mailboxidexists "P" { set "L0_home" "Y"; set "skipinbox" "Y"; }'
MOVE = LABEL + '\nset "stop" "Y";'
FINANCE = '# Finance\nif address :is "from" "a@b.c" { fileinto "INBOX.X"; stop; }\n'


def ui_rule(search, body):
    return (
        f'# Search: "from:{search}"\n'
        f'if jmapquery text:\n{{\n   "from": "{search}"\n}}\n.\n{{\n{body}\n}}\n'
    )


def rules_for(fragments, ui=""):
    return build_rules(fragments, FASTMAIL_REQUIRE + ui, DOCS)


def lines(fragments, ui="", disabled=(), variables=()):
    return collect_warnings(rules_for(fragments, ui), disabled, variables)


class CollectTest(unittest.TestCase):
    def test_an_overlap_is_reported_once_for_the_pair(self):
        found = lines({"rules/middle.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        self.assertEqual(
            found,
            [
                (
                    "overlap",
                    "rule 1 (middle) vs rule 2 (UI) on a@b.c: rule 2 never applies",
                )
            ],
        )

    def test_both_apply(self):
        custom = 'if address :domain "from" "b.c" { fileinto :copy "INBOX.X"; }\n'
        found = lines({"rules/middle.sieve": custom}, ui_rule("a@b.c", LABEL))
        self.assertTrue(found[0][1].endswith("both apply"))

    def test_bottom_rule_runs_after_the_ui_rule(self):
        found = lines({"rules/bottom.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        self.assertEqual(
            found,
            [
                (
                    "overlap",
                    "rule 1 (UI) vs rule 2 (bottom) on a@b.c: rule 2 runs after rule 1",
                )
            ],
        )

    def test_duplicate_ui_rules(self):
        found = lines({}, ui_rule("a@b.c", LABEL) + ui_rule("a@b.c", LABEL))
        self.assertEqual(found, [("duplicate", "rule 2 (UI) repeats rule 1 (UI)")])

    def test_same_search_with_different_actions_is_a_conflict(self):
        found = lines({}, ui_rule("a@b.c", LABEL) + ui_rule("A@B.c", MOVE))
        self.assertEqual(
            found,
            [
                (
                    "conflict",
                    "rule 2 (UI) has the same search as rule 1 but different actions",
                )
            ],
        )

    def test_disabled_rules_and_variable_warnings_are_included(self):
        found = lines(
            {},
            ui_rule("a@b.c", LABEL),
            disabled=["from:old@x.y"],
            variables=["x: stale"],
        )
        self.assertIn(
            ("disabled", "UI rule from:old@x.y is commented out in Fastmail"), found
        )
        self.assertIn(("variables", "x: stale"), found)

    def test_nothing_to_report(self):
        self.assertEqual(
            lines({"rules/middle.sieve": FINANCE}, ui_rule("x@y.z", LABEL)), []
        )


if __name__ == "__main__":
    unittest.main()
