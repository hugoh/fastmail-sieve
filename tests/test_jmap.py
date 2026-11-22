import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from unittest import mock

import requests
import responses

from fastmail_sieve.fastmail import jmap as jmap_module
from fastmail_sieve.fastmail.jmap import SESSION_URL, invoke, jmap
from tests.support import API as FASTMAIL_API
from tests.support import FastmailCase

CREDS = {"token": "fma1-secret", "cookie": "__Http-s_x=y"}
MAIL = "urn:ietf:params:jmap:mail"


class InvokeTest(FastmailCase):
    def test_reads_the_session_then_makes_one_method_call(self):
        self.reply("Thing/get", {"list": [1]})
        result = invoke(CREDS, ["urn:core"], "Thing/get", {"ids": None})
        self.assertEqual(result, {"list": [1]})
        self.assertEqual(
            [(c.request.method, c.request.url) for c in self.http.calls],
            [("GET", SESSION_URL), ("POST", FASTMAIL_API)],
        )
        body = self.bodies[0]
        self.assertEqual(body["using"], ["urn:core"])
        self.assertEqual(
            body["methodCalls"], [["Thing/get", {"accountId": "u1", "ids": None}, "0"]]
        )

    def test_an_error_response_becomes_a_runtime_error_with_the_reason(self):
        self.reply("error", {"type": "forbidden", "description": "no scope"})
        with self.assertRaisesRegex(RuntimeError, "Thing/get.*forbidden.*no scope"):
            invoke(CREDS, ["urn:core"], "Thing/get", {})


API = "https://api.fastmail.com/x"
READ = {"methodCalls": [["Thing/get", {}, "0"]]}
WRITE = {"methodCalls": [["SieveBlocks/set", {}, "0"]]}


class HttpCase(unittest.TestCase):
    def setUp(self):
        jmap_module._sessions.clear()
        jmap_module._sessions_by_policy.clear()
        self.addCleanup(jmap_module._sessions.clear)
        self.addCleanup(jmap_module._sessions_by_policy.clear)
        mocked = responses.RequestsMock(assert_all_requests_are_fired=False)
        self.http = mocked
        mocked.start()
        self.addCleanup(mocked.stop)
        self.addCleanup(mocked.reset)

    def reply(self, body=None, status=200, **kwargs):
        if isinstance(body, (dict, list)):
            kwargs["json"] = body
        elif body is not None:
            kwargs["body"] = body
        self.http.add(responses.POST, API, status=status, **kwargs)
        self.http.add(responses.GET, API, status=status, **kwargs)


