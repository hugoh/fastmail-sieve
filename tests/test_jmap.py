import io
import json
import unittest
import urllib.error
from email.message import Message
from unittest import mock

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


class JmapTest(unittest.TestCase):
    def open_with(self, outcome):
        patcher = mock.patch("fastmail_sieve.fastmail.jmap.urllib.request.urlopen")
        urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        if isinstance(outcome, Exception):
            urlopen.side_effect = outcome
        else:
            response = mock.MagicMock()
            response.__enter__.return_value = io.BytesIO(json.dumps(outcome).encode())
            urlopen.return_value = response
        return urlopen

    def test_sends_the_credentials_and_a_json_body(self):
        urlopen = self.open_with({"ok": True})
        self.assertEqual(jmap("https://api.example/x", CREDS, {"a": 1}), {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer fma1-secret")
        self.assertEqual(request.get_header("Cookie"), "__Http-s_x=y")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"a": 1})

    def test_an_api_token_has_no_cookie_header(self):
        urlopen = self.open_with({"ok": True})
        jmap("https://api.example/x", {"token": "api-1", "cookie": None})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer api-1")
        self.assertFalse(request.has_header("Cookie"))

    def test_a_get_has_no_body(self):
        urlopen = self.open_with({"ok": True})
        jmap("https://api.example/x", CREDS)
        self.assertIsNone(urlopen.call_args.args[0].data)

    def test_an_expired_session_says_how_to_fix_it(self):
        self.open_with(
            urllib.error.HTTPError("u", 401, "Unauthorized", Message(), None)
        )
        with self.assertRaisesRegex(RuntimeError, r"HTTP 401.*fastmail-sieve auth"):
            jmap("https://api.example/x", CREDS)

    def test_other_http_errors_are_reported_with_the_code(self):
        self.open_with(
            urllib.error.HTTPError("u", 500, "Server Error", Message(), None)
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            jmap("https://api.example/x", CREDS)

    def test_network_failures_are_readable(self):
        self.open_with(urllib.error.URLError("no route"))
        with self.assertRaisesRegex(RuntimeError, "Could not reach Fastmail: no route"):
            jmap("https://api.example/x", CREDS)


if __name__ == "__main__":
    unittest.main()
