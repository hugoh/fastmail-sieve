from pathlib import Path

from fastmail_sieve import config
from fastmail_sieve.fastmail.blocks import NO_BLOCKS, get_script
from fastmail_sieve.fastmail.credentials import gather, pick
from fastmail_sieve.fastmail.jmap import get_session, jmap
from fastmail_sieve.fastmail.mailboxes import fetch_mailboxes
from fastmail_sieve.sieve.script import fragment_files
from fastmail_sieve.steps import Result, Step, require

OFFICIAL_SIEVE = "urn:ietf:params:jmap:sieve"
RULES = "https://www.fastmail.com/dev/rules"
TIERS = (("session token + cookie", "session"), ("API token", "api"))


def _count(count, noun):
    return f"{count} {noun}{'' if count == 1 else 's'}"


class Doctor:
    """Checks, in the order a first-time user would hit problems. Details name
    sources and tiers, never values."""

    def __init__(self, call=jmap):
        self.call = call
        self.sources = []
        self.session = None
        self.remote = None

    def project(self):
        files = fragment_files()
        problems = [f"{name} is missing" for name in files if not Path(name).is_file()]
        variables = config.current().variables_file
        if not Path(variables).is_file():
            problems.append(f"{variables} is missing")
        if problems:
            problems.append("create what is missing with `fastmail-sieve init`")
        return Result(errors=problems, detail=f"{len(files)} fragments, {variables}")

    def credentials(self):
        self.sources = gather()
        if not self.sources:
            pick([])
        found = [
            f"{name}: " + " and ".join(label for label, key in TIERS if tiers[key])
            for name, tiers in self.sources
        ]
        return Result(detail="; ".join(found))

    def reachable(self):
        chosen = pick(self.sources, session_required=False)
        self.session = get_session(chosen, self.call)
        user = self.session.get("username", "an unknown user")
        what = "API token" if chosen["kind"] == "api" else "session token + cookie"
        return Result(
            detail=f"signed in as {user} using the {what} from {chosen['source']}"
        )

    def official_api(self):
        advertised = OFFICIAL_SIEVE in require(self.session, "The session").get(
            "capabilities", {}
        )
        if advertised:
            return Result(detail="advertised: an official backend may be possible")
        return Result(
            detail="not advertised: using Fastmail's private SieveBlocks methods"
        )

    def folders(self):
        boxes = fetch_mailboxes(pick(self.sources, session_required=False), self.call)
        return Result(detail=_count(len(boxes), "folder"))

    def script(self):
        chosen = pick(self.sources, session_required=True)
        if self.session is not None and RULES not in self.session.get(
            "capabilities", {}
        ):
            return Result(
                errors=[
                    "Fastmail did not offer the rules capability to these credentials"
                ]
            )
        self.remote = get_script(chosen, self.call)
        return Result(detail=_count(len(self.remote.text), "byte"))

    def blocks(self):
        if not require(self.remote, "The script").has_markers:
            return Result(errors=[NO_BLOCKS])
        return Result(detail="start, middle and end")


def doctor_steps(doctor):
    return [
        Step("Project files found", doctor.project),
        Step("Credentials found", doctor.credentials),
        Step("Fastmail accepts the credentials", doctor.reachable, slow=True),
        Step("Official Sieve API (RFC 9661)", doctor.official_api),
        Step("Folders readable", doctor.folders, slow=True),
        Step("Sieve script readable", doctor.script, slow=True),
        Step("Managed blocks present", doctor.blocks),
    ]