class JmapTest(HttpCase):
    def test_sends_the_credentials_and_a_json_body(self):
        self.reply({"ok": True})
        self.assertEqual(jmap(API, CREDS, {"a": 1}), {"ok": True})
        request = self.http.calls[0].request
        self.assertEqual(request.headers["Authorization"], "Bearer fma1-secret")
        self.assertEqual(request.headers["Cookie"], "__Http-s_x=y")
        self.assertEqual(request.headers["Content-Type"], "application/json")
        body = request.body
        assert isinstance(body, bytes)
        self.assertEqual(json.loads(body), {"a": 1})

    def test_it_says_who_it_is(self):
        self.reply({"ok": True})
        jmap(API, CREDS)
        headers = self.http.calls[0].request.headers
        self.assertRegex(str(headers["User-Agent"]), r"^fastmail-sieve")
        self.assertEqual(headers["Accept"], "application/json")

    def test_an_api_token_has_no_cookie_header(self):
        self.reply({"ok": True})
        jmap(API, {"token": "api-1", "cookie": None})
        headers = self.http.calls[0].request.headers
        self.assertEqual(headers["Authorization"], "Bearer api-1")
        self.assertNotIn("Cookie", headers)

    def test_a_get_has_no_body(self):
        self.reply({"ok": True})
        jmap(API, CREDS)
        self.assertEqual(self.http.calls[0].request.method, "GET")
        self.assertIsNone(self.http.calls[0].request.body)

    def test_a_netrc_entry_never_replaces_the_token(self):
        self.reply({"ok": True})
        with mock.patch("requests.sessions.get_netrc_auth", return_value=("u", "p")):
            jmap(API, CREDS)
        self.assertEqual(
            self.http.calls[0].request.headers["Authorization"], "Bearer fma1-secret"
        )

    def test_an_expired_session_says_how_to_fix_it(self):
        self.reply(status=401)
        with self.assertRaisesRegex(RuntimeError, r"HTTP 401.*fastmail-sieve auth"):
            jmap(API, CREDS)

    def test_other_http_errors_are_reported_with_the_code(self):
        self.reply(status=500)
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            jmap(API, CREDS)

    def test_a_problem_answer_says_what_fastmail_called_it(self):
        self.reply(
            {"type": "urn:ietf:params:jmap:error:limit", "detail": "too many"},
            status=400,
        )
        with self.assertRaisesRegex(RuntimeError, r"HTTP 400.*error:limit: too many"):
            jmap(API, CREDS)

    def test_network_failures_are_readable(self):
        self.reply(body=requests.exceptions.ConnectionError("no route"))
        with self.assertRaisesRegex(RuntimeError, "Could not reach Fastmail: no route"):
            jmap(API, CREDS)

    def test_set_cookie_answers_are_not_kept_or_resent(self):
        self.reply({"ok": True}, headers={"Set-Cookie": "x=1; Domain=fastmail.com"})
        jmap(API, CREDS)
        jmap(API, CREDS)
        self.assertEqual(self.http.calls[1].request.headers["Cookie"], "__Http-s_x=y")


SESSION = {
    "apiUrl": "https://api.fastmail.com/jmap/api/",
    "primaryAccounts": {MAIL: "u1"},
}
ANSWER = {"methodResponses": [["Thing/get", {"list": []}, "0"]]}


class SessionCacheTest(HttpCase):
    def answers(self, *bodies):
        pending = list(bodies)

        def respond(request):
            return (200, {}, json.dumps(pending.pop(0)))

        self.http.add_callback(responses.GET, SESSION_URL, callback=respond)
        self.http.add_callback(
            responses.POST, "https://api.fastmail.com/jmap/api/", callback=respond
        )

    def test_the_session_is_fetched_once_for_several_calls(self):
        self.answers(SESSION, ANSWER, ANSWER, ANSWER)
        for _ in range(3):
            invoke(CREDS, ["urn:core"], "Thing/get", {})
        self.assertEqual(len(self.http.calls), 4)  # one session and three calls

    def test_each_login_gets_its_own_session(self):
        self.answers(SESSION, ANSWER, SESSION, ANSWER)
        invoke(CREDS, ["urn:core"], "Thing/get", {})
        invoke({"token": "another", "cookie": None}, ["urn:core"], "Thing/get", {})
        self.assertEqual(len(self.http.calls), 4)


class UnreadableAnswerTest(HttpCase):
    """Whatever goes wrong on the wire is one readable line, never a traceback."""

    def failure(self):
        with self.assertRaises(RuntimeError) as raised:
            jmap(API, CREDS)
        return str(raised.exception)

    def test_an_html_page_with_http_200_is_explained(self):
        self.reply("<html>please sign in</html>")
        self.assertRegex(self.failure(), "did not answer with JSON.*proxy")

    def test_a_timeout_names_the_limit(self):
        self.reply(body=requests.exceptions.ReadTimeout("timed out"))
        self.assertRegex(self.failure(), "did not answer within 30 seconds")

    def test_a_dropped_connection_is_reported(self):
        self.reply(body=requests.exceptions.ConnectionError("reset by peer"))
        self.assertRegex(self.failure(), "Could not reach Fastmail: .*reset by peer")

    def test_a_huge_answer_is_not_read(self):
        with mock.patch.object(jmap_module, "MAX_RESPONSE_BYTES", 10):
            self.reply('{"a": "' + "x" * 100 + '"}')
            self.assertRegex(self.failure(), "larger than expected")


