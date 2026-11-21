import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class LicenseFilesTest(unittest.TestCase):
    def test_the_notice_ships_with_the_wheel_and_the_sdist(self):
        self.assertIn("NOTICE", PYPROJECT["project"]["license-files"])
        self.assertIn(
            "/NOTICE",
            PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"],
        )

    def test_the_notice_carries_the_upstream_mit_notice(self):
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Fastmail-Sieve-Sync", notice)
        self.assertIn("Copyright (c) 2023 Yu-Fu Fu", notice)
        self.assertIn("Permission is hereby granted, free of charge", notice)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', notice)

    def test_the_readme_points_at_the_notice_and_describes_the_relationship(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Relationship to Fastmail-Sieve-Sync", readme)
        self.assertIn("`NOTICE`", readme)
        self.assertNotIn("shares no code", readme)


if __name__ == "__main__":
    unittest.main()
