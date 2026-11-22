import contextlib
import io
import os
import unittest
from unittest import mock

from rich.table import Table
from rich.text import Text

from fastmail_sieve.ui.tables import (
    cell,
    echo,
    make_console,
    render_table,
    safe_text,
    strip_variation_selectors,
    styled,
)


def sample():
    table = Table()
    table.add_column("A")
    table.add_row(Text("[red]x", style="bold"))
    return table


class RenderTableTest(unittest.TestCase):
    def test_plain_output_has_no_escape_codes_and_shows_markup_literally(self):
        lines = render_table(sample(), make_console("never", 40))
        self.assertTrue(any("[red]x" in line for line in lines))
        self.assertFalse(any("\x1b[" in line for line in lines))

    def test_colour_output_adds_escape_codes(self):
        self.assertTrue(
            any(
                "\x1b[" in line
                for line in render_table(sample(), make_console("always", 40))
            )
        )


class VariationSelectorTest(unittest.TestCase):
    def test_strips_the_selector_but_keeps_the_character(self):
        self.assertEqual(strip_variation_selectors("a ⌨\ufe0f code"), "a ⌨ code")

    def test_cell_strips_and_styles(self):
        text = cell("x\ufe0fy", "bold")
        self.assertEqual((text.plain, str(text.style)), ("xy", "bold"))


class SafeTextTest(unittest.TestCase):
    """Text from Fastmail is shown on a terminal: it must not be able to drive it."""

    def test_escape_sequences_and_other_control_characters_are_removed(self):
        self.assertEqual(safe_text("a\x1b[31mb\x07\x08c\x00d\x7fe\x9bf"), "a[31mbcdef")

    def test_newlines_and_tabs_survive(self):
        self.assertEqual(safe_text("a\n\tb\r\n"), "a\n\tb\n")

    def test_the_variation_selector_goes_too(self):
        self.assertEqual(safe_text("⌨\ufe0f"), "⌨")

    def test_a_cell_is_safe(self):
        self.assertEqual(cell("x\x1b]0;title\x07y").plain, "x]0;titley")


class MakeConsoleTest(unittest.TestCase):
    def test_choices(self):
        self.assertIsNotNone(make_console("always").color_system)
        self.assertIsNone(make_console("never").color_system)

    @mock.patch.dict(os.environ, {"NO_COLOR": "1"})
    def test_no_color_wins_over_auto(self):
        self.assertIsNone(make_console("auto").color_system)

    @mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True)
    def test_force_color_enables_auto(self):
        self.assertIsNotNone(make_console("auto").color_system)

    @mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True)
    def test_never_beats_force_color(self):
        self.assertIsNone(make_console("never").color_system)

    def test_the_width_is_clamped(self):
        self.assertEqual(make_console(width=10).width, 60)
        self.assertEqual(make_console(width=500).width, 140)
        self.assertEqual(make_console(width=100).width, 100)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_output_that_is_not_a_terminal_gets_100_columns(self):
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(make_console().width, 100)

    def test_it_can_write_to_standard_error(self):
        self.assertTrue(make_console(stderr=True).stderr)
        self.assertFalse(make_console().stderr)

    def test_text_is_shown_literally(self):
        console = make_console("never")
        with console.capture() as captured:
            console.print("[red]x[/] :smile: 1.2.3")
        self.assertEqual(captured.get().strip(), "[red]x[/] :smile: 1.2.3")


class StyledTest(unittest.TestCase):
    def test_a_colour_console_adds_escape_codes_and_keeps_the_text(self):
        text = styled(make_console("always"), "RULES", "bold")
        self.assertIn("\x1b[", text)
        self.assertIn("RULES", text)

    def test_a_plain_console_returns_the_text_unchanged(self):
        self.assertEqual(styled(make_console("never"), "RULES", "bold"), "RULES")


class EchoTest(unittest.TestCase):
    def run_echo(self, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            echo(*args, **kwargs)
        return out.getvalue(), err.getvalue()

    def test_writes_a_line_to_standard_output(self):
        self.assertEqual(self.run_echo("hello"), ("hello\n", ""))

    def test_can_write_to_standard_error_and_omit_the_newline(self):
        self.assertEqual(self.run_echo("oops", err=True, end=""), ("", "oops"))

    def test_does_not_interpret_markup_emoji_or_wrap_long_lines(self):
        line = "[bold]x[/] :smile: " + "word " * 60
        self.assertEqual(self.run_echo(line), (line + "\n", ""))

    def test_text_from_fastmail_cannot_drive_the_terminal(self):
        self.assertEqual(self.run_echo("a\x1b[2Jb"), ("a[2Jb\n", ""))

    @mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True)
    def test_a_styled_line_ends_outside_the_style(self):
        out, _ = self.run_echo("ok", style="green")
        self.assertEqual(out, "\x1b[32mok\x1b[0m\n")

    def test_a_style_is_not_visible_when_output_is_not_a_terminal(self):
        self.assertEqual(self.run_echo("ok", style="green"), ("ok\n", ""))

    def test_no_arguments_prints_an_empty_line(self):
        self.assertEqual(self.run_echo(), ("\n", ""))


if __name__ == "__main__":
    unittest.main()
