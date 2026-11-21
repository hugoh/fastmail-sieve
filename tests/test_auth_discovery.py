import unittest

from Cryptodome.Cipher import AES
from Cryptodome.Protocol.KDF import PBKDF2
from Cryptodome.Util.Padding import pad

from fastmail_sieve.fastmail.auth_discovery import decrypt_chromium_value

PASSWORD = b"safe-storage-password"


def encrypt(plain, password=PASSWORD):
    """How Chromium on macOS stores a cookie: v10 + AES-128-CBC, PBKDF2 key, 16 spaces IV."""
    key = PBKDF2(password, b"saltysalt", 16, count=1003)
    return b"v10" + AES.new(key, AES.MODE_CBC, b" " * 16).encrypt(pad(plain, 16))


class DecryptChromiumValueTest(unittest.TestCase):
    def test_a_stored_value_round_trips(self):
        self.assertEqual(
            decrypt_chromium_value(encrypt(b"abc123"), PASSWORD, False), "abc123"
        )

    def test_the_host_hash_prefix_is_dropped_on_newer_databases(self):
        stored = encrypt(b"h" * 32 + b"cookie-value")
        self.assertEqual(decrypt_chromium_value(stored, PASSWORD, True), "cookie-value")

    def test_a_value_exactly_one_block_long_round_trips(self):
        plain = b"x" * 16
        self.assertEqual(
            decrypt_chromium_value(encrypt(plain), PASSWORD, False), "x" * 16
        )

    def test_the_wrong_password_is_an_error_not_garbage(self):
        with self.assertRaisesRegex(ValueError, "could not be decrypted"):
            decrypt_chromium_value(encrypt(b"abc123"), b"another-password", False)

    def test_a_truncated_value_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "could not be decrypted"):
            decrypt_chromium_value(encrypt(b"abc123")[:-3], PASSWORD, False)


if __name__ == "__main__":
    unittest.main()
