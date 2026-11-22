from dataclasses import dataclass, replace

from fastmail_sieve.fastmail.jmap import MethodError, invoke, jmap
from fastmail_sieve.sieve.script import (
    LEGACY_MARKER_END,
    LEGACY_MARKER_START,
    MARKER_END,
    MARKER_PAIRS,
    MARKER_START,
)

# Fastmail's own (undocumented) methods for the Sieve script, not RFC 9661.
SIEVE_USING = (
    "https://www.fastmail.com/dev/rules",
    "https://www.fastmail.com/dev/user",
)


NO_BLOCKS = (
    "Fastmail's script has no managed blocks yet: "
    "run `fastmail-sieve init --remote` once to add them"
)


CHANGED = (
    "Fastmail's managed blocks changed while you were deciding: "
    "run the command again to see the new diff"
)


def _markers(block):
    """The (start, end) marker pair a block uses, new style first, or None."""
    for start, end in MARKER_PAIRS:
        if start in block and end in block:
            return start, end
    return None


def _has_markers(block):
    return _markers(block) is not None


def _with_markers(block):
    if _has_markers(block):
        return block
    return f"{block}\n{MARKER_START}\n{MARKER_END}".strip()


LEGACY_PAIR = (LEGACY_MARKER_START, LEGACY_MARKER_END)


def _uses_legacy(block):
    return _markers(block) == LEGACY_PAIR


def _convert(block):
    if not _uses_legacy(block):
        return block
    return block.replace(LEGACY_MARKER_START, MARKER_START, 1).replace(
        LEGACY_MARKER_END, MARKER_END, 1
    )


def _fragment(block):
    markers = _markers(block)
    if markers is None:
        raise RuntimeError(NO_BLOCKS)
    start, end = markers
    return block[block.index(start) + len(start) : block.index(end)].removeprefix("\n")


def _stored(fragment):
    """How a fragment is kept in a block: always ending in a newline."""
    return fragment + "\n" if fragment and not fragment.endswith("\n") else fragment


def _with_fragment(block, fragment):
    markers = _markers(block)
    if markers is None:
        raise RuntimeError(NO_BLOCKS)
    start, end = markers
    fragment = _stored(fragment)
    before = block[: block.index(start)]
    after = block[block.index(end) + len(end) :]
    return f"{before}{start}\n{fragment}{end}{after}".strip()


@dataclass(frozen=True)
class RemoteScript:
    """The script as Fastmail stores it: six parts, of which only the start, middle
    and end blocks (your `top`, `middle` and `bottom` fragments) can be written."""

    require: str
    start: str
    blocked: str
    middle: str
    rules: str
    end: str

    @classmethod
    def from_json(cls, data):
        return cls(
            require=data["sieveRequire"],
            start=data["sieveAtStart"],
            blocked=data["sieveForBlocked"],
            middle=data["sieveAtMiddle"],
            rules=data["sieveForRules"],
            end=data["sieveAtEnd"],
        )

    @property
    def text(self):
        parts = (
            self.require,
            self.start,
            self.blocked,
            self.middle,
            self.rules,
            self.end,
        )
        return "\n".join(parts)

    @property
    def fragments(self):
        return tuple(_fragment(block) for block in (self.start, self.middle, self.end))

    def matches(self, fragments):
        """Whether the blocks hold these fragments, the way they would be stored."""
        return self.fragments == tuple(_stored(f) for f in fragments)

    def with_fragments(self, top, middle, bottom):
        return replace(
            self,
            start=_with_fragment(self.start, top),
            middle=_with_fragment(self.middle, middle),
            end=_with_fragment(self.end, bottom),
        )

    @property
    def has_markers(self):
        return all(_has_markers(block) for block in (self.start, self.middle, self.end))

    def with_markers(self):
        return replace(
            self,
            start=_with_markers(self.start),
            middle=_with_markers(self.middle),
            end=_with_markers(self.end),
        )

    @property
    def uses_legacy_markers(self):
        return any(_uses_legacy(b) for b in (self.start, self.middle, self.end))

    def convert_markers(self):
        """The same script with Sieve-Sync's markers replaced by this tool's own."""
        return replace(
            self,
            start=_convert(self.start),
            middle=_convert(self.middle),
            end=_convert(self.end),
        )

    def same_blocks(self, other):
        return (self.start, self.middle, self.end) == (
            other.start,
            other.middle,
            other.end,
        )


def get_script(credentials, call=jmap):
    result = invoke(
        credentials, SIEVE_USING, "SieveBlocks/get", {"ids": ["singleton"]}, call
    )
    if not result.get("list"):
        raise RuntimeError("Fastmail returned no Sieve script")
    return RemoteScript.from_json(result["list"][0])


def set_blocks(credentials, script, call=jmap):
    update = {
        "sieveAtStart": script.start,
        "sieveAtMiddle": script.middle,
        "sieveAtEnd": script.end,
    }
    try:
        result = invoke(
            credentials,
            SIEVE_USING,
            "SieveBlocks/set",
            {"update": {"singleton": update}},
            call,
        )
    except MethodError as error:
        if error.type == "stateMismatch":
            raise RuntimeError(CHANGED) from error
        raise
    if result.get("notUpdated"):
        raise RuntimeError(f"Fastmail refused the update: {result['notUpdated']}")


def validate_sieve(credentials, text, call=jmap):
    """Ask Fastmail whether it accepts this whole script: None if it does, else
    why not. Its parser is stricter than the Sieve spec (keywords must be
    lowercase), so only this answer says the script will be accepted."""
    result = invoke(credentials, SIEVE_USING, "Validate/sieve", {"sieve": text}, call)
    if result.get("isValid") is True:
        return None
    return (
        result.get("errorDescription")
        or "Fastmail's validator did not say the script is valid"
    )