class InvokeShapeTest(FastmailCase):
    def test_credentials_with_no_mail_account_say_what_is_missing(self):
        self.session = {"apiUrl": FASTMAIL_API, "primaryAccounts": {}}
        with self.assertRaisesRegex(RuntimeError, "no mail account.*Email scope"):
            invoke(CREDS, ["urn:core"], "Thing/get", {})

    def test_an_answer_without_method_responses_is_explained(self):
        for reply in ({}, {"methodResponses": []}, None, "text"):
            with (
                self.subTest(reply=reply),
                self.assertRaisesRegex(RuntimeError, "not in the expected form"),
            ):
                self.reply_raw(reply)
                invoke(CREDS, ["urn:core"], "Thing/get", {})


class UrlGuardTest(HttpCase):
    """The token and cookie are a full web session: they go only to fastmail.com over https."""

    def refused(self, url, pattern):
        self.http.add(responses.GET, url, json={"ok": True})
        with self.assertRaises(RuntimeError) as raised:
            jmap(url, CREDS)
        self.assertRegex(str(raised.exception), pattern)
        self.assertNotIn("fma1-secret", str(raised.exception))
        self.assertNotIn("Http-s_", str(raised.exception))
        self.assertEqual(len(self.http.calls), 0)

    def test_plain_http_is_refused(self):
        self.refused("http://api.fastmail.com/jmap/session", "https")

    def test_other_hosts_are_refused_and_named(self):
        for url in (
            "https://evil.example/",
            "https://www.fastmail.com/x",
            "https://fastmail.com/x",
            "https://anything.fastmail.com/x",
            "https://api.fastmail.com.evil.example/",
            "https://notfastmail.com/",
            "https://api.fastmail.com@evil.example/",
        ):
            with self.subTest(url=url):
                self.refused(url, "not an api.fastmail.com address")

    def test_only_the_api_host_is_accepted(self):
        for url in (
            "https://api.fastmail.com/jmap/api/",
            "https://API.FASTMAIL.COM/x",
        ):
            with self.subTest(url=url):
                self.http.add(responses.GET, url, json={"ok": True})
                self.assertEqual(jmap(url, CREDS), {"ok": True})

    def test_a_redirect_is_not_followed_and_is_reported_as_refused(self):
        self.reply(status=302, headers={"Location": "https://evil.example/"})
        with self.assertRaisesRegex(RuntimeError, "redirect.*refused"):
            jmap(API, CREDS)
        self.assertEqual(len(self.http.calls), 1)

    def test_a_foreign_api_url_in_the_session_never_receives_the_login(self):
        session = {
            "apiUrl": "https://evil.example/api",
            "primaryAccounts": {MAIL: "u1"},
        }
        self.http.add(responses.GET, SESSION_URL, json=session)
        with self.assertRaisesRegex(RuntimeError, "evil.example"):
            invoke(CREDS, ["urn:core"], "Thing/get", {})
        self.assertEqual(len(self.http.calls), 1)


class DeadlineTest(unittest.TestCase):
    """Retries stop starting once a request has been struggling for too long."""

    def increment(self, retry):
        from urllib3 import HTTPResponse

        return retry.increment("GET", "/", response=HTTPResponse(status=503))

    def test_a_retry_within_the_deadline_goes_ahead(self):
        retry = self.increment(jmap_module._policy(True))
        self.assertIsNotNone(self.increment(retry))

    def test_no_new_retry_after_the_deadline(self):
        from urllib3.exceptions import MaxRetryError

        with mock.patch.object(jmap_module.time, "monotonic") as clock:
            clock.return_value = 1000.0
            retry = self.increment(jmap_module._policy(True))
            clock.return_value = 1000.0 + jmap_module.DEADLINE_SECONDS + 1
            with self.assertRaises(MaxRetryError):
                self.increment(retry)


