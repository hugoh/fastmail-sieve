"""A fake Fastmail at the HTTP level: the session document, and a JMAP API whose
answers a test scripts. Production code runs unchanged against it."""

import json
import unittest

import responses

from fastmail_sieve.fastmail import jmap as jmap_module
from fastmail_sieve.fastmail.jmap import MAIL, SESSION_URL

API = "https://api.fastmail.com/jmap/api/"
SESSION = {
    "username": "me@example.com",
    "apiUrl": API,
    "primaryAccounts": {MAIL: "u1"},
    "capabilities": {
        "urn:ietf:params:jmap:core": {},
        "https://www.fastmail.com/dev/rules": {},
    },
}


def answer(name, result, call_id="0"):
    """A JMAP response body holding one method response."""
    return {"methodResponses": [[name, result, call_id]]}


class FastmailCase(unittest.TestCase):
    """Starts a fake Fastmail for each test.

    `reply(...)` queues answers for successive API calls; `handler` answers every
    API call from its request body instead. `bodies` records the API requests and
    `seen` the (bearer token, method name) of each."""

    session = SESSION

    def setUp(self):
        super().setUp()
        for cache in (jmap_module._sessions, jmap_module._sessions_by_policy):
            cache.clear()
            self.addCleanup(cache.clear)
        self.bodies, self.seen, self.answers, self.handler = [], [], [], None
        self.http = responses.RequestsMock(assert_all_requests_are_fired=False)
        self.http.add_callback(responses.GET, SESSION_URL, callback=self._session)
        self.http.add_callback(responses.POST, API, callback=self._api)
        self.http.start()
        self.addCleanup(self.http.stop)
        self.addCleanup(self.http.reset)

    def reply(self, name, result, call_id="0"):
        self.answers.append(answer(name, result, call_id))

    def reply_raw(self, body):
        self.answers.append(body)

    def _session(self, request):
        return 200, {}, json.dumps(self.session)

    def _api(self, request):
        body = json.loads(request.body)
        self.bodies.append(body)
        token = request.headers["Authorization"].removeprefix("Bearer ")
        self.seen.append((token, body["methodCalls"][0][0]))
        reply = self.handler(body) if self.handler else self.answers.pop(0)
        return 200, {}, json.dumps(reply)
