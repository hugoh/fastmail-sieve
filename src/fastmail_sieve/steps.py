from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from fastmail_sieve.fastmail.blocks import CHANGED, get_script, set_blocks
from fastmail_sieve.fastmail.credentials import LazySources, pick
from fastmail_sieve.fastmail.mailboxes import check_ids, check_names, fetch_mailboxes
from fastmail_sieve.sieve.format import format_errors, format_files
from fastmail_sieve.sieve.lint import check_fragments, check_markers, check_syntax
from fastmail_sieve.sieve.report import build_rules, disabled_ui_rules
from fastmail_sieve.sieve.script import assemble, fragment_files, read_fragments
from fastmail_sieve.sieve.variables import load_report, load_variable_docs
from fastmail_sieve.sieve.warnings import collect_warnings


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


def _format_rules():
    changed = format_files(list(fragment_files()))
    if changed:
        return Result(detail="reformatted " + ", ".join(changed))
    return Result(detail="already formatted")


def _lint_fragments():
    fragments = read_fragments()
    errors = format_errors(dict(zip(fragment_files(), fragments, strict=True)))
    error = check_fragments(*fragments)
    return Result(errors=[*errors, *([error] if error else [])])


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

    def __init__(self):
        self.script = None
        self.remote = None
        self.assembled = None
        self._sources = None

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
        self.assembled = assemble(self.remote, *read_fragments())
        return Result()

    def check_syntax(self):
        return Result(errors=_errors(check_syntax(self.assembled)))

    def check_markers(self):
        return Result(errors=_errors(check_markers(self.assembled)))

    def check_variables(self):
        return Result(errors=load_report(self.assembled).errors)

    def warnings(self, strict=False):
        rules = build_rules(
            dict(zip(fragment_files(), read_fragments(), strict=True)),
            self.assembled,
            load_variable_docs(),
        )
        found = collect_warnings(
            rules,
            disabled_ui_rules(self.assembled),
            load_report(self.assembled).warnings,
        )
        lines = [f"{kind}: {text}" for kind, text in found]
        if strict and lines:
            return Result(errors=lines)
        return Result(warnings=lines, detail=None if lines else "none")

    def push(self):
        script = require(self.script, "The remote script")
        updated = script.with_fragments(*read_fragments())
        if updated.same_blocks(script):
            return Result(detail="no change; nothing to push")
        if not get_script(self.credentials()).same_blocks(script):
            return Result(errors=[CHANGED])
        set_blocks(self.credentials(), updated)
        return Result(detail="pushed the managed blocks")

    def verify(self):
        if not get_script(self.credentials()).matches(read_fragments()):
            return Result(
                errors=["Fastmail's managed blocks differ from the local fragments"]
            )
        return Result()


class FolderChecks:
    """The two folder steps share one read of Fastmail's folders."""

    def __init__(self, session=None):
        self._session = session or Session()
        self._mailboxes = None

    def _fragments(self):
        if self._mailboxes is None:
            self._mailboxes = fetch_mailboxes(
                self._session.credentials(session_required=False)
            )
        return self._mailboxes, dict(
            zip(fragment_files(), read_fragments(), strict=True)
        )

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


def lint_steps(session=None, *, offline=False, from_file=None, fix=False, strict=False):
    """Every check, in order. `offline` skips whatever needs Fastmail (everything
    but your rules, unless `from_file` supplies the script); `fix` formats first."""
    session = session or Session()
    steps = [Step("Format your rules", _format_rules)] if fix else []
    steps.append(Step("Valid format and syntax in your rules", _lint_fragments))
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
    steps += [
        Step("Assemble the full script", session.assemble),
        Step("Valid syntax in the assembled script", session.check_syntax),
        Step("Valid markers in the assembled script", session.check_markers),
        Step("Valid variables", session.check_variables),
    ]
    if not offline:
        folders = FolderChecks(session)
        steps += [
            Step("Valid folder stable ids", folders.check_ids, slow=True),
            Step("Valid folder names", folders.check_names),
        ]
    steps.append(Step("Warnings", lambda: session.warnings(strict)))
    return steps


def write_steps(session=None):
    session = session or Session()
    return [
        Step("Push the managed blocks", session.push, slow=True),
        Step("Verify with a fresh pull", session.verify, slow=True),
    ]


def build_steps():
    session = Session()
    return [*lint_steps(session), *write_steps(session)]