class MethodErrorTest(FastmailCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(jmap_module, "_pause")
        self.pause = patcher.start()
        self.addCleanup(patcher.stop)

    def error(self, kind):
        self.reply("error", {"type": kind})

    def ok(self, name="Thing/get", result=None):
        self.reply(name, {"list": [1]} if result is None else result)

    def test_a_busy_server_error_on_a_read_is_retried_after_a_pause(self):
        for kind in ("serverFail", "serverUnavailable", "rateLimit"):
            with self.subTest(kind=kind):
                self.pause.reset_mock()
                self.error(kind)
                self.ok()
                result = invoke(CREDS, ["u"], "Thing/get", {})
                self.assertEqual(result, {"list": [1]})
                self.pause.assert_called_once()

    def test_a_read_gives_up_after_the_limit_with_the_reason(self):
        for _ in range(10):
            self.error("serverFail")
        with self.assertRaisesRegex(RuntimeError, "serverFail"):
            invoke(CREDS, ["u"], "Thing/get", {})
        self.assertEqual(self.pause.call_count, jmap_module.MAX_RETRIES)

    def test_a_write_is_retried_only_when_rate_limited(self):
        self.error("rateLimit")
        self.ok("Thing/set", {})
        self.assertEqual(invoke(CREDS, ["u"], "Thing/set", {}), {})
        self.error("serverFail")
        self.ok("Thing/set", {})
        with self.assertRaisesRegex(RuntimeError, "serverFail"):
            invoke(CREDS, ["u"], "Thing/set", {})

    def test_other_errors_are_not_retried_and_carry_their_type(self):
        self.error("forbidden")
        self.ok()
        with self.assertRaises(jmap_module.MethodError) as raised:
            invoke(CREDS, ["u"], "Thing/get", {})
        self.assertEqual(raised.exception.type, "forbidden")
        self.pause.assert_not_called()

    def test_pauses_grow_and_are_jittered(self):
        self.assertTrue(0 < jmap_module.backoff(1) <= 1.0)
        self.assertTrue(1.0 <= jmap_module.backoff(2) <= 2.0)
        self.assertLessEqual(jmap_module.backoff(30), jmap_module.MAX_BACKOFF_SECONDS)


class ReadOnlyTest(unittest.TestCase):
    def test_gets_and_reading_methods_can_be_repeated(self):
        self.assertTrue(jmap_module.is_read_only(None))
        for name in ("SieveBlocks/get", "Mailbox/get", "Validate/sieve", "X/query"):
            with self.subTest(name=name):
                self.assertTrue(
                    jmap_module.is_read_only({"methodCalls": [[name, {}, "0"]]})
                )

    def test_writes_and_the_unknown_are_never_repeated(self):
        for body in (
            {"methodCalls": [["SieveBlocks/set", {}, "0"]]},
            {"methodCalls": [["Mailbox/get", {}, "0"], ["X/set", {}, "1"]]},
            {"methodCalls": []},
            {},
            "nonsense",
        ):
            with self.subTest(body=body):
                self.assertFalse(jmap_module.is_read_only(body))


class ScriptedServer(ThreadingHTTPServer):
    """A local server that answers from a script and remembers what it was asked."""

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.seen: list = []
        self.script: list = []


class Scripted(BaseHTTPRequestHandler):
    def _answer(self):
        server = cast(ScriptedServer, self.server)
        length = int(self.headers.get("Content-Length") or 0)
        server.seen.append((self.command, self.rfile.read(length)))
        status, headers, body = server.script.pop(0)
        if status is None:  # drop the connection without answering
            self.connection.close()
            return
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, format, *args):
        pass


