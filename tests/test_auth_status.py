import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from fastmail_sieve.cli import build_parser, main
from fastmail_sieve.fastmail.credentials import SourceStatus, inspect_sources

SECRETS = ("fma1-SECRETTOKEN", "__Http-s_SECRETCOOKIE=1", "SECRETAPITOKEN")
SESSION_ENV = {
    "FASTMAIL_SIEVE_TOKEN": SECRETS[0],
    "FASTMAIL_SIEVE_COOKIE": SECRETS[1],
}
KEYCHAIN = {"username": "me@example.com", "token": SECRETS[0], "cookie": SECRETS[1]}
EMPTY_KEYCHAIN = {"username": None, "token": None, "cookie": None}


def keychain(values):
    return lambda: values


def command_run(payload=None, returncode=0, stdout=None):
    text = stdout if stdout is not None else json.dumps(payload)
    return mock.Mock(
        return_value=subprocess.CompletedProcess([], returncode, text, None)
    )


def inspect(environ, values=EMPTY_KEYCHAIN, run=None):
    kwargs = {"run": run} if run else {}
    return {
        s.name: s
        for s in inspect_sources(environ=environ, keychain=keychain(values), **kwargs)
    }


class InspectSourcesTest(unittest.TestCase):
    def test_the_sources_come_in_precedence_order_even_when_nothing_is_set(self):
        statuses = inspect_sources(environ={}, keychain=keychain(EMPTY_KEYCHAIN))
        self.assertEqual(
            [s.name for s in statuses],
            ["environment", "credential command", "keychain"],
        )
        self.assertEqual({s.state for s in statuses}, {"not set"})

    def test_a_complete_session_pair_in_the_environment(self):
        status = inspect(SESSION_ENV)["environment"]
        self.assertEqual((status.state, status.tiers), ("found", ("session",)))
        self.assertIn("FASTMAIL_SIEVE_TOKEN", status.detail)
        self.assertIn("FASTMAIL_SIEVE_COOKIE", status.detail)

    def test_an_api_token_in_the_environment(self):
        status = inspect({"FASTMAIL_API_TOKEN": SECRETS[2]})["environment"]
        self.assertEqual((status.state, status.tiers), ("found", ("api",)))
        self.assertIn("FASTMAIL_API_TOKEN", status.detail)

    def test_a_token_without_its_cookie_is_incomplete_and_says_what_is_missing(self):
        status = inspect({"FASTMAIL_SIEVE_TOKEN": SECRETS[0]})["environment"]
        self.assertEqual((status.state, status.tiers), ("incomplete", ()))
        self.assertIn("FASTMAIL_SIEVE_COOKIE is missing", status.detail)

    def test_a_cookie_without_its_token_is_incomplete_too(self):
        status = inspect({"FASTMAIL_SIEVE_COOKIE": SECRETS[1]})["environment"]
        self.assertEqual(status.state, "incomplete")
        self.assertIn("FASTMAIL_SIEVE_TOKEN is missing", status.detail)

    def test_an_api_token_beside_half_a_session_still_counts_as_found(self):
        environ = {"FASTMAIL_API_TOKEN": SECRETS[2], "FASTMAIL_SIEVE_TOKEN": SECRETS[0]}
        status = inspect(environ)["environment"]
        self.assertEqual((status.state, status.tiers), ("found", ("api",)))
        self.assertIn("FASTMAIL_SIEVE_COOKIE is missing", status.detail)

    def test_a_working_command_reports_what_it_provides(self):
        run = command_run({"token": SECRETS[0], "cookie": SECRETS[1], "api_token": "x"})
        status = inspect({"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"}, run=run)[
            "credential command"
        ]
        self.assertEqual((status.state, status.tiers), ("found", ("session", "api")))

    def test_a_failing_command_is_reported_not_raised_and_never_echoed(self):
        run = command_run({"token": SECRETS[0]}, returncode=3)
        status = inspect({"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"}, run=run)[
            "credential command"
        ]
        self.assertEqual(status.state, "failed")
        self.assertIn("exit status 3", status.detail)

    def test_a_command_that_prints_nothing_usable_is_incomplete(self):
        run = command_run({"username": "me"})
        status = inspect({"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"}, run=run)[
            "credential command"
        ]
        self.assertEqual(status.state, "incomplete")

    def test_a_command_that_is_not_json_is_reported_without_its_output(self):
        run = command_run(stdout=f"{SECRETS[0]} not json")
        status = inspect({"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"}, run=run)[
            "credential command"
        ]
        self.assertEqual(status.state, "failed")
        self.assertNotIn(SECRETS[0], status.detail)

    def test_the_keychain_reports_the_stored_user(self):
        status = inspect({}, KEYCHAIN)["keychain"]
        self.assertEqual((status.state, status.tiers), ("found", ("session",)))
        self.assertIn("me@example.com", status.detail)

    def test_a_half_stored_keychain_is_incomplete(self):
        status = inspect({}, {**EMPTY_KEYCHAIN, "token": SECRETS[0]})["keychain"]
        self.assertEqual(status.state, "incomplete")
        self.assertIn("fastmail-sieve auth", status.detail)

    def test_no_keychain_backend_is_unavailable(self):
        status = inspect({}, None)["keychain"]
        self.assertEqual(status.state, "unavailable")
        self.assertIn("keychain", status.detail)

    def test_an_empty_keychain_says_how_to_fill_it(self):
        status = inspect({}, EMPTY_KEYCHAIN)["keychain"]
        self.assertEqual(status.state, "not set")
        self.assertIn("fastmail-sieve auth", status.detail)

    def test_no_status_ever_contains_a_secret(self):
        run = command_run({"token": SECRETS[0], "cookie": SECRETS[1]})
        environ = {
            **SESSION_ENV,
            "FASTMAIL_API_TOKEN": SECRETS[2],
            "FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper --secret SECRETARG",
        }
        for status in inspect_sources(
            environ=environ, keychain=keychain(KEYCHAIN), run=run
        ):
            shown = f"{status.name} {status.state} {status.tiers} {status.detail}"
            for secret in (*SECRETS, "SECRETARG"):
                self.assertNotIn(secret, shown)


