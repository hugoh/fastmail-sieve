import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve.remote import fetch_script, load_assembled, load_remote
from tests.test_sieve_blocks import skeleton


class InTempDir(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        previous = os.getcwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, previous)


class FetchScriptTest(InTempDir):
    def test_reads_the_script_text_from_fastmail(self):
        script = mock.Mock(text="remote script\n")
        with (
            mock.patch(
                "fastmail_sieve.remote.load_credentials", return_value={"token": "t"}
            ),
            mock.patch(
                "fastmail_sieve.remote.get_script", return_value=script
            ) as get_script,
        ):
            self.assertEqual(fetch_script(), "remote script\n")
        get_script.assert_called_once_with({"token": "t"})
        self.assertFalse(Path("rules.sieve").exists())


class LoadTest(InTempDir):
    def test_from_file_reads_the_file_without_touching_fastmail(self):
        Path("copy.sieve").write_text("saved\n")
        with mock.patch("fastmail_sieve.remote.get_script") as get_script:
            self.assertEqual(load_remote("copy.sieve"), "saved\n")
        get_script.assert_not_called()

    def test_without_a_file_the_script_is_fetched(self):
        with mock.patch(
            "fastmail_sieve.remote.fetch_script", return_value="live\n"
        ) as fetch:
            self.assertEqual(load_remote(), "live\n")
        fetch.assert_called_once_with()

    def test_assembled_puts_the_local_fragments_into_the_remote_script(self):
        Path("copy.sieve").write_text(skeleton("old;\n", "old;\n", "old;\n"))
        fragments = ("new top;\n", "new middle;\n", "new bottom;\n")
        with mock.patch("fastmail_sieve.remote.read_fragments", return_value=fragments):
            text = load_assembled("copy.sieve")
        self.assertIn("new top;\n", text)
        self.assertNotIn("old;", text)


if __name__ == "__main__":
    unittest.main()
