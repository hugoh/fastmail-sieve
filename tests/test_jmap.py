import io
import json
import unittest
import urllib.error
import urllib.request
from email.message import Message
from unittest import mock

from fastmail_sieve.fastmail import jmap as jmap_module
from fastmail_sieve.fastmail.jmap import SESSION_URL, invoke, jmap

CREDS = {"token": "fma1-secret", "cookie": "__Http-s_x=y"}
MAIL = "urn:ietf:params:jmap:mail"


class FakeCall:
    """A fake JMAP call: the session on GET, then `reply`; records each request."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, url, credentials, body=None):
        self.calls.append((url, body))
        if body is None:
            return {
                "apiUrl": "https://api.example/jmap",
                "primaryAccounts": {MAIL: "u1"},
            }
        return self.reply


def fake_call(reply):
    return FakeCall(reply)


class InvokeTest(unittest.TestCase):
    def test_reads_the_session_then_makes_one_method_call(self):
        call = fake_call({"methodResponses": [["Thing/get", {"list": [1]}, "0"]]})
        result = invoke(CREDS, ["urn:core"], "Thing/get", {"ids": None}, call)
        self.assertEqual(result, {"list": [1]})
        (session_url, _), (api_url, body) = call.calls
        self.assertEqual(
            (session_url, api_url), (SESSION_URL, "https://api.example/jmap")
        )
        self.assertEqual(body["using"], ["urn:core"])
        self.assertEqual(
            body["methodCalls"], [["Thing/get", {"accountId": "u1", "ids": None}, "0"]]
        )

    def test_an_error_response_becomes_a_runtime_error_with_the_reason(self):
        call = fake_call(
            {
                "methodResponses": [
                    ["error", {"type": "forbidden", "description": "no scope"}, "0"]
                ]
            }
        )
        with self.assertRaisesRegex(RuntimeError, "Thing/get.*forbidden.*no scope"):
            invoke(CREDS, ["urn:core"], "Thing/get", {}, call)


class OpenerCase(unittest.TestCase):
    def open_with(self, outcome):
        patcher = mock.patch.object(jmap_module, "_opener")
        opener = patcher.start()
        self.addCleanup(patcher.stop)
        if isinstance(outcome, Exception):
            opener.open.side_effect = outcome
        else:
            response = mock.MagicMock()
            body = (
                outcome if isinstance(outcome, bytes) else json.dumps(outcome).encode()
            )
            response.__enter__.return_value = io.BytesIO(body)
            opener.open.return_value = response
        return opener.open


class JmapTest(OpenerCase):
    def test_sends_the_credentials_and_a_json_body(self):
        urlopen = self.open_with({"ok": True})
        self.assertEqual(
            jmap("https://api.fastmail.com/x", CREDS, {"a": 1}), {"ok": True}
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer fma1-secret")
        self.assertEqual(request.get_header("Cookie"), "__Http-s_x=y")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"a": 1})

    def test_an_api_token_has_no_cookie_header(self):
        urlopen = self.open_with({"ok": True})
        jmap("https://api.fastmail.com/x", {"token": "api-1", "cookie": None})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer api-1")
        self.assertFalse(request.has_header("Cookie"))

    def test_a_get_has_no_body(self):
        urlopen = self.open_with({"ok": True})
        jmap("https://api.fastmail.com/x", CREDS)
        self.assertIsNone(urlopen.call_args.args[0].data)

    def test_an_expired_session_says_how_to_fix_it(self):
        self.open_with(
            urllib.error.HTTPError("u", 401, "Unauthorized", Message(), None)
        )
        with self.assertRaisesRegex(RuntimeError, r"HTTP 401.*fastmail-sieve auth"):
            jmap("https://api.fastmail.com/x", CREDS)

    def test_other_http_errors_are_reported_with_the_code(self):
        self.open_with(
            urllib.error.HTTPError("u", 500, "Server Error", Message(), None)
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            jmap("https://api.fastmail.com/x", CREDS)

    def test_network_failures_are_readable(self):
        self.open_with(urllib.error.URLError("no route"))
        with self.assertRaisesRegex(RuntimeError, "Could not reach Fastmail: no route"):
            jmap("https://api.fastmail.com/x", CREDS)


SESSION = {
    "apiUrl": "https://api.fastmail.com/jmap/api/",
    "primaryAccounts": {MAIL: "u1"},
}
ANSWER = {"methodResponses": [["Thing/get", {"list": []}, "0"]]}


class SessionCacheTest(OpenerCase):
    def setUp(self):
        jmap_module._sessions.clear()
        self.addCleanup(jmap_module._sessions.clear)

    def answers(self, *bodies):
        pending = list(bodies)
        opener = self.open_with({})

        def respond(request, timeout=None):
            handle = mock.MagicMock()
            handle.__enter__.return_value = io.BytesIO(
                json.dumps(pending.pop(0)).encode()
            )
            return handle

        opener.side_effect = respond
        return opener

    def test_the_session_is_fetched_once_for_several_calls(self):
        opener = self.answers(SESSION, ANSWER, ANSWER, ANSWER)
        for _ in range(3):
            invoke(CREDS, ["urn:core"], "Thing/get", {})
        self.assertEqual(opener.call_count, 4)  # one session and three calls

    def test_each_login_gets_its_own_session(self):
        opener = self.answers(SESSION, ANSWER, SESSION, ANSWER)
        invoke(CREDS, ["urn:core"], "Thing/get", {})
        invoke({"token": "another", "cookie": None}, ["urn:core"], "Thing/get", {})
        self.assertEqual(opener.call_count, 4)

    def test_a_fake_call_is_never_cached(self):
        calls = []

        def call(url, credentials, body=None):
            calls.append(body is None)
            return SESSION if body is None else ANSWER

        invoke(CREDS, ["urn:core"], "Thing/get", {}, call)
        invoke(CREDS, ["urn:core"], "Thing/get", {}, call)
        self.assertEqual(calls.count(True), 2)


class UnreadableAnswerTest(OpenerCase):
    """Whatever goes wrong on the wire is one readable line, never a traceback."""

    def failure(self):
        with self.assertRaises(RuntimeError) as raised:
            jmap("https://api.fastmail.com/x", CREDS)
        return str(raised.exception)

    def test_an_html_page_with_http_200_is_explained(self):
        self.open_with(b"<html>please sign in</html>")
        self.assertRegex(self.failure(), "did not answer with JSON.*proxy")

    def test_a_timeout_on_connect_names_the_limit(self):
        self.open_with(TimeoutError("timed out"))
        self.assertRegex(self.failure(), "did not answer within 30 seconds")

    def test_a_timeout_while_reading_the_body_names_the_limit(self):
        class Stalls(io.BytesIO):
            def read(self, *args):
                raise TimeoutError("timed out")

        opener = self.open_with({})
        opener.return_value.__enter__.return_value = Stalls()
        self.assertRegex(self.failure(), "did not answer within 30 seconds")

    def test_a_dropped_connection_is_reported(self):
        self.open_with(ConnectionResetError("reset by peer"))
        self.assertRegex(self.failure(), "Could not reach Fastmail: .*reset by peer")


class InvokeShapeTest(unittest.TestCase):
    def call_returning(self, session, reply=None):
        def call(url, credentials, body=None):
            return session if body is None else reply

        return call

    def test_credentials_with_no_mail_account_say_what_is_missing(self):
        call = self.call_returning(
            {"apiUrl": "https://api.fastmail.com/x", "primaryAccounts": {}}
        )
        with self.assertRaisesRegex(RuntimeError, "no mail account.*Email scope"):
            invoke(CREDS, ["urn:core"], "Thing/get", {}, call)

    def test_an_answer_without_method_responses_is_explained(self):
        session = {
            "apiUrl": "https://api.fastmail.com/x",
            "primaryAccounts": {MAIL: "u1"},
        }
        for reply in ({}, {"methodResponses": []}, None, "text"):
            with (
                self.subTest(reply=reply),
                self.assertRaisesRegex(RuntimeError, "not in the expected form"),
            ):
                invoke(
                    CREDS,
                    ["urn:core"],
                    "Thing/get",
                    {},
                    self.call_returning(session, reply),
                )


class UrlGuardTest(OpenerCase):
    """The token and cookie are a full web session: they go only to fastmail.com over https."""

    def refused(self, url, pattern):
        opened = self.open_with({"ok": True})
        with self.assertRaises(RuntimeError) as raised:
            jmap(url, CREDS)
        self.assertRegex(str(raised.exception), pattern)
        self.assertNotIn("fma1-secret", str(raised.exception))
        self.assertNotIn("Http-s_", str(raised.exception))
        opened.assert_not_called()

    def test_plain_http_is_refused(self):
        self.refused("http://api.fastmail.com/jmap/session", "https")

    def test_other_hosts_are_refused_and_named(self):
        for url in (
            "https://evil.example/",
            "https://api.fastmail.com.evil.example/",
            "https://notfastmail.com/",
            "https://api.fastmail.com@evil.example/",
        ):
            with self.subTest(url=url):
                self.refused(url, "not a fastmail.com address")

    def test_fastmail_hosts_are_accepted(self):
        for url in (
            "https://api.fastmail.com/jmap/api/",
            "https://fastmail.com/x",
            "https://API.FASTMAIL.COM/x",
        ):
            with self.subTest(url=url):
                opened = self.open_with({"ok": True})
                self.assertEqual(jmap(url, CREDS), {"ok": True})
                opened.assert_called_once()

    def test_redirects_are_never_followed(self):
        handler = jmap_module._NoRedirect()
        request = urllib.request.Request("https://api.fastmail.com/x")
        self.assertIsNone(
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://evil.example/"
            )
        )

    def test_a_redirect_answer_is_reported_as_refused(self):
        self.open_with(urllib.error.HTTPError("u", 302, "Found", Message(), None))
        with self.assertRaisesRegex(RuntimeError, "redirect.*refused"):
            jmap("https://api.fastmail.com/x", CREDS)

    def test_a_foreign_api_url_in_the_session_never_receives_the_login(self):
        session = {
            "apiUrl": "https://evil.example/api",
            "primaryAccounts": {MAIL: "u1"},
        }
        opened = self.open_with(session)
        with self.assertRaisesRegex(RuntimeError, "evil.example"):
            invoke(CREDS, ["urn:core"], "Thing/get", {})
        self.assertEqual(opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