class RetryTest(unittest.TestCase):
    """The real urllib3 retry machinery against a local server (http only here;
    `_check_url` is bypassed because the guard itself is tested above)."""

    def setUp(self):
        jmap_module._sessions_by_policy.clear()
        self.addCleanup(jmap_module._sessions_by_policy.clear)
        self.server = ScriptedServer(("127.0.0.1", 0), Scripted)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/x"
        patcher = mock.patch.object(jmap_module, "_check_url")
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch("urllib3.util.retry.time.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def script(self, *steps):
        self.server.script[:] = [
            (
                status,
                headers or {},
                json.dumps(body).encode() if body is not None else b"",
            )
            for status, headers, body in steps
        ]

    def call(self, body):
        for read_only in (True, False):
            session = jmap_module._http(read_only)
            session.mount(
                "http://",
                jmap_module.HTTPAdapter(max_retries=jmap_module._policy(read_only)),
            )
        return jmap(self.url, CREDS, body)

    def test_a_busy_server_is_retried_and_its_retry_after_is_obeyed(self):
        self.script(
            (503, {"Retry-After": "7"}, None),
            (429, {"Retry-After": "2"}, None),
            (200, None, {"ok": True}),
        )
        self.assertEqual(self.call(READ), {"ok": True})
        self.assertEqual(len(self.server.seen), 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [7, 2])

    def test_a_retry_after_cannot_make_us_wait_for_ever(self):
        policy = jmap_module._policy(True)
        response = mock.Mock(headers={"Retry-After": "86400"})
        self.assertEqual(
            policy.get_retry_after(response), jmap_module.MAX_RETRY_AFTER_SECONDS
        )

    def test_backoff_grows_and_is_never_zero_between_attempts(self):
        policy = jmap_module._policy(True)
        waits = []
        for tries in (1, 2, 3, 4, 9):
            policy.history = (object(),) * tries
            waits.append(policy.get_backoff_time())
        self.assertTrue(all(w > 0 for w in waits))
        self.assertLessEqual(waits[0], 1.0)
        self.assertLessEqual(waits[1], 2.0)
        self.assertLessEqual(waits[-1], jmap_module.MAX_BACKOFF_SECONDS)

    def test_a_read_gives_up_after_the_limit_and_says_the_server_is_busy(self):
        self.script(*[(503, None, None)] * 10)
        with self.assertRaisesRegex(RuntimeError, "HTTP 503.*still busy"):
            self.call(READ)
        self.assertEqual(len(self.server.seen), 1 + jmap_module.MAX_RETRIES)

    def test_a_client_error_is_not_retried(self):
        self.script((400, None, {"type": "x"}), (200, None, {"ok": True}))
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            self.call(READ)
        self.assertEqual(len(self.server.seen), 1)

    def test_a_read_is_retried_after_a_dropped_connection(self):
        self.script((None, None, None), (200, None, {"ok": True}))
        self.assertEqual(self.call(READ), {"ok": True})
        self.assertEqual(len(self.server.seen), 2)
        self.assertGreater(self.sleep.call_args.args[0], 0)

    def test_a_write_is_retried_on_429_only(self):
        self.script((429, {"Retry-After": "1"}, None), (200, None, {"ok": True}))
        self.assertEqual(self.call(WRITE), {"ok": True})
        self.assertEqual(len(self.server.seen), 2)

    def test_a_write_is_not_retried_on_503(self):
        self.script((503, None, None), (200, None, {"ok": True}))
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            self.call(WRITE)
        self.assertEqual(len(self.server.seen), 1)

    def test_a_write_is_not_repeated_when_the_answer_is_lost(self):
        self.script((None, None, None), (200, None, {"ok": True}))
        with self.assertRaisesRegex(RuntimeError, "Could not reach Fastmail"):
            self.call(WRITE)
        self.assertEqual(len(self.server.seen), 1)


if __name__ == "__main__":
    unittest.main()
