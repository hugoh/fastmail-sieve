START_TEXTS = ("Managed by fastmail-sieve: start", "Managed by Sieve Sync Start")
END_TEXTS = ("Managed by fastmail-sieve: end", "Managed by Sieve Sync End")
MARKER_START = f"#### {START_TEXTS[0]} ####"
MARKER_END = f"#### {END_TEXTS[0]} ####"
LEGACY_MARKER_START = f"#### {START_TEXTS[1]} ####"
LEGACY_MARKER_END = f"#### {END_TEXTS[1]} ####"
MARKER_PAIRS = ((MARKER_START, MARKER_END), (LEGACY_MARKER_START, LEGACY_MARKER_END))
STARTS = tuple(start for start, _ in MARKER_PAIRS)
ENDS = tuple(end for _, end in MARKER_PAIRS)
BLOCK_COUNT = 3


def contains_marker(text):
    return any(marker in text for marker in STARTS + ENDS)


def mentions_marker(text):
    return any(words in text for words in START_TEXTS + END_TEXTS)


def mentions_start(text):
    return any(words in text for words in START_TEXTS)


def mentions_end(text):
    return any(words in text for words in END_TEXTS)


def _pairs(lines):
    starts = [i for i, line in enumerate(lines) if line in STARTS]
    ends = [i for i, line in enumerate(lines) if line in ENDS]
    if len(starts) != BLOCK_COUNT or len(ends) != BLOCK_COUNT:
        raise ValueError(
            f"expected {BLOCK_COUNT} marker pairs, found {len(starts)}/{len(ends)}"
        )
    pairs = list(zip(starts, ends, strict=True))
    if any(start >= end for start, end in pairs) or any(
        pairs[i][1] >= pairs[i + 1][0] for i in range(BLOCK_COUNT - 1)
    ):
        raise ValueError("marker pairs are out of order")
    return pairs


def split(text):
    lines = text.split("\n")
    return tuple(
        "".join(f"{line}\n" for line in lines[start + 1 : end])
        for start, end in _pairs(lines)
    )


def live_fragments(text):
    """The text of the three managed blocks of a script, or empty ones if it has none."""
    try:
        return split(text)
    except ValueError:
        return ("", "", "")


def assemble(skeleton, top, middle, bottom):
    fragments = (top, middle, bottom)
    if any(contains_marker(f) for f in fragments):
        raise ValueError("a fragment must not contain managed-block markers")
    lines = skeleton.split("\n")
    result = []
    cursor = 0
    for (start, end), fragment in zip(_pairs(lines), fragments, strict=True):
        result += lines[cursor : start + 1]
        result += fragment.removesuffix("\n").split("\n") if fragment else []
        cursor = end
    return "\n".join(result + lines[cursor:])
