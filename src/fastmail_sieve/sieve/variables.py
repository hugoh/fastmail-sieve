import re
import tomllib
from dataclasses import dataclass, field

from rich import box
from rich.table import Table
from sievelib.parser import Parser

from fastmail_sieve.sieve import lint as check_sieve  # noqa: F401  (registers the Fastmail command extensions)
from fastmail_sieve.sieve.script import mentions_marker
from fastmail_sieve.sieve.variable_docs import load_descriptions, lookup  # noqa: F401
from fastmail_sieve.sieve.wording import headings
from fastmail_sieve.ui.tables import DEFAULT_WIDTH, cell, render_table

VARIABLE_REFERENCE = re.compile(r"\$\{([A-Za-z_][\w.]*)\}")
CALENDAR_OUTPUTS = ("outcome", "reason")
LOCATION_LIMIT = 4
START_LABEL = "the start of the script"


@dataclass
class Variable:
    description: str | None = None
    may_be_unset: bool = False
    set_by: list = field(default_factory=list)
    read_by: list = field(default_factory=list)


DEFAULT_DOCS_FILE = "variables.toml"


@dataclass
class Report:
    variables: dict
    errors: list
    warnings: list


def _strings(value):
    if isinstance(value, bytes):
        yield value.decode("utf-8")
    elif isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif hasattr(value, "arguments"):
        for nested in _command_values(value):
            yield from _strings(nested)


def _command_values(command):
    yield from command.arguments.values()
    yield from command.extra_arguments.values()


def _walk(command):
    yield command
    for value in _command_values(command):
        for nested in _nested_commands(value):
            yield from _walk(nested)
    for child in command.children:
        yield from _walk(child)


def _nested_commands(value):
    if hasattr(value, "arguments"):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _nested_commands(item)


def _unquote(value):
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def _assigned_names(command):
    if command.name == "set":
        yield _unquote(command.arguments["name"]).lower()
    elif command.name == "processcalendar":
        for key in CALENDAR_OUTPUTS:
            if key in command.extra_arguments:
                yield _unquote(command.extra_arguments[key]).lower()


def _read_names(command):
    for value in _command_values(command):
        if isinstance(value, (list, tuple)) and any(
            hasattr(i, "arguments") for i in value
        ):
            continue
        if hasattr(value, "arguments"):
            continue
        for text in _strings(value):
            yield from (name.lower() for name in VARIABLE_REFERENCE.findall(text))


def fragment_variable_names(fragments):
    names = set()
    for text in fragments:
        parser = Parser()
        if not parser.parse(check_sieve.FASTMAIL_REQUIRE + text):
            raise ValueError(parser.error)
        for top_level in parser.result:
            for command in _walk(top_level):
                names.update(_assigned_names(command))
                names.update(_read_names(command))
    return names


def _add(locations, label):
    if label not in locations:
        locations.append(label)


def _describe(name, descriptions):
    entry = lookup(name, descriptions)
    if entry is None:
        return None, False
    return entry.get("description"), bool(entry.get("may_be_unset"))


def analyze(text, descriptions, scope=None, docs_name=DEFAULT_DOCS_FILE):
    parser = Parser()
    if not parser.parse(text):
        raise ValueError(parser.error)
    variables = {}
    label = START_LABEL
    for top_level in parser.result:
        found = next(
            (
                h.removeprefix("## ")
                for h in headings(top_level)
                if not mentions_marker(h)
            ),
            None,
        )
        if found:
            label = found
        for command in _walk(top_level):
            for name in _assigned_names(command):
                _add(variables.setdefault(name, Variable()).set_by, label)
            for name in _read_names(command):
                _add(variables.setdefault(name, Variable()).read_by, label)
    errors = []
    for name in sorted(variables):
        variable = variables[name]
        variable.description, variable.may_be_unset = _describe(name, descriptions)
        if scope is not None and name not in scope:
            continue
        if variable.description is None:
            errors.append(f"{name}: no description in {docs_name}")
        if variable.read_by and not variable.set_by and not variable.may_be_unset:
            errors.append(f"{name}: read but never set")
        if variable.set_by and not variable.read_by:
            errors.append(f"{name}: set but never read")
    warnings = [
        f"{name}: described in {docs_name} but not in the script"
        for name in sorted(descriptions)
        if name not in variables
    ]
    return Report(variables, errors, warnings)


def _locations(locations):
    if not locations:
        return cell("nowhere", "dim")
    shown = "\n".join(locations[:LOCATION_LIMIT])
    extra = len(locations) - LOCATION_LIMIT
    return cell(shown + (f"\nand {extra} more" if extra > 0 else ""))


def render(report, width=DEFAULT_WIDTH, color=False):
    table = Table(box=box.ROUNDED, header_style="bold", show_lines=True)
    table.add_column("Variable", no_wrap=True, style="bold")
    table.add_column("Meaning", overflow="fold")
    table.add_column("Set by", overflow="fold")
    table.add_column("Read by", overflow="fold")
    for name in sorted(report.variables):
        variable = report.variables[name]
        meaning = cell(variable.description or "(undocumented)")
        table.add_row(
            name, meaning, _locations(variable.set_by), _locations(variable.read_by)
        )
    return "\n".join(render_table(table, width, color))


def load_variable_docs(project):
    path = project.variables_file
    try:
        text = project.path(path).read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise RuntimeError(
            f"{path} not found: create it with `fastmail-sieve init`"
        ) from error
    try:
        return load_descriptions(text)
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"{path}: {error}") from error


def load_report(project, script_text, fragments=None):
    """The variable report; `fragments` (default: your local ones) say which names
    your own rules set."""
    fragments = project.read_fragments() if fragments is None else fragments
    return analyze(
        script_text,
        load_variable_docs(project),
        fragment_variable_names(fragments),
        project.variables_file,
    )
