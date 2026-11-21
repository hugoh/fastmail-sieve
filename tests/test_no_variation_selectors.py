import unittest
from pathlib import Path

VS16 = "\ufe0f"


class NoVariationSelectorTest(unittest.TestCase):
    def test_our_markers_are_always_wide_emoji(self):
        offenders = [
            str(path)
            for pattern in ("src/fastmail_sieve/**/*.py", "variables.toml")
            for path in Path(".").glob(pattern)
            if VS16 in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
