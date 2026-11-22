import unittest


class CiGateProbe(unittest.TestCase):
    def test_fails_on_purpose(self) -> None:
        self.fail("probe for the ci-gate required check; never merge")
