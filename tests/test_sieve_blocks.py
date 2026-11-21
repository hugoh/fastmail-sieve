import unittest

from fastmail_sieve.sieve.script import (
    LEGACY_MARKER_END,
    LEGACY_MARKER_START,
    MARKER_END,
    MARKER_START,
    assemble,
    split,
)

PAIR = f"{MARKER_START}\n{MARKER_END}"


def skeleton(top="", middle="", bottom=""):
    def block(content):
        return f"{MARKER_START}\n{content}{MARKER_END}"

    return (
        f"require [];\n{block(top)}\n### blocked {{{{{{\n{block(middle)}\n"
        f"### rules {{{{{{\n{block(bottom)}"
    )


class SplitTest(unittest.TestCase):
    def test_empty_blocks(self):
        self.assertEqual(split(skeleton()), ("", "", ""))

    def test_extracts_each_block(self):
        text = skeleton("stop;\n", 'set "a" "Y";\nstop;\n', "discard;\n")
        self.assertEqual(
            split(text), ("stop;\n", 'set "a" "Y";\nstop;\n', "discard;\n")
        )

    def test_requires_three_pairs(self):
        with self.assertRaises(ValueError):
            split(f"require [];\n{PAIR}\n{PAIR}")


class AssembleTest(unittest.TestCase):
    def test_roundtrip_is_identity(self):
        text = skeleton("stop;\n", "keep;\n", "")
        self.assertEqual(assemble(text, *split(text)), text)

    def test_replaces_only_managed_blocks(self):
        base = skeleton()
        built = assemble(base, "a;\n", "b;\n", "c;\n")
        self.assertEqual(built, skeleton("a;\n", "b;\n", "c;\n"))

    def test_replaces_previous_content(self):
        base = skeleton("old;\n", "old;\n", "old;\n")
        self.assertEqual(split(assemble(base, "", "x;\n", "")), ("", "x;\n", ""))

    def test_rejects_fragment_containing_marker(self):
        with self.assertRaises(ValueError):
            assemble(skeleton(), f"{MARKER_START}\n", "", "")


def legacy_skeleton(top="", middle="", bottom=""):
    def block(content):
        return f"{LEGACY_MARKER_START}\n{content}{LEGACY_MARKER_END}"

    return f"require [];\n{block(top)}\n### blocked\n{block(middle)}\n### rules\n{block(bottom)}"


class MarkerStylesTest(unittest.TestCase):
    def test_the_new_markers_name_this_tool(self):
        self.assertEqual(MARKER_START, "#### Managed by fastmail-sieve: start ####")
        self.assertEqual(MARKER_END, "#### Managed by fastmail-sieve: end ####")

    def test_the_old_markers_are_still_what_sieve_sync_wrote(self):
        self.assertEqual(LEGACY_MARKER_START, "#### Managed by Sieve Sync Start ####")
        self.assertEqual(LEGACY_MARKER_END, "#### Managed by Sieve Sync End ####")

    def test_split_reads_a_script_with_the_old_markers(self):
        text = legacy_skeleton("a;\n", "b;\n", "c;\n")
        self.assertEqual(split(text), ("a;\n", "b;\n", "c;\n"))

    def test_assemble_keeps_the_markers_it_finds(self):
        built = assemble(legacy_skeleton(), "a;\n", "b;\n", "c;\n")
        self.assertEqual(built, legacy_skeleton("a;\n", "b;\n", "c;\n"))
        self.assertNotIn(MARKER_START, built)

    def test_a_script_can_mix_the_styles_block_by_block(self):
        text = (
            f"require [];\n{LEGACY_MARKER_START}\nold;\n{LEGACY_MARKER_END}\n### b\n"
            f"{MARKER_START}\nnew;\n{MARKER_END}\n### r\n{LEGACY_MARKER_START}\n{LEGACY_MARKER_END}"
        )
        self.assertEqual(split(text), ("old;\n", "new;\n", ""))
        built = assemble(text, "A;\n", "B;\n", "C;\n")
        self.assertEqual(split(built), ("A;\n", "B;\n", "C;\n"))
        self.assertEqual(
            [MARKER_START in built, LEGACY_MARKER_START in built], [True, True]
        )

    def test_a_fragment_may_not_contain_either_style(self):
        for marker in (MARKER_START, LEGACY_MARKER_END):
            with self.assertRaisesRegex(ValueError, "managed-block markers"):
                assemble(skeleton(), "", f"x\n{marker}\n", "")


if __name__ == "__main__":
    unittest.main()
