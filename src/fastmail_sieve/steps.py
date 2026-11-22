from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from fastmail_sieve.fastmail.blocks import (
    CHANGED,
    get_script,
    set_blocks,
    validate_sieve,
)
from fastmail_sieve.fastmail.credentials import LazySources, pick
from fastmail_sieve.fastmail.mailboxes import check_ids, check_names, fetch_mailboxes
from fastmail_sieve.sieve.format import format_errors, format_files
from fastmail_sieve.sieve.lint import check_fragments, check_markers, check_syntax
from fastmail_sieve.sieve.report import build_rules, disabled_ui_rules
from fastmail_sieve.sieve.script import assemble, live_fragments
from fastmail_sieve.sieve.variables import load_report, load_variable_docs
from fastmail_sieve.sieve.warnings import collect_warnings

LIVE_SCRIPT = "Fastmail's script"


@dataclass
class Result:
    errors: list = field(default_factory=list)
    detail: str | None = None
    warnings: list = field(default_factory=list)


@dataclass
class Step:
    name: str
    action: object
    slow: bool = False


def run_steps(steps, console):
    for step in steps:
        try:
            progress = console.status(f"{step.name}…") if step.slow else nullcontext()
            with progress:
                result = step.action()
        except Exception as error:
            result = Result(errors=[str(error)])
        if result.errors:
            console.print(f"✗ {step.name}", style="red", markup=False)
            for error in result.errors:
                console.print(f"    {error}", markup=False)
            return 1
        if result.warnings:
            console.print(f"! {step.name}", style="yellow", markup=False)
            for warning in result.warnings:
                console.print(f"    {warning}", markup=False)
        else:
            console.print(f"✓ {step.name}", style="green", markup=False)
        if result.detail:
            console.print(f"    {result.detail}", style="dim", markup=False)
    return 0


def require(value, what):
    """A value an earlier step sets; fail clearly if that step has not run."""
    if value is None:
        raise RuntimeError(f"{what} has not been read yet: run the earlier step first")
    return value


def _errors(error):
    return [error] if error else []


class Session:
    """One run's view of Fastmail: the remote script, your assembled script, and
    the steps that read or write them."""

    def __init__(self, project, live=False):
        self.project = project
        self.live = live
        self.script = None
        self.remote = None
        self.assembled = None
        self._sources = None

    def format_rules(self):
        names = self.project.fragment_files
        changed = format_files([self.project.path(name) for name in names])
        if changed:
            shown = [
                Path(path).relative_to(self.project.root).as_posix() for path in changed
            ]
            return Result(detail="reformatted " + ", ".join(shown))
        return Result(detail="already formatted")

    def lint_fragments(self):
        fragments = self.project.read_fragments()
        files = dict(zip(self.project.fragment_files, fragments, strict=True))
        errors = format_errors(files)
        error = check_fragments(*fragments)
        return Result(errors=[*errors, *([error] if error else [])])

    def credentials(self, session_required=True):
        if self._sources is None:
            self._sources = LazySources()
        return pick(self._sources, session_required)

    def fetch(self):
        self.script = get_script(self.credentials())
        self.remote = self.script.text
        return Result()

    def read_file(self, path):
        self.remote = Path(path).read_text(encoding="utf-8")
        return Result()

    def assemble(self):
        if self.live:
            self.assembled = self.remote
        else:
            self.assembled = assemble(self.remote, *self.project.read_fragments())
        return Result()

    def fragment_texts(self):
        """The three fragments being judged: your files, or the live blocks."""
        return (
            live_fragments(self.assembled)
            if self.live
            else self.project.read_fragments()
        )

    def rules_files(self):
        """name -> text of the rules being judged."""
        return dict(
            zip(self.project.fragment_files, self.fragment_texts(), strict=True)
        )

    def folder_sources(self):
        """name -> text to look for folder references in."""
        if self.live:
            return {LIVE_SCRIPT: self.assembled}
        return self.rules_files()

    def check_syntax(self):
        return Result(errors=_errors(check_syntax(self.assembled)))

    def validate(self):
        return Result(
            errors=_errors(validate_sieve(self.credentials(), self.assembled))
        )

    def check_markers(self):
        return Result(errors=_errors(check_markers(self.assembled)))

    def _variable_report(self):
        return load_report(self.project, self.assembled, self.fragment_texts())

    def check_variables(self):
        return Result(errors=self._variable_report().errors)

    def warnings(self, strict=False):
        rules = build_rules(
            self.rules_files(), self.assembled, load_variable_docs(self.project)
        )
        found = collect_warnings(
            rules, disabled_ui_rules(self.assembled), self._variable_report().warnings
        )
        lines = [f"{kind}: {text}" for kind, text in found]
        if strict and lines:
            return Result(errors=lines)
        return Result(warnings=lines, detail=None if lines else "none")

    def push(self):
        script = require(self.script, "The remote script")
        updated = script.with_fragments(*self.project.read_fragments())
        if updated.same_blocks(script):
            return Result(detail="no change; nothing to push")
        if not get_script(self.credentials()).same_blocks(script):
            return Result(errors=[CHANGED])
        set_blocks(self.credentials(), updated)
        return Result(detail="pushed the managed blocks")

    def verify(self):
        if not get_script(self.credentials()).matches(self.project.read_fragments()):
            return Result(
                errors=["Fastmail's managed blocks differ from the local fragments"]
            )
        return Result()


