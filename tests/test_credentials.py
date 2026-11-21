import json
import subprocess
import unittest
from unittest import mock

from fastmail_sieve.fastmail.credentials import (
    LazySources,
    check_credentials,
    gather,
    load_credentials,
    pick,
)

SESSION_ENV = {
    "FASTMAIL_SIEVE_TOKEN": "fma1-env",
    "FASTMAIL_SIEVE_COOKIE": "__Http-s_e=1",
}
KEYCHAIN = {"username": "me@example.com", "token": "fma1-key", "cookie": "__Http-s_k=2"}


def keychain(values=KEYCHAIN):
    return lambda: values


def command_result(payload, returncode=0):
    return mock.Mock(
        return_value=subprocess.CompletedProcess(
            [], returncode, json.dumps(payload), None
        )
    )


class CheckCredentialsTest(unittest.TestCase):
    def test_complete_credentials_pass(self):
        self.assertEqual(check_credentials(KEYCHAIN), KEYCHAIN)

    def test_missing_values_name_the_fix(self):
        with self.assertRaisesRegex(RuntimeError, r"token.*fastmail-sieve auth"):
            check_credentials({**KEYCHAIN, "token": None})

    def test_an_empty_value_counts_as_missing(self):
        with self.assertRaisesRegex(RuntimeError, "cookie"):
            check_credentials({**KEYCHAIN, "cookie": ""})

    def test_the_username_is_informational_and_not_required(self):
        self.assertTrue(check_credentials({"token": "t", "cookie": "c"}))


