import contextlib
import io
import unittest
from unittest import mock

from fastmail_sieve.cli import main
from fastmail_sieve.fastmail.auth_input import clean_token, parse_curl, validate_token

TOKEN = "fma1-" + "abcDEF123_-xyz"  # gitleaks:allow (a made-up value)
COOKIE = "__Http-s_abc=VALUE1; other=2"

CHROME_CURL = f"""curl 'https://api.fastmail.com/jmap/api/' \\
  -H 'accept: */*' \\
  -H 'authorization: Bearer {TOKEN}' \\
  -H 'content-type: application/json' \\
  -H 'cookie: {COOKIE}' \\
  --data-raw '{{"using":[]}}'
"""
FLAG_CURL = f"""curl "https://api.fastmail.com/jmap/api/" -H "Authorization: Bearer {TOKEN}" -b "{COOKIE}" """


class ParseCurlTest(unittest.TestCase):
    def test_reads_the_bearer_token_and_cookie_header_across_continuations(self):
        self.assertEqual(parse_curl(CHROME_CURL), (TOKEN, COOKIE))

    def test_the_cookie_flag_and_double_quotes(self):
        self.assertEqual(parse_curl(FLAG_CURL), (TOKEN, COOKIE))

    def test_bash_ansi_quoting_is_accepted(self):
        text = f"curl -H $'Authorization: Bearer {TOKEN}' --header $'Cookie: {COOKIE}' https://x"
        self.assertEqual(parse_curl(text), (TOKEN, COOKIE))

    def test_no_bearer_header_is_an_error_that_does_not_echo_the_input(self):
        with self.assertRaises(RuntimeError) as raised:
            parse_curl(f"curl -H 'Cookie: {COOKIE}' https://x")
        self.assertIn("Authorization: Bearer", str(raised.exception))
        self.assertNotIn("VALUE1", str(raised.exception))

    def test_no_cookie_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "Cookie"):
            parse_curl(f"curl -H 'Authorization: Bearer {TOKEN}' https://x")


class TokenTest(unittest.TestCase):
    def test_clean_token_strips_the_header_prefix(self):
        for raw in (
            TOKEN,
            f" {TOKEN}\n",
            f"Bearer {TOKEN}",
            f"Authorization: Bearer {TOKEN}",
        ):
            self.assertEqual(clean_token(raw), TOKEN)

    def test_validate_token_wants_the_session_prefix_without_echoing_the_value(self):
        self.assertEqual(validate_token(TOKEN), TOKEN)
        with self.assertRaises(RuntimeError) as raised:
            validate_token("not-a-token-SECRET")
        self.assertIn("fma1-", str(raised.exception))
        self.assertNotIn("SECRET", str(raised.exception))


class AuthCommandTest(unittest.TestCase):
    def run_auth(
        self, *argv, stdin="", prompts=(), validate=None, store=None, env=None
    ):
        out, err = io.StringIO(), io.StringIO()
        validate = validate or mock.Mock(return_value={"username": "me@example.com"})
        store = store or mock.Mock()
        patches = [
            mock.patch("sys.stdin", io.StringIO(stdin)),
            mock.patch("fastmail_sieve.commands.auth.jmap", validate),
            mock.patch("fastmail_sieve.commands.auth.store_keychain", store),
            mock.patch(
                "fastmail_sieve.commands.auth.getpass.getpass",
                side_effect=list(prompts),
            ),
            mock.patch.dict("os.environ", env or {}, clear=True),
        ]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["auth", *argv])
        return code, out.getvalue() + err.getvalue(), validate, store

    def test_stdin_takes_a_pasted_curl_command(self):
        code, output, validate, store = self.run_auth("--stdin", stdin=CHROME_CURL)
        self.assertEqual(code, 0)
        store.assert_called_once_with("me@example.com", TOKEN, COOKIE)
        self.assertIn("me@example.com", output)
        self.assertNotIn(TOKEN, output)
        self.assertNotIn("VALUE1", output)
        creds = validate.call_args.args[1]
        self.assertEqual((creds["token"], creds["cookie"]), (TOKEN, COOKIE))

    def test_without_stdin_it_prompts_with_hidden_input(self):
        code, output, _, store = self.run_auth(prompts=[TOKEN, COOKIE])
        self.assertEqual(code, 0)
        store.assert_called_once_with("me@example.com", TOKEN, COOKIE)
        self.assertNotIn(TOKEN, output)

    def test_a_token_that_is_not_a_session_token_is_refused_before_any_request(self):
        code, output, validate, store = self.run_auth(prompts=["nope", COOKIE])
        self.assertEqual(code, 1)
        validate.assert_not_called()
        store.assert_not_called()
        self.assertIn("fma1-", output)

    def test_fastmail_rejecting_the_pair_stores_nothing(self):
        validate = mock.Mock(
            side_effect=RuntimeError("Fastmail answered HTTP 401 Unauthorized")
        )
        code, output, _, store = self.run_auth(
            "--stdin", stdin=CHROME_CURL, validate=validate
        )
        self.assertEqual(code, 1)
        store.assert_not_called()
        self.assertIn("HTTP 401", output)

    def test_no_keychain_explains_the_alternatives(self):
        store = mock.Mock(side_effect=RuntimeError("no usable keychain here"))
        code, output, _, _ = self.run_auth("--stdin", stdin=CHROME_CURL, store=store)
        self.assertEqual(code, 1)
        self.assertIn("no usable keychain", output)

    def test_discovery_only_runs_when_asked_and_says_what_it_reads(self):
        finder = mock.Mock(return_value=("Fastmail app", COOKIE))
        with mock.patch("fastmail_sieve.commands.auth.discover_cookie", finder):
            code, output, _, store = self.run_auth("--discover", prompts=[TOKEN])
        self.assertEqual(code, 0)
        finder.assert_called_once()
        store.assert_called_once_with("me@example.com", TOKEN, COOKIE)
        self.assertIn("Fastmail Safe Storage", output)
        self.assertIn("other apps", output)

    def test_without_discover_nothing_is_discovered(self):
        finder = mock.Mock()
        with mock.patch("fastmail_sieve.commands.auth.discover_cookie", finder):
            self.run_auth(prompts=[TOKEN, COOKIE])
        finder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
