import unittest

from fastmail_sieve.fastmail.blocks import RemoteScript, get_script, set_blocks
from fastmail_sieve.sieve.script import (
    LEGACY_MARKER_END,
    LEGACY_MARKER_START,
    MARKER_END,
    MARKER_START,
    assemble,
)

CREDS = {"token": "fma1-x", "cookie": "c=1"}
MAIL = "urn:ietf:params:jmap:mail"
EMPTY = f"{MARKER_START}\n{MARKER_END}"


def block(content=""):
    return f"{MARKER_START}\n{content}{MARKER_END}"


def remote(start="", middle="", end=""):
    return RemoteScript(
        require='require ["fileinto"];',
        start=block(start),
        blocked="### blocked",
        middle=block(middle),
        rules="### rules",
        end=block(end),
    )


JSON = {
    "id": "singleton",
    "sieveRequire": "R",
    "sieveAtStart": EMPTY,
    "sieveForBlocked": "B",
    "sieveAtMiddle": EMPTY,
    "sieveForRules": "U",
    "sieveAtEnd": EMPTY,
}


class RemoteScriptTest(unittest.TestCase):
    def test_text_joins_the_six_parts_with_newlines(self):
        script = RemoteScript.from_json(JSON)
        self.assertEqual(script.text, "\n".join(["R", EMPTY, "B", EMPTY, "U", EMPTY]))

    def test_fragments_are_what_sits_between_the_markers(self):
        script = remote("stop;\nkeep;\n", "", "discard;\n")
        self.assertEqual(script.fragments, ("stop;\nkeep;\n", "", "discard;\n"))

    def test_with_fragments_replaces_only_the_managed_blocks(self):
        updated = remote().with_fragments("a;\n", "b;\n", "c;\n")
        self.assertEqual(updated.fragments, ("a;\n", "b;\n", "c;\n"))
        self.assertEqual(
            (updated.require, updated.blocked, updated.rules),
            ('require ["fileinto"];', "### blocked", "### rules"),
        )

    def test_a_fragment_without_a_trailing_newline_keeps_the_marker_on_its_own_line(
        self,
    ):
        updated = remote().with_fragments("a;", "", "")
        self.assertEqual(updated.start, f"{MARKER_START}\na;\n{MARKER_END}")

    def test_empty_fragments_give_empty_blocks(self):
        self.assertEqual(remote("x;\n").with_fragments("", "", "").start, EMPTY)

    def test_text_outside_the_markers_in_a_block_is_kept(self):
        old, new = block("x;\n"), block("y;\n")
        script = RemoteScript("R", f"# before\n{old}\n# after", "B", EMPTY, "U", EMPTY)
        updated = script.with_fragments("y;\n", "", "")
        self.assertEqual(updated.start, f"# before\n{new}\n# after")

    def test_same_blocks_ignores_the_parts_you_cannot_edit(self):
        one, other = remote("a;\n"), remote("a;\n")
        self.assertTrue(one.same_blocks(other))
        self.assertFalse(one.same_blocks(remote("b;\n")))

    def test_the_text_matches_assembling_into_the_remote_text(self):
        for fragments in (("a;\n", "b;\n", "c;\n"), ("a;", "", "c;\n\n"), ("", "", "")):
            base = remote("old;\n", "old;\n", "old;\n")
            self.assertEqual(
                base.with_fragments(*fragments).text,
                assemble(base.text, *fragments),
                fragments,
            )


def old_block(content=""):
    return f"{LEGACY_MARKER_START}\n{content}{LEGACY_MARKER_END}"


