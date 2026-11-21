import os
import unittest
from unittest import mock

from rich.table import Table
from rich.text import Text

from fastmail_sieve.ui.tables import (
    cell,
    render_table,
    strip_variation_selectors,
    terminal_width,
    use_color,
)


def sample():
    table = Table()
    table.add_column("A")
    table.add_row(Text("[red]x", style="bold"))
    return table


class RenderTableTest(unittest.TestCase):
    def test_plain_output_has_no_escape_codes_and_shows_markup_literally(self):
        lines = render_table(sample(), 40, color=False)
        self.assertTrue(any("[red]x" in line for line in lines))
        self.assertFalse(any("\x1b[" in line for line in lines))

    def test_colour_output_adds_escape_codes(self):
        self.assertTrue(
            any("\x1b[" in line for line in render_table(sample(), 40, color=True))
        )


class VariationSelectorTest(unittest.TestCase):
    def test_strips_the_selector_but_keeps_the_character(self):
        self.assertEqual(strip_variation_selectors("a ⌨\ufe0f code"), "a ⌨ code")

    def test_cell_strips_and_styles(self):
        text = cell("x\ufe0fy", "bold")
        self.assertEqual((text.plain, str(text.style)), ("xy", "bold"))


class UseColorTest(unittest.TestCase):
    def test_choices(self):
        self.assertTrue(use_color("always"))
        self.assertFalse(use_color("never"))

    @mock.patch.dict(os.environ, {"NO_COLOR": "1"})
    def test_no_color_wins_over_auto(self):
        self.assertFalse(use_color("auto"))

    @mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True)
    def test_force_color_enables_auto(self):
        self.assertTrue(use_color("auto"))


class TerminalWidthTest(unittest.TestCase):
    def test_is_clamped(self):
        self.assertEqual(terminal_width(requested=10), 60)
        self.assertEqual(terminal_width(requested=500), 140)
        self.assertEqual(terminal_width(requested=100), 100)


if __name__ == "__main__":
    unittest.main()