def found(*tiers, username=None):
    found_tiers = {
        "session": {"token": "t", "cookie": "c", "username": username},
        "api": {"token": "a", "cookie": None, "username": None},
    }
    return {
        kind: found_tiers.get(kind) if kind in tiers else None
        for kind in ("session", "api")
    }


def status(name, state, tiers=(), detail="", credentials=None):
    return SourceStatus(name, state, tiers, detail, credentials)


NOTHING = [
    status(
        "environment",
        "not set",
        detail="set FASTMAIL_SIEVE_TOKEN and FASTMAIL_SIEVE_COOKIE",
    ),
    status(
        "credential command", "not set", detail="set FASTMAIL_SIEVE_CREDENTIAL_COMMAND"
    ),
    status("keychain", "not set", detail="nothing stored: run `fastmail-sieve auth`"),
]
KEYCHAIN_ONLY = [
    NOTHING[0],
    NOTHING[1],
    status(
        "keychain", "found", ("session",), "stored for me@example.com", found("session")
    ),
]
API_ONLY = [
    status("environment", "found", ("api",), "FASTMAIL_API_TOKEN", found("api")),
    NOTHING[1],
    NOTHING[2],
]
BOTH_IN_ORDER = [
    status("environment", "found", ("api",), "FASTMAIL_API_TOKEN", found("api")),
    NOTHING[1],
    status(
        "keychain", "found", ("session",), "stored for me@example.com", found("session")
    ),
]


def run_status(statuses):
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch(
            "fastmail_sieve.commands.auth.inspect_sources", return_value=statuses
        ),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = main(["auth", "status"])
    return code, out.getvalue()


class StatusCommandTest(unittest.TestCase):
    def test_it_is_a_subcommand_and_plain_auth_is_unchanged(self):
        parser = build_parser()
        self.assertTrue(parser.parse_args(["auth", "--stdin"]).stdin)
        self.assertEqual(parser.parse_args(["auth", "status"]).auth_command, "status")
        self.assertIsNone(parser.parse_args(["auth"]).auth_command)

    def test_it_lists_every_source_in_order_with_its_state(self):
        _, output = run_status(KEYCHAIN_ONLY)
        lines = output.splitlines()
        positions = [
            next(
                i for i, line in enumerate(lines) if name in line and "Used" not in line
            )
            for name in ("environment", "credential command", "keychain")
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("not set", output)
        self.assertIn("session token + cookie", output)
        self.assertIn("stored for me@example.com", output)

    def test_it_says_what_each_kind_of_command_will_use_and_from_where(self):
        code, output = run_status(KEYCHAIN_ONLY)
        self.assertEqual(code, 0)
        script = next(
            line for line in output.splitlines() if line.lstrip().startswith("script")
        )
        folders = next(
            line for line in output.splitlines() if line.lstrip().startswith("folders")
        )
        self.assertIn("session token + cookie from keychain", script)
        self.assertIn("session token + cookie from keychain", folders)

    def test_folders_prefer_an_api_token_but_the_script_needs_the_session(self):
        _, output = run_status(BOTH_IN_ORDER)
        lines = output.splitlines()
        script = next(line for line in lines if line.lstrip().startswith("script"))
        folders = next(line for line in lines if line.lstrip().startswith("folders"))
        self.assertIn("session token + cookie from keychain", script)
        self.assertIn("API token from environment", folders)

    def test_an_api_token_alone_cannot_do_the_script(self):
        code, output = run_status(API_ONLY)
        self.assertEqual(code, 0)
        script = next(
            line for line in output.splitlines() if line.lstrip().startswith("script")
        )
        self.assertIn("not available", script)
        self.assertIn("API token", script)
        self.assertIn("fastmail-sieve auth", script)

    def test_with_nothing_available_it_says_so_and_fails(self):
        code, output = run_status(NOTHING)
        self.assertEqual(code, 1)
        self.assertEqual(output.count("not available"), 2)
        self.assertIn("fastmail-sieve auth", output)

    def test_problems_are_shown_with_their_reason(self):
        broken = [
            status(
                "environment", "incomplete", detail="FASTMAIL_SIEVE_COOKIE is missing"
            ),
            status("credential command", "failed", detail="exit status 3"),
            status("keychain", "unavailable", detail="no usable keychain backend here"),
        ]
        code, output = run_status(broken)
        self.assertEqual(code, 1)
        for text in (
            "FASTMAIL_SIEVE_COOKIE is missing",
            "exit status 3",
            "no usable keychain",
        ):
            self.assertIn(text, output)

    def test_it_never_prints_a_credential_value(self):
        creds = {
            "token": SECRETS[0],
            "cookie": SECRETS[1],
            "username": "me@example.com",
        }
        statuses = [
            status(
                "environment",
                "found",
                ("session",),
                "FASTMAIL_SIEVE_TOKEN, FASTMAIL_SIEVE_COOKIE",
                {
                    "session": creds,
                    "api": {"token": SECRETS[2], "cookie": None, "username": None},
                },
            ),
            NOTHING[1],
            NOTHING[2],
        ]
        _, output = run_status(statuses)
        for secret in SECRETS:
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