class FolderChecks:
    """The two folder steps share one read of Fastmail's folders."""

    def __init__(self, session):
        self._session = session
        self._mailboxes = None

    def _fragments(self):
        if self._mailboxes is None:
            self._mailboxes = fetch_mailboxes(
                self._session.credentials(session_required=False)
            )
        return self._mailboxes, self._session.folder_sources()

    def check_ids(self):
        count, problems = check_ids(*self._fragments())
        return Result(
            errors=problems,
            detail=_count(count, "stable id exists", "stable ids exist"),
        )

    def check_names(self):
        count, problems = check_names(*self._fragments())
        return Result(
            errors=problems,
            detail=_count(count, "folder name matches", "folder names match"),
        )


def _count(count, one, many):
    return f"{count} {one if count == 1 else many}"


def lint_steps(
    project,
    session=None,
    *,
    offline=False,
    from_file=None,
    fix=False,
    strict=False,
    live=False,
):
    """Every check, in order. `offline` skips whatever needs Fastmail (everything
    but your rules, unless `from_file` supplies the script); `fix` formats first.
    `live` judges Fastmail's script as it is and never looks at your rules."""
    if live and fix:
        raise RuntimeError("--live checks Fastmail's script: --fix cannot change it")
    if live and offline and not from_file:
        raise RuntimeError(
            "--live needs Fastmail: give --from-file to check a saved copy"
        )
    session = session or Session(project, live=live)
    scope = "live script" if live else "assembled script"
    steps = [Step("Format your rules", session.format_rules)] if fix else []
    if not live:
        steps.append(
            Step("Valid format and syntax in your rules", session.lint_fragments)
        )
    if offline and not from_file:
        return steps
    if from_file:
        steps.append(
            Step("Read the saved script", lambda: session.read_file(from_file))
        )
    else:
        steps.append(
            Step("Fetch Fastmail's generated script", session.fetch, slow=True)
        )
    if not live:
        steps.append(Step("Assemble the full script", session.assemble))
    else:
        steps.append(Step("Use Fastmail's script as it is", session.assemble))
    steps += [
        Step(f"Valid syntax in the {scope}", session.check_syntax),
        Step(f"Valid markers in the {scope}", session.check_markers),
        Step("Valid variables", session.check_variables),
    ]
    if not offline:
        folders = FolderChecks(session)
        steps += [
            Step("Accepted by Fastmail's validator", session.validate, slow=True),
            Step("Valid folder stable ids", folders.check_ids, slow=True),
            Step("Valid folder names", folders.check_names),
        ]
    steps.append(Step("Warnings", lambda: session.warnings(strict)))
    return steps


def write_steps(session):
    return [
        Step("Push the managed blocks", session.push, slow=True),
        Step("Verify with a fresh pull", session.verify, slow=True),
    ]
