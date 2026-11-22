import os
import re
import sys
from typing import Literal

from rich.console import Console
from rich.text import Text

DEFAULT_WIDTH = 100
MIN_WIDTH, MAX_WIDTH = 60, 140


VARIATION_SELECTOR = "\ufe0f"


def strip_variation_selectors(text):
    """Terminals draw emoji-presentation characters two cells wide while rich
    counts them as one, so drop the selector from displayed text."""
    return text.replace(VARIATION_SELECTOR, "")


# Everything that can move the cursor, retitle the window or otherwise drive a
# terminal (C0 and C1 controls, DEL), except the newline and tab that layout needs.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe_text(text):
    """Text from Fastmail, made safe to print: no control characters, no
    variation selectors. A carriage return counts as a control character, so
    CRLF becomes LF."""
    return CONTROL_CHARACTERS.sub("", strip_variation_selectors(text))


def cell(text, style=""):
    return Text(safe_text(text), style=style)


def make_console(color="auto", width=None, stderr=False):
    """The one place a rich Console is configured.

    `color` is "auto" (a terminal, FORCE_COLOR and NO_COLOR decide), "always" or
    "never". The width is the terminal's, 100 when the output is not a terminal,
    and always between 60 and 140 columns so tables stay readable. Text is shown
    literally: no markup, emoji codes or automatic highlighting."""
    if color == "auto" and os.environ.get("NO_COLOR"):
        color = "never"
    force_terminal: bool | None = None
    color_system: Literal["auto", "standard"] | None = "auto"
    if color == "always":
        force_terminal, color_system = True, "standard"
    elif color == "never":
        force_terminal, color_system = False, None
    console = Console(
        width=width,
        stderr=stderr,
        force_terminal=force_terminal,
        color_system=color_system,
        markup=False,
        emoji=False,
        highlight=False,
    )
    stream = sys.stderr if stderr else sys.stdout
    if width is None and not stream.isatty() and "COLUMNS" not in os.environ:
        console.width = DEFAULT_WIDTH
    console.width = max(MIN_WIDTH, min(console.width, MAX_WIDTH))
    return console


def render_table(table, console):
    """The lines a table takes on this console, with its colour and width."""
    with console.capture() as captured:
        console.print(table)
    return captured.get().rstrip("\n").split("\n")


def styled(console, text, style):
    """`text` in this style, as the console would show it: unchanged when it has
    no colour."""
    if console.color_system is None:
        return text
    with console.capture() as captured:
        console.print(Text(text, style=style), end="")
    return captured.get()


def echo(text="", *, err=False, end="\n", style=None):
    """Print a line to standard output (or error). The text is written as it is,
    after removing control characters, so it is safe for what Fastmail sent and
    exact for what is meant to be copied; with a `style`, through rich."""
    text = safe_text(text)
    stream = sys.stderr if err else sys.stdout
    if style:
        # The line ending is written outside the style, not coloured with it.
        make_console(stderr=err).print(
            text, style=style, end="", soft_wrap=True, markup=False
        )
        stream.write(end)
        return
    stream.write(text + end)
