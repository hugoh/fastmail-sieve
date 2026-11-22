"""Deliberately failing test: proves `ci-gate` goes red. Throwaway, never merge."""

import unittest


class CiGateProbe(unittest.TestCase):
    def test_fails_on_purpose(self) -> None:
        self.fail("deliberate failure to verify the ci-gate negative path")
