import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastmail_sieve.config import Project as RulesProject
from fastmail_sieve.doctor import Doctor, doctor_steps
from tests.support import SESSION as BASE_SESSION
from tests.support import FastmailCase
from tests.test_blocks import JSON

SESSION_TOKEN = "fma1-SECRETSESSIONTOKEN"
COOKIE = "__Http-s_SECRETCOOKIE=1"
API_TOKEN = "SECRETAPITOKEN"
BOXES = [{"id": "P1", "name": "home", "parentId": None, "role": None}]
SESSION = BASE_SESSION
BOTH = [
    (
        "keychain",
        {
            "session": {"token": SESSION_TOKEN, "cookie": COOKIE, "username": None},
            "api": None,
        },
    ),
    (
        "environment",
        {
            "session": None,
            "api": {"token": API_TOKEN, "cookie": None, "username": None},
        },
    ),
]
SESSION_ONLY = BOTH[:1]
API_ONLY = BOTH[1:]


class Project(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = os.getcwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, previous)


def doctor(sources):
    instance = Doctor(RulesProject(Path.cwd()))
    patcher = mock.patch("fastmail_sieve.doctor.gather", return_value=sources)
    patcher.start()
    return instance, patcher


class ProjectFilesTest(Project):
    def test_all_files_present(self):
        Path("rules").mkdir()
        for name in ("top", "middle", "bottom"):
            Path(f"rules/{name}.sieve").write_text("")
        Path("variables.toml").write_text("")
        result = Doctor(RulesProject(Path.cwd())).project()
        self.assertEqual(result.errors, [])
        self.assertIn("3 fragments", result.detail)

    def test_missing_files_are_listed_with_the_fix(self):
        Path("rules").mkdir()
        Path("rules/top.sieve").write_text("")
        result = Doctor(RulesProject(Path.cwd())).project()
        self.assertIn("rules/middle.sieve is missing", result.errors)
        self.assertIn("rules/bottom.sieve is missing", result.errors)
        self.assertTrue(any("fastmail-sieve init" in error for error in result.errors))


class NetworkStepsTest(FastmailCase):
    script = JSON

    def setUp(self):
        super().setUp()
        self.addCleanup(mock.patch.stopall)
        self.session = SESSION
        self.handler = self.answer

    def answer(self, body):
        method = body["methodCalls"][0][0]
        result = {"list": BOXES if method == "Mailbox/get" else [self.script]}
        return {"methodResponses": [[method, result, "0"]]}

    def test_credentials_are_described_by_source_and_tier_never_by_value(self):
        subject, _ = doctor(BOTH)
        result = subject.credentials()
        self.assertIn("keychain: session token + cookie", result.detail)
        self.assertIn("environment: API token", result.detail)
        for secret in (SESSION_TOKEN, COOKIE, API_TOKEN):
            self.assertNotIn(secret, result.detail)

    def test_no_credentials_explains_every_way_to_provide_them(self):
        subject, _ = doctor([])
        with self.assertRaisesRegex(RuntimeError, "fastmail-sieve auth"):
            subject.credentials()

    def test_the_session_check_names_the_user_and_the_credentials_used(self):
        subject, _ = doctor(BOTH)
        subject.credentials()
        result = subject.reachable()
        self.assertIn("me@example.com", result.detail)
        self.assertIn("API token from environment", result.detail)

    def test_the_official_api_is_reported_either_way(self):
        subject, _ = doctor(SESSION_ONLY)
        subject.credentials()
        subject.reachable()
        self.assertIn("not advertised", subject.official_api().detail)
        subject.session["capabilities"]["urn:ietf:params:jmap:sieve"] = {}
        self.assertIn("advertised", subject.official_api().detail)
        self.assertNotIn("not advertised", subject.official_api().detail)

    def test_folders_use_the_api_token_when_there_is_one(self):
        subject, _ = doctor(BOTH)
        subject.credentials()
        result = subject.folders()
        self.assertEqual(result.detail, "1 folder")
        self.assertIn((API_TOKEN, "Mailbox/get"), self.seen)

    def test_the_script_uses_the_session_pair_and_reports_its_size(self):
        subject, _ = doctor(BOTH)
        subject.credentials()
        result = subject.script()
        self.assertIn((SESSION_TOKEN, "SieveBlocks/get"), self.seen)
        self.assertRegex(result.detail, r"\d+ bytes")

    def test_the_size_counts_bytes_not_characters(self):
        multibyte = {**JSON, "sieveRequire": "# \u2328 \U0001f6d2 r\u00e9sum\u00e9"}
        self.script = multibyte
        subject, _ = doctor(BOTH)
        subject.credentials()
        result = subject.script()
        text = subject.remote.text
        self.assertGreater(len(text.encode("utf-8")), len(text))
        self.assertEqual(result.detail, f"{len(text.encode('utf-8'))} bytes")

    def test_an_api_token_alone_cannot_read_the_script(self):
        subject, _ = doctor(API_ONLY)
        subject.credentials()
        with self.assertRaisesRegex(RuntimeError, "API token cannot"):
            subject.script()

    def test_a_script_without_managed_blocks_says_how_to_add_them(self):
        bare = {**JSON, "sieveAtStart": "", "sieveAtMiddle": "", "sieveAtEnd": ""}
        self.script = bare
        subject, _ = doctor(SESSION_ONLY)
        subject.credentials()
        subject.script()
        self.assertTrue(
            any("init --remote" in error for error in subject.blocks().errors)
        )

    def test_managed_blocks_present(self):
        subject, _ = doctor(SESSION_ONLY)
        subject.credentials()
        subject.script()
        self.assertEqual(subject.blocks().errors, [])

    def test_no_step_ever_prints_a_secret(self):
        subject, _ = doctor(BOTH)
        details = []
        for step in doctor_steps(subject):
            details.append(step.action().detail or "")
        text = "\n".join(details)
        for secret in (SESSION_TOKEN, COOKIE, API_TOKEN):
            self.assertNotIn(secret, text)

    def test_the_checklist_names(self):
        self.assertEqual(
            [step.name for step in doctor_steps(Doctor(RulesProject(Path.cwd())))],
            [
                "Project files found",
                "Credentials found",
                "Fastmail accepts the credentials",
                "Official Sieve API (RFC 9661)",
                "Folders readable",
                "Sieve script readable",
                "Managed blocks present",
            ],
        )


if __name__ == "__main__":
    unittest.main()