class MarkerStylesTest(unittest.TestCase):
    def legacy(self, start="a;\n", middle="b;\n", end="c;\n"):
        return RemoteScript(
            "R", old_block(start), "B", old_block(middle), "U", old_block(end)
        )

    def test_a_script_with_the_old_markers_has_managed_blocks(self):
        script = self.legacy()
        self.assertTrue(script.has_markers)
        self.assertEqual(script.fragments, ("a;\n", "b;\n", "c;\n"))

    def test_with_fragments_keeps_the_old_markers(self):
        updated = self.legacy().with_fragments("x;\n", "y;\n", "z;\n")
        self.assertEqual(updated.start, old_block("x;\n"))
        self.assertNotIn(MARKER_START, updated.text)

    def test_with_fragments_keeps_each_blocks_own_style(self):
        script = RemoteScript(
            "R", old_block("a;\n"), "B", block("b;\n"), "U", old_block()
        )
        updated = script.with_fragments("1;\n", "2;\n", "3;\n")
        self.assertEqual(
            (updated.start, updated.middle, updated.end),
            (old_block("1;\n"), block("2;\n"), old_block("3;\n")),
        )

    def test_with_markers_leaves_old_blocks_alone_and_adds_the_new_style_elsewhere(
        self,
    ):
        script = RemoteScript("R", old_block("a;\n"), "B", "# code", "U", "")
        marked = script.with_markers()
        self.assertEqual(marked.start, script.start)
        self.assertEqual(marked.middle, f"# code\n{MARKER_START}\n{MARKER_END}")
        self.assertEqual(marked.end, f"{MARKER_START}\n{MARKER_END}")

    def test_a_lone_marker_is_not_a_managed_block(self):
        script = RemoteScript(
            "R", f"{MARKER_START}\nx;\n", "B", old_block(), "U", old_block()
        )
        self.assertFalse(script.has_markers)
        with self.assertRaisesRegex(RuntimeError, "no managed blocks"):
            _ = script.fragments

    def test_a_marker_of_one_style_does_not_pair_with_the_other(self):
        crossed = f"{LEGACY_MARKER_START}\nx;\n{MARKER_END}"
        script = RemoteScript("R", crossed, "B", old_block(), "U", old_block())
        self.assertFalse(script.has_markers)


class ConvertMarkersTest(unittest.TestCase):
    def legacy(self):
        return RemoteScript(
            "R", old_block("a;\n"), "B", old_block("b;\n"), "U", old_block()
        )

    def test_old_markers_become_the_new_ones_and_everything_else_is_kept(self):
        script = self.legacy()
        converted = script.convert_markers()
        self.assertEqual(
            (converted.start, converted.middle, converted.end),
            (block("a;\n"), block("b;\n"), block()),
        )
        self.assertEqual(converted.fragments, script.fragments)
        self.assertEqual(
            (converted.require, converted.blocked, converted.rules), ("R", "B", "U")
        )

    def test_text_around_the_markers_is_kept(self):
        old, new = old_block("x;\n"), block("x;\n")
        script = RemoteScript(
            "R", f"# before\n{old}\n# after", "B", old_block(), "U", old_block()
        )
        self.assertEqual(script.convert_markers().start, f"# before\n{new}\n# after")

    def test_a_mixed_script_ends_up_entirely_in_the_new_style(self):
        script = RemoteScript(
            "R", old_block("a;\n"), "B", block("b;\n"), "U", old_block()
        )
        self.assertFalse(script.convert_markers().uses_legacy_markers)

    def test_new_style_and_unmanaged_blocks_are_left_alone(self):
        marked = RemoteScript("R", block("a;\n"), "B", block(), "U", block())
        self.assertEqual(marked.convert_markers(), marked)
        bare = RemoteScript("R", "# code", "B", "", "U", "")
        self.assertEqual(bare.convert_markers(), bare)

    def test_converting_twice_changes_nothing_more(self):
        once = self.legacy().convert_markers()
        self.assertEqual(once.convert_markers(), once)

    def test_uses_legacy_markers_tells_the_styles_apart(self):
        self.assertTrue(self.legacy().uses_legacy_markers)
        self.assertFalse(remote().uses_legacy_markers)
        self.assertFalse(RemoteScript("R", "", "B", "", "U", "").uses_legacy_markers)

    def test_only_one_block_in_the_old_style_still_counts(self):
        script = RemoteScript("R", old_block(), "B", block(), "U", block())
        self.assertTrue(script.uses_legacy_markers)


