import re
import unittest

from fastmail_sieve.sieve.lint import FASTMAIL_REQUIRE
from fastmail_sieve.sieve.report import (
    _condition_line,
    _lines,
    build_full_rules,
    build_rules,
    disabled_ui_rules,
    render,
)

DOCS = {
    "stop": {
        "when_yes": "an earlier rule already handled the message",
        "when_no": "no earlier rule has handled the message",
        "set_yes": "🛑 stop applying further rules",
    },
    "spam": {"when_no": "Fastmail does not consider the message spam"},
    "skipinbox": {"set_yes": "keep the message out of the Inbox"},
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def ui_rule(search, body):
    return (
        f'# Search: "from:{search}"\n'
        f'if jmapquery text:\n{{\n   "from": "{search}"\n}}\n.\n{{\n{body}\n}}\n'
    )


LABEL = 'if mailboxidexists "P" { set "L0_home" "Y"; set "skipinbox" "Y"; }'
MOVE = LABEL + '\nset "stop" "Y";'
FINANCE = '# Finance\nif address :is "from" "a@b.c" { fileinto "INBOX.X"; stop; }\n'


def build(fragments, ui=""):
    return build_rules(fragments, FASTMAIL_REQUIRE + ui, DOCS)


class BuildTest(unittest.TestCase):
    def test_simple_rule(self):
        rule = build({"rules/middle.sieve": FINANCE})[0]
        self.assertEqual(
            (rule.number, rule.source, rule.title), (1, "middle", "Finance")
        )
        self.assertEqual(rule.cond, ("leaf", "from is a@b.c"))
        self.assertEqual([a.kind for a in rule.actions], ["move", "stop"])

    def test_stop_guard_is_hoisted(self):
        text = (
            'if allof(not string :is "${stop}" "Y", address :is "from" "a@b.c") '
            '{ fileinto "X"; }\n'
        )
        self.assertEqual(
            build({"rules/middle.sieve": text})[0].cond, ("leaf", "from is a@b.c")
        )

    def test_spam_guard_is_kept_and_nested_rules_are_flattened(self):
        text = (
            "# Filing (skipped for spam)\n"
            'if not string :is "${spam}" "Y" {\n'
            '  if address :domain "from" "x.io" { fileinto "A"; stop; }\n'
            '  if address :domain "from" "y.io" { fileinto "B"; stop; }\n}\n'
        )
        rules = build({"rules/middle.sieve": text})
        self.assertEqual([r.title for r in rules], ["Filing → A", "Filing → B"])
        self.assertEqual(
            rules[0].cond,
            (
                "all",
                [
                    ("leaf", "Fastmail does not consider the message spam"),
                    ("leaf", "from domain is x.io"),
                ],
            ),
        )

    def test_ui_rule_is_one_rule_with_the_guard_inlined(self):
        rule = build({}, ui_rule("a@b.c", MOVE))[0]
        self.assertEqual(rule.source, "ui")
        self.assertEqual(rule.title, "from:a@b.c")
        self.assertEqual([a.kind for a in rule.actions], ["move", "skipinbox", "stop"])

    def test_copy_without_stop_is_a_label(self):
        rule = build({}, ui_rule("a@b.c", LABEL))[0]
        self.assertEqual([a.kind for a in rule.actions], ["label", "skipinbox"])

    def test_numbered_in_execution_order(self):
        fragments = {
            "rules/top.sieve": "if true { discard; }\n",
            "rules/middle.sieve": FINANCE,
            "rules/bottom.sieve": "if true { keep; }\n",
        }
        rules = build(fragments, ui_rule("x@y.z", LABEL))
        self.assertEqual(
            [(r.number, r.source) for r in rules],
            [(1, "top"), (2, "middle"), (3, "ui"), (4, "bottom")],
        )

    def test_syntax_error_names_the_fragment(self):
        with self.assertRaisesRegex(ValueError, "middle.sieve"):
            build({"rules/middle.sieve": "if true { stop;\n"})


class WarningTest(unittest.TestCase):
    def test_overlap_where_your_rule_stops(self):
        rules = build({"rules/middle.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        mine, ui = rules
        self.assertTrue(
            any("never applies" in w and "rule 2" in w for w in mine.warnings)
        )
        self.assertTrue(any("stops it first" in w for w in ui.warnings))

    def test_overlap_where_both_apply(self):
        custom = 'if address :domain "from" "b.c" { fileinto :copy "INBOX.X"; }\n'
        rules = build({"rules/middle.sieve": custom}, ui_rule("a@b.c", LABEL))
        self.assertTrue(any("both apply" in w for w in rules[0].warnings))

    def test_bottom_rule_runs_after_the_ui_rule(self):
        rules = build({"rules/bottom.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        ui = rules[0]
        self.assertTrue(any("runs after" in w for w in ui.warnings))

    def test_a_pin_only_rule_does_not_overlap_a_filing_ui_rule(self):
        pin_only = 'if address :is "from" "a@b.c" { addflag "\\\\Flagged"; }\n'
        rules = build({"rules/middle.sieve": pin_only}, ui_rule("a@b.c", MOVE))
        self.assertEqual([r.warnings for r in rules], [[], []])
        self.assertEqual([r.issues for r in rules], [[], []])

    def test_a_filing_rule_still_overlaps_a_pin_only_ui_rule_check_is_symmetric(self):
        ui_pin_only = ui_rule("a@b.c", 'set "flagged" "Y";')
        rules = build({"rules/middle.sieve": FINANCE}, ui_pin_only)
        self.assertEqual([r.warnings for r in rules], [[], []])

    def test_identical_ui_rules_are_duplicates(self):
        rules = build({}, ui_rule("a@b.c", LABEL) + ui_rule("a@b.c", LABEL))
        self.assertEqual(rules[0].warnings, [])
        self.assertTrue(any("duplicate of rule 1" in w for w in rules[1].warnings))

    def test_same_search_different_actions(self):
        rules = build({}, ui_rule("a@b.c", LABEL) + ui_rule("A@B.c", MOVE))
        self.assertTrue(
            any(
                "same search as rule 1 but different actions" in w
                for w in rules[1].warnings
            )
        )

    def test_distinct_searches_have_no_warnings(self):
        rules = build({}, ui_rule("a@b.c", LABEL) + ui_rule("x@y.z", LABEL))
        self.assertEqual([r.warnings for r in rules], [[], []])


DISABLED = (
    '# Search: "from:old@x.y"\n'
    '# if jmapquery text:\n# {\n#    "from": "old@x.y"\n# }\n# .\n# {\n'
    '#   set "L1_old" "Y";\n# }\n'
)


class DisabledUiRuleTest(unittest.TestCase):
    def test_the_next_rule_keeps_its_own_title(self):
        rules = build({}, DISABLED + ui_rule("a@b.c", LABEL))
        self.assertEqual([r.title for r in rules], ["from:a@b.c"])

    def test_disabled_rules_are_listed(self):
        text = FASTMAIL_REQUIRE + DISABLED + ui_rule("a@b.c", LABEL)
        self.assertEqual(disabled_ui_rules(text), ["from:old@x.y"])

    def test_a_trailing_disabled_rule_is_not_mistaken_for_a_rule(self):
        text = FASTMAIL_REQUIRE + ui_rule("a@b.c", LABEL) + DISABLED + "# done\nstop;\n"
        self.assertEqual(disabled_ui_rules(text), ["from:old@x.y"])
        self.assertEqual([r.title for r in build_rules({}, text, DOCS)], ["from:a@b.c"])

    def test_render_lists_disabled_rules_after_the_ui_table(self):
        rules = build({}, ui_rule("a@b.c", LABEL))
        text = render(rules, disabled=["from:old@x.y"])
        self.assertIn("⏸ Disabled in Fastmail: from:old@x.y", text)
        self.assertLess(text.index("from:a@b.c"), text.index("⏸"))


START = "#### Managed by Sieve Sync Start ####\n"
END = "#### Managed by Sieve Sync End ####\n"


def assembled(generated_before="", top="", middle="", between="", bottom="", after=""):
    return (
        FASTMAIL_REQUIRE
        + generated_before
        + START
        + top
        + END
        + between
        + START
        + middle
        + END
        + between
        + START
        + bottom
        + END
        + after
    )


NEW_START = "#### Managed by fastmail-sieve: start ####\n"
NEW_END = "#### Managed by fastmail-sieve: end ####\n"


def assembled_new(top="", middle="", bottom=""):
    return (
        FASTMAIL_REQUIRE
        + NEW_START
        + top
        + NEW_END
        + NEW_START
        + middle
        + NEW_END
        + NEW_START
        + bottom
        + NEW_END
    )


GENERATED = (
    '### Sieve generated for spam protection {{{\nif header :is "x" "y" { discard; }\n'
)
LATER = '# Calculate rule actions\nif header :is "p" "q" { keep; }\n'


class NewMarkersFullScriptTest(unittest.TestCase):
    def test_the_new_markers_delimit_your_blocks_like_the_old_ones(self):
        rules = build_full_rules(
            assembled_new(
                top='if header :is "a" "b" { keep; }\n',
                bottom='if header :is "c" "d" { keep; }\n',
            )
        )
        self.assertEqual([rule.source for rule in rules], ["top", "bottom"])


class FullScriptTest(unittest.TestCase):
    def full(self, text):
        return build_full_rules(text, DOCS)

    def test_rules_are_tagged_by_origin_in_execution_order(self):
        text = assembled(
            generated_before=GENERATED,
            top='# Mine top\nif header :is "a" "b" { stop; }\n',
            middle=FINANCE,
            between=ui_rule("u@v.w", LABEL),
            bottom='# Mine bottom\nif header :is "c" "d" { stop; }\n',
            after=LATER,
        )
        self.assertEqual(
            [(r.number, r.source) for r in self.full(text)],
            [
                (1, "fastmail"),
                (2, "top"),
                (3, "ui"),
                (4, "middle"),
                (5, "ui"),
                (6, "bottom"),
                (7, "fastmail"),
            ],
        )

    def test_generated_rules_without_a_comment_inherit_the_last_heading(self):
        text = assembled(
            generated_before=GENERATED + 'if header :is "x2" "y2" { discard; }\n'
        )
        titles = [r.title for r in self.full(text)]
        self.assertEqual(titles, ["Sieve generated for spam protection"] * 2)

    def test_empty_blocks_do_not_confuse_the_origin_tracking(self):
        rules = self.full(assembled(middle=FINANCE, after=LATER))
        self.assertEqual([r.source for r in rules], ["middle", "fastmail"])

    def test_sections_follow_execution_order_and_name_each_origin(self):
        text = assembled(generated_before=GENERATED, middle=FINANCE, after=LATER)
        out = render(self.full(text), sequence=True)
        positions = [
            out.index("FASTMAIL GENERATED"),
            out.index("YOUR RULES (middle)"),
            out.rindex("FASTMAIL GENERATED"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertGreater(positions[2], positions[0])

    def test_generated_rules_are_dimmed_and_yours_are_not(self):
        text = assembled(generated_before=GENERATED, middle=FINANCE)
        rules = self.full(text)
        coloured = render(rules, sequence=True, color=True)
        plain = render(rules, sequence=True)
        self.assertNotIn("\x1b[", plain)
        generated_line = next(
            line for line in coloured.splitlines() if "Sieve generated for spam" in line
        )
        yours_line = next(
            line for line in coloured.splitlines() if "Finance" in line and "│" in line
        )
        self.assertIn("\x1b[2m", generated_line)
        self.assertNotIn("\x1b[2m", yours_line.split("Finance")[0].split("│")[-1])


class BuilderRegressionTest(unittest.TestCase):
    def rules(self, text):
        return build({"rules/middle.sieve": text})

    def test_actions_before_a_nested_rule_are_not_repeated(self):
        text = 'if header :is "a" "b" {\nset "x" "Y";\nif header :is "c" "d" { stop; }\nset "z" "Y";\n}\n'
        rules = self.rules(text)
        self.assertEqual(len(rules), 3)
        self.assertEqual(
            [[a.text for a in r.actions] for r in rules][0], ["set ${x} to Y"]
        )
        self.assertEqual(
            [[a.text for a in r.actions] for r in rules][2], ["set ${z} to Y"]
        )

    def test_nested_otherwise_collapses_to_one_condition(self):
        text = 'if header :is "a" "b" { stop; } else { if header :is "c" "d" { discard; } else { keep; } }\n'
        rules = self.rules(text)
        keep = next(
            r for r in rules if any(a.text.startswith("keep") for a in r.actions)
        )
        self.assertEqual(keep.cond, ("leaf", "otherwise"))


class TitleTest(unittest.TestCase):
    def titles(self, text):
        return [r.title for r in build({"rules/middle.sieve": text})]

    def nested(self, inner):
        return f'# Folder filing\nif not string :is "${{spam}}" "Y" {{\n{inner}\n}}\n'

    def test_a_nested_pin_only_rule_is_titled_pinning(self):
        text = self.nested('if address :is "from" "a@b.c" { addflag "\\\\Flagged"; }')
        self.assertEqual(self.titles(text), ["Pinning"])

    def test_a_nested_rule_that_files_keeps_the_heading_and_folder(self):
        text = self.nested(
            'if address :is "from" "a@b.c" { addflag "\\\\Flagged"; fileinto "INBOX.X"; stop; }'
        )
        self.assertEqual(self.titles(text), ["Folder filing → X"])

    def test_a_nested_trash_rule_is_titled_trash(self):
        text = self.nested(
            'if address :is "from" "a@b.c" { fileinto :specialuse "\\\\Trash" "INBOX.Trash"; }'
        )
        self.assertEqual(self.titles(text), ["Trash"])

    def test_an_uncommented_pin_only_rule_is_titled_pinning(self):
        text = 'if address :is "from" "a@b.c" { addflag "\\\\Flagged"; }\n'
        self.assertEqual(self.titles(text), ["Pinning"])

    def test_your_own_comment_still_wins_on_a_top_level_rule(self):
        text = '# Amazon returns\nif address :is "from" "a@b.c" { addflag "\\\\Flagged"; }\n'
        self.assertEqual(self.titles(text), ["Amazon returns"])


class ConditionLinesTest(unittest.TestCase):
    def test_a_negated_group_indents_its_members_once(self):
        node = (
            "all",
            [("leaf", "x"), ("not", ("any", [("leaf", "a"), ("leaf", "b")]))],
        )
        self.assertEqual(_lines(node), ["x", "AND NOT any of:", "    a", "    OR b"])

    def test_a_negated_leaf_stays_on_one_line(self):
        self.assertEqual(_lines(("not", ("leaf", "x"))), ["NOT x"])


class WordingTest(unittest.TestCase):
    def render_for(self, text, docs=DOCS):
        return render(build_rules({"rules/middle.sieve": text}, FASTMAIL_REQUIRE, docs))

    def test_variables_read_as_their_meaning(self):
        docs = {**DOCS, "status": {"label": "the conversation status"}}
        text = 'if string :is "${status}" "followed" { set "status" "muted"; }\n'
        out = self.render_for(text, docs)
        self.assertIn("the conversation status is followed", out)
        self.assertIn("set the conversation status to muted", out)

    def test_undocumented_variables_keep_their_raw_form(self):
        out = self.render_for('if string :is "${mystery}" "Y" { stop; }\n')
        self.assertIn("${mystery} is Y", out)

    def test_folder_flags_are_worded_without_docs_entries(self):
        out = self.render_for('if true { set "L0_home" "Y"; }\n')
        self.assertIn("🔖 label: copy into the home folder", out)

    def test_or_searches_and_numeric_comparisons(self):
        out = self.render_for(
            'if anyof(jmapquery text:\n{"conditions": [{"from": "a@x"}, {"from": "b@x"}], "operator": "OR"}\n.\n,'
            ' header :comparator "i;ascii-numeric" :value "ge" "X-Spam-score" "5") { stop; }\n'
        )
        self.assertIn("from: a@x or from: b@x", out)
        self.assertIn("header X-Spam-score >= 5 (numeric)", out)

    def test_trash_and_junk_markers_and_pins(self):
        out = self.render_for(
            'if true { fileinto :specialuse "\\\\Trash" "INBOX.Trash";'
            ' fileinto :specialuse "\\\\Junk" "INBOX.Spam"; addflag "\\\\Flagged"; }\n'
        )
        self.assertIn("🚮 file into INBOX.Trash", out)
        self.assertIn("🚫 file into INBOX.Spam", out)
        self.assertIn("📌 pin (flag) the message", out)


class AlignmentTest(unittest.TestCase):
    def test_rendered_tables_contain_no_variation_selectors(self):
        custom = 'if address :is "from" "a@b.c" { fileinto :mailboxid "Pik" "INBOX.⌨\ufe0f code"; stop; }\n'
        text = render(build({"rules/middle.sieve": custom}, ui_rule("a@b.c", LABEL)))
        self.assertNotIn("\ufe0f", text)
        self.assertIn("⌨ code", text)

    def test_every_table_line_has_the_same_display_width(self):
        import unicodedata

        def width(line):
            return sum(
                0
                if unicodedata.combining(c)
                else 2
                if unicodedata.east_asian_width(c) in "WF"
                else 1
                for c in line
            )

        custom = (
            'if address :is "from" "a@b.c" { addflag "\\\\Flagged"; fileinto :mailboxid "Pik" "INBOX.⌨\ufe0f code";'
            ' fileinto :specialuse "\\\\Trash" "INBOX.Trash"; stop; }\n'
        )
        text = render(build({"rules/middle.sieve": custom}, ui_rule("a@b.c", LABEL)))
        self.assertTrue(any(line.startswith("╭") for line in text.splitlines()))
        by_table = {}
        current = []
        for line in text.splitlines():
            if line.startswith("╭"):
                current = []
            if line and line[0] in "╭│├╰":
                current.append(width(line))
            if line.startswith("╰"):
                by_table[len(by_table)] = current
        for widths in by_table.values():
            self.assertEqual(len(set(widths)), 1, widths)


def styled_parts(padding):
    text = padding.renderable
    return [(text.plain[span.start : span.end], str(span.style)) for span in text.spans]


class ValueEmphasisTest(unittest.TestCase):
    def test_values_are_not_dimmed_but_the_wording_is(self):
        parts = styled_parts(
            _condition_line("from domain is aspiriant.com", False, ["aspiriant.com"])
        )
        self.assertIn(("from domain is ", "dim"), parts)
        self.assertIn(("aspiriant.com", "bold"), parts)

    def test_every_value_in_a_list_is_emphasised(self):
        parts = styled_parts(
            _condition_line("from is a@b.c or d@e.f", False, ["a@b.c", "d@e.f"])
        )
        self.assertEqual(
            [p for p in parts if p[1] == "bold"], [("a@b.c", "bold"), ("d@e.f", "bold")]
        )

    def test_keywords_stay_yellow_and_the_rest_follows(self):
        parts = styled_parts(
            _condition_line("AND header subject matches Hello", False, ["Hello"])
        )
        self.assertEqual(parts[0], ("AND", "yellow"))
        self.assertIn(("Hello", "bold"), parts)

    def test_longer_values_win_over_their_own_substrings(self):
        parts = styled_parts(
            _condition_line("from is info@a.com", False, ["a.com", "info@a.com"])
        )
        self.assertIn(("info@a.com", "bold"), parts)

    def test_values_are_matched_as_whole_tokens(self):
        parts = styled_parts(
            _condition_line("header X-Spam-score >= 5 (numeric)", False, ["5"])
        )
        self.assertEqual([p for p in parts if p[1] == "bold"], [("5", "bold")])
        parts = styled_parts(_condition_line("from is a5@b.c", False, ["5"]))
        self.assertEqual([p for p in parts if p[1] == "bold"], [])

    def test_fastmail_generated_rules_stay_fully_dim(self):
        parts = styled_parts(
            _condition_line("from domain is aspiriant.com", True, ["aspiriant.com"])
        )
        self.assertEqual({style for _, style in parts}, {"dim"})

    def test_rules_collect_the_values_they_test(self):
        custom = (
            'if address :domain "from" ["aspiriant.com", "x.io"] { fileinto "A"; }\n'
        )
        rule = build({"rules/middle.sieve": custom})[0]
        self.assertEqual(sorted(rule.values), ["aspiriant.com", "x.io"])

    def test_variable_phrases_have_no_emphasised_values(self):
        text = 'if not string :is "${spam}" "Y" { stop; }\n'
        self.assertEqual(build({"rules/middle.sieve": text})[0].values, [])

    def test_search_values_are_collected_in_their_original_case(self):
        rule = build({}, ui_rule("Info@Example.com", LABEL))[0]
        self.assertEqual(rule.values, ["Info@Example.com"])


def ui_search_rule(query_json, body, title="Contact"):
    return f'# Search: "{title}"\nif jmapquery text:\n{query_json}\n.\n{{\n{body}\n}}\n'


COPY_HOME = 'fileinto :copy :mailboxid "P-xSc" "INBOX.home";'


def custom_search_rule(query, body=COPY_HOME):
    escaped = query.replace('"', '\\"')
    return f'if jmapquery "{escaped}" {{ {body} }}\n'


class SearchOverlapTest(unittest.TestCase):
    CONTACT = '{ "fromContactCardUid": "abc-123" }'
    COMPACT = '{"fromContactCardUid":"abc-123"}'

    def test_a_custom_jmapquery_rule_overlaps_a_ui_rule_with_the_same_search(self):
        rules = build(
            {"rules/middle.sieve": custom_search_rule(self.COMPACT)},
            ui_search_rule(self.CONTACT, LABEL),
        )
        issues = [issue for rule in rules for issue in rule.issues]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0][0], "overlap")
        self.assertIn("the same search (fromContactCardUid: abc-123)", issues[0][1])
        self.assertTrue(issues[0][1].endswith("both apply"))
        self.assertTrue(any("same search" in w for w in rules[1].warnings))

    def test_whitespace_and_case_do_not_matter(self):
        rules = build(
            {
                "rules/middle.sieve": custom_search_rule(
                    '{ "fromContactCardUid" :  "ABC-123" }'
                )
            },
            ui_search_rule(self.CONTACT, LABEL),
        )
        self.assertEqual(len([i for r in rules for i in r.issues]), 1)

    def test_a_stopping_custom_rule_means_the_ui_rule_never_applies(self):
        body = COPY_HOME + " stop;"
        rules = build(
            {"rules/middle.sieve": custom_search_rule(self.COMPACT, body)},
            ui_search_rule(self.CONTACT, LABEL),
        )
        issue = rules[0].issues[0][1]
        self.assertTrue(issue.endswith("rule 2 never applies"), issue)

    def test_different_searches_do_not_overlap(self):
        other = '{"fromContactCardUid":"zzz"}'
        rules = build(
            {"rules/middle.sieve": custom_search_rule(other)},
            ui_search_rule(self.CONTACT, LABEL),
        )
        self.assertEqual([r.issues for r in rules], [[], []])

    def test_sender_overlaps_still_work(self):
        rules = build({"rules/middle.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        self.assertIn("on a@b.c", rules[0].issues[0][1])


class RenderTest(unittest.TestCase):
    def text(self, fragments, ui="", **options):
        return render(build(fragments, ui), **options)

    def test_rules_table_has_id_source_and_details_columns(self):
        text = self.text({"rules/middle.sieve": FINANCE}, ui_rule("x@y.z", LABEL))
        rules = text[text.index("RULES") :]
        self.assertRegex(rules, r"│\s+ID\s+│\s+Source\s+│\s+Details\s+│")
        self.assertRegex(rules, r"│\s+1\s+│\s+middle\s+│\s+Finance\s+│")
        self.assertRegex(rules, r"│\s+2\s+│\s+UI\s+│\s+from:x@y\.z\s+│")

    def test_details_separate_conditions_from_actions(self):
        lines = self.text({"rules/middle.sieve": FINANCE}).splitlines()
        condition = next(
            i
            for i, line in enumerate(lines)
            if "IF" in line and "from is a@b.c" in line
        )
        action = next(
            i
            for i, line in enumerate(lines)
            if "DO" in line and "📁 file into INBOX.X" in line
        )
        self.assertLess(condition, action)
        self.assertIn("🛑 stop", lines[action + 1])

    def test_hoisted_note_and_summary_come_first(self):
        text = self.text({"rules/middle.sieve": FINANCE})
        self.assertLess(text.index("SUMMARY"), text.index("RULES"))
        self.assertIn(
            "Every rule below runs only while nothing earlier has stopped", text
        )
        self.assertRegex(text, r"a@b\.c\s+│\s+📁 X 🛑\s+│\s+1 middle")

    def test_summary_is_a_bordered_table_with_headers(self):
        text = self.text({"rules/middle.sieve": FINANCE})
        summary = text[: text.index("RULES")]
        self.assertIn("╭", summary)
        self.assertRegex(summary, r"│\s+Sender\s+│\s+Outcome\s+│\s+Rule\s+│")

    def test_summary_shows_text_that_looks_like_markup_literally(self):
        custom = 'if address :domain "from" "[red]x.io" { fileinto "A"; }\n'
        text = self.text({"rules/middle.sieve": custom})
        self.assertIn("[red]x.io", text[: text.index("RULES")])

    def test_summary_collapses_long_sender_lists(self):
        domains = ", ".join(f'"d{i}.io"' for i in range(6))
        custom = f'if address :domain "from" [{domains}] {{ fileinto "A"; }}\n'
        text = self.text({"rules/middle.sieve": custom})
        self.assertIn("d0.io, d1.io, d2.io +3 more", text)

    def test_long_lines_wrap_to_the_width(self):
        domains = ", ".join(f'"domain{i}.example.com"' for i in range(12))
        custom = f'if address :domain "from" [{domains}] {{ fileinto "A"; }}\n'
        text = self.text({"rules/middle.sieve": custom}, width=60)
        card = text[text.index("RULES") :]
        self.assertTrue(all(len(line) <= 60 for line in card.splitlines()))

    def test_warnings_appear_on_cards_and_in_the_summary(self):
        text = self.text({"rules/middle.sieve": FINANCE}, ui_rule("a@b.c", LABEL))
        self.assertRegex(text, r"│ ❗ mail from a@b\.c")
        self.assertRegex(text, r"1 middle ❗")

    def test_colour_only_adds_escape_codes(self):
        fragments = {"rules/middle.sieve": FINANCE}
        plain = self.text(fragments, ui_rule("a@b.c", LABEL))
        coloured = self.text(fragments, ui_rule("a@b.c", LABEL), color=True)
        self.assertIn("\x1b[", coloured)
        self.assertNotIn("\x1b[", plain)
        self.assertEqual(ANSI.sub("", coloured), plain)

    def test_ui_rules_are_separated_from_yours(self):
        fragments = {"rules/middle.sieve": FINANCE, "rules/bottom.sieve": FINANCE}
        text = self.text(fragments, ui_rule("x@y.z", LABEL))
        yours = text.index("YOUR RULES")
        ui = text.index("FASTMAIL UI RULES")
        after = text.index("YOUR RULES (AFTER THE UI RULES)")
        self.assertLess(yours, ui)
        self.assertLess(ui, after)
        self.assertLess(text.index("from:x@y.z"), after)

    def test_sections_are_omitted_when_empty(self):
        text = self.text({"rules/middle.sieve": FINANCE})
        self.assertNotIn("FASTMAIL UI RULES", text)
        self.assertNotIn("AFTER THE UI RULES", text)

    def test_no_rules(self):
        self.assertEqual(render([]), "No rules.")


if __name__ == "__main__":
    unittest.main()