class GatherTest(unittest.TestCase):
    def test_environment_session_credentials(self):
        [(source, found)] = gather(environ=SESSION_ENV, keychain=keychain(None))
        self.assertEqual(source, "environment")
        self.assertEqual(
            (found["session"]["token"], found["session"]["cookie"]),
            ("fma1-env", "__Http-s_e=1"),
        )
        self.assertIsNone(found["api"])

    def test_an_api_token_is_its_own_tier(self):
        [(source, found)] = gather(
            environ={"FASTMAIL_API_TOKEN": "api-1"}, keychain=keychain(None)
        )
        self.assertEqual(
            (source, found["api"]["token"], found["api"]["cookie"]),
            ("environment", "api-1", None),
        )
        self.assertIsNone(found["session"])

    def test_a_token_without_a_cookie_is_not_a_session(self):
        self.assertEqual(
            gather(environ={"FASTMAIL_SIEVE_TOKEN": "t"}, keychain=keychain(None)), []
        )

    def test_the_keychain_is_a_source(self):
        [(source, found)] = gather(environ={}, keychain=keychain())
        self.assertEqual((source, found["session"]["token"]), ("keychain", "fma1-key"))

    def test_a_missing_keychain_backend_is_not_an_error(self):
        self.assertEqual(gather(environ={}, keychain=keychain(None)), [])

    def test_the_command_prints_json(self):
        run = command_result(
            {"token": "fma1-cmd", "cookie": "c=1", "api_token": "api-cmd"}
        )
        [(source, found)] = gather(
            environ={"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "op read-fastmail"},
            keychain=keychain(None),
            run=run,
        )
        self.assertEqual(source, "credential command")
        self.assertEqual(
            (found["session"]["token"], found["api"]["token"]), ("fma1-cmd", "api-cmd")
        )
        self.assertEqual(run.call_args.args[0], ["op", "read-fastmail"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_a_failing_command_reports_the_exit_code_and_never_its_output(self):
        run = command_result({"token": "fma1-SECRET"}, returncode=3)
        with self.assertRaises(RuntimeError) as raised:
            gather(
                environ={"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "x"},
                keychain=keychain(None),
                run=run,
            )
        self.assertIn("exit status 3", str(raised.exception))
        self.assertNotIn("SECRET", str(raised.exception))

    def test_invalid_command_output_is_reported_without_echoing_it(self):
        run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [], 0, "fma1-SECRET not json", None
            )
        )
        with self.assertRaises(RuntimeError) as raised:
            gather(
                environ={"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "x"},
                keychain=keychain(None),
                run=run,
            )
        self.assertIn("JSON", str(raised.exception))
        self.assertNotIn("SECRET", str(raised.exception))

    def test_a_missing_executable_is_reported(self):
        run = mock.Mock(side_effect=FileNotFoundError("nope"))
        with self.assertRaisesRegex(RuntimeError, "could not be run"):
            gather(
                environ={"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "x"},
                keychain=keychain(None),
                run=run,
            )

    def test_sources_come_in_precedence_order(self):
        run = command_result({"token": "t", "cookie": "c"})
        sources = gather(
            environ={**SESSION_ENV, "FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "x"},
            keychain=keychain(),
            run=run,
        )
        self.assertEqual(
            [name for name, _ in sources],
            ["environment", "credential command", "keychain"],
        )


class PickTest(unittest.TestCase):
    def sources(self, **env):
        return gather(environ=env, keychain=keychain())

    def test_the_script_needs_the_session_pair(self):
        self.assertEqual(
            pick(self.sources(**SESSION_ENV), session_required=True)["token"],
            "fma1-env",
        )

    def test_the_environment_beats_the_keychain(self):
        self.assertEqual(pick(self.sources(**SESSION_ENV))["source"], "environment")

    def test_folders_prefer_an_api_token_over_the_session(self):
        chosen = pick(
            self.sources(**SESSION_ENV, FASTMAIL_API_TOKEN="api-1"),
            session_required=False,
        )
        self.assertEqual((chosen["token"], chosen["kind"]), ("api-1", "api"))

    def test_folders_fall_back_to_the_session(self):
        chosen = pick(self.sources(), session_required=False)
        self.assertEqual(
            (chosen["token"], chosen["kind"], chosen["source"]),
            ("fma1-key", "session", "keychain"),
        )

    def test_an_api_token_alone_cannot_do_the_script(self):
        with self.assertRaisesRegex(
            RuntimeError, r"API token cannot.*Sieve script.*fastmail-sieve auth"
        ):
            pick(
                gather(environ={"FASTMAIL_API_TOKEN": "api-1"}, keychain=keychain(None))
            )

    def test_nothing_found_lists_every_way_to_provide_credentials(self):
        with self.assertRaises(RuntimeError) as raised:
            pick([])
        message = str(raised.exception)
        for needle in (
            "fastmail-sieve auth",
            "FASTMAIL_SIEVE_TOKEN",
            "FASTMAIL_SIEVE_COOKIE",
            "FASTMAIL_SIEVE_CREDENTIAL_COMMAND",
        ):
            self.assertIn(needle, message)
        self.assertNotIn("FASTMAIL_API_TOKEN", message)

    def test_nothing_found_for_folders_also_mentions_the_api_token(self):
        with self.assertRaisesRegex(RuntimeError, "FASTMAIL_API_TOKEN"):
            pick([], session_required=False)

    def test_the_picked_credentials_carry_no_stray_fields(self):
        chosen = pick(self.sources(**SESSION_ENV))
        self.assertEqual(set(chosen), {"token", "cookie", "username", "source", "kind"})


class LazySourcesTest(unittest.TestCase):
    ENV_AND_STALE_HELPER = {**SESSION_ENV, "FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "false"}

    def test_a_working_environment_never_touches_the_helper_or_the_keychain(self):
        run = mock.Mock()
        read = mock.Mock(return_value=KEYCHAIN)
        sources = LazySources(environ=self.ENV_AND_STALE_HELPER, keychain=read, run=run)
        self.assertEqual(pick(sources)["source"], "environment")
        run.assert_not_called()
        read.assert_not_called()

    def test_a_stale_helper_command_does_not_break_a_run_that_has_the_login(self):
        failing = command_result({"token": "x"}, returncode=1)
        sources = LazySources(
            environ=self.ENV_AND_STALE_HELPER, keychain=keychain(None), run=failing
        )
        self.assertEqual(pick(sources)["token"], "fma1-env")

    def test_later_sources_are_read_only_when_the_earlier_ones_have_nothing(self):
        read = mock.Mock(return_value=KEYCHAIN)
        self.assertEqual(
            pick(LazySources(environ={}, keychain=read))["source"], "keychain"
        )
        read.assert_called_once()

    def test_what_was_read_is_remembered_across_picks(self):
        read = mock.Mock(return_value=KEYCHAIN)
        sources = LazySources(environ={}, keychain=read)
        pick(sources)
        pick(sources, session_required=False)
        list(sources)
        read.assert_called_once()

    def test_folders_prefer_an_api_token_so_a_later_source_may_be_needed(self):
        run = command_result({"api_token": "api-cmd"})
        sources = LazySources(
            environ={**SESSION_ENV, "FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"},
            keychain=keychain(None),
            run=run,
        )
        chosen = pick(sources, session_required=False)
        self.assertEqual(
            (chosen["kind"], chosen["source"]), ("api", "credential command")
        )
        run.assert_called_once()

    def test_a_failing_helper_is_still_an_error_when_it_is_reached(self):
        failing = command_result({}, returncode=3)
        sources = LazySources(
            environ={"FASTMAIL_SIEVE_CREDENTIAL_COMMAND": "helper"},
            keychain=keychain(KEYCHAIN),
            run=failing,
        )
        with self.assertRaisesRegex(RuntimeError, "exit status 3"):
            pick(sources)


class LoadCredentialsTest(unittest.TestCase):
    def test_reads_environment_then_keychain(self):
        with mock.patch(
            "fastmail_sieve.fastmail.credentials.read_keychain", return_value=KEYCHAIN
        ):
            self.assertEqual(
                load_credentials(environ=SESSION_ENV)["source"], "environment"
            )
            self.assertEqual(load_credentials(environ={})["source"], "keychain")


if __name__ == "__main__":
    unittest.main()