class ManagedBlocksTest(unittest.TestCase):
    BARE = RemoteScript("R", "# my start code", "B", "", "U", "")

    def test_a_script_with_markers_in_all_three_blocks_has_them(self):
        self.assertTrue(remote().has_markers)

    def test_a_script_without_markers_does_not(self):
        self.assertFalse(self.BARE.has_markers)
        self.assertFalse(
            remote().__class__("R", block(), "B", "", "U", block()).has_markers
        )

    def test_with_markers_adds_empty_blocks_and_keeps_existing_code(self):
        marked = self.BARE.with_markers()
        self.assertTrue(marked.has_markers)
        self.assertEqual(marked.start, f"# my start code\n{MARKER_START}\n{MARKER_END}")
        self.assertEqual(marked.middle, EMPTY)
        self.assertEqual(marked.fragments, ("", "", ""))

    def test_with_markers_leaves_a_marked_script_alone(self):
        script = remote("x;\n", "y;\n", "z;\n")
        self.assertEqual(script.with_markers(), script)

    def test_reading_or_writing_fragments_without_markers_explains_the_fix(self):
        with self.assertRaisesRegex(RuntimeError, r"no managed blocks.*init --remote"):
            _ = self.BARE.fragments
        with self.assertRaisesRegex(RuntimeError, r"no managed blocks.*init --remote"):
            self.BARE.with_fragments("", "", "")


class SessionThen:
    """A fake JMAP call: the session on GET, then `reply`; records each body."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, url, credentials, body=None):
        self.calls.append(body)
        if body is None:
            return {
                "apiUrl": "https://api.example/jmap",
                "primaryAccounts": {MAIL: "u1"},
            }
        return self.reply


def session_then(reply):
    return SessionThen(reply)


class GetScriptTest(unittest.TestCase):
    def test_reads_the_singleton_with_the_rules_capabilities(self):
        call = session_then(
            {"methodResponses": [["SieveBlocks/get", {"list": [JSON]}, "0"]]}
        )
        script = get_script(CREDS, call)
        self.assertEqual(script.text, RemoteScript.from_json(JSON).text)
        body = call.calls[1]
        self.assertEqual(
            body["using"],
            ["https://www.fastmail.com/dev/rules", "https://www.fastmail.com/dev/user"],
        )
        self.assertEqual(
            body["methodCalls"],
            [["SieveBlocks/get", {"accountId": "u1", "ids": ["singleton"]}, "0"]],
        )

    def test_no_script_is_an_error(self):
        call = session_then(
            {"methodResponses": [["SieveBlocks/get", {"list": []}, "0"]]}
        )
        with self.assertRaisesRegex(RuntimeError, "no Sieve script"):
            get_script(CREDS, call)


class SetBlocksTest(unittest.TestCase):
    def test_sends_only_the_three_managed_blocks(self):
        call = session_then(
            {
                "methodResponses": [
                    ["SieveBlocks/set", {"updated": {"singleton": None}}, "0"]
                ]
            }
        )
        set_blocks(CREDS, remote("a;\n", "b;\n", "c;\n"), call)
        [name, arguments, _] = call.calls[1]["methodCalls"][0]
        self.assertEqual(name, "SieveBlocks/set")
        self.assertEqual(
            arguments["update"]["singleton"],
            {
                "sieveAtStart": block("a;\n"),
                "sieveAtMiddle": block("b;\n"),
                "sieveAtEnd": block("c;\n"),
            },
        )
        self.assertEqual(arguments["accountId"], "u1")

    def test_a_refused_update_is_an_error(self):
        reply = {
            "methodResponses": [
                [
                    "SieveBlocks/set",
                    {"notUpdated": {"singleton": {"type": "invalidProperties"}}},
                    "0",
                ]
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "refused.*invalidProperties"):
            set_blocks(CREDS, remote(), session_then(reply))


if __name__ == "__main__":
    unittest.main()
