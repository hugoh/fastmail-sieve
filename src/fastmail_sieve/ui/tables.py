import io
import os
import re
import shutil

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


def render_table(table, width, color):
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=width,
        force_terminal=color,
        color_system="standard" if color else None,
        no_color=not color,
        markup=False,
        emoji=False,
        highlight=False,
    )
    console.print(table)
    return buffer.getvalue().rstrip("\n").split("\n")


def use_color(choice="auto"):
    import sys

    if choice == "always":
        return True
    if choice == "never" or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))


def terminal_width(requested=None):
    columns = requested or shutil.get_terminal_size((DEFAULT_WIDTH, 24)).columns
    return max(MIN_WIDTH, min(int(columns), MAX_WIDTH))
