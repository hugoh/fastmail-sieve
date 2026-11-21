import json
import re
from dataclasses import dataclass, field

from sievelib.parser import Parser

from fastmail_sieve.sieve import lint as check_sieve
from fastmail_sieve.sieve import wording as ex
from fastmail_sieve.sieve.variable_docs import folder_label

CARRIED_FLAGS = ("skipinbox", "flagged", "stop")
FILING_SOURCE = re.compile(r"^\$\{([^}]+)\}$")
INDENT = "  "


class Unsupported(Exception):
    pass


@dataclass
class Migration:
    snippet: str = ""
    errors: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _all_commands(commands):
    for command in commands:
        yield command
        yield from _all_commands(command.children)


def _filing_variable(test):
    if test is None or test.name != "string":
        return None
    if test.arguments.get("match-type", ":is") != ":is":
        return None
    if ex._unquote(test.arguments["key-list"]) != "Y":
        return None
    match = FILING_SOURCE.match(ex._unquote(test.arguments["source"]))
    return match.group(1).lower() if match else None


def _folders(commands):
    folders = {}
    for command in _all_commands(commands):
        variable = (
            _filing_variable(command.arguments.get("test"))
            if command.name == "if"
            else None
        )
        if variable is None:
            continue
        for child in command.children:
            if child.name == "fileinto" and "mailboxid" in child.extra_arguments:
                mailbox_id = ex._unquote(child.extra_arguments["mailboxid"])
                folders[variable] = (
                    mailbox_id,
                    ex._unquote(child.arguments["mailbox"]),
                )
    return folders


def _is_stop_guard(test):
    if test.name != "not":
        return False
    inner = test.arguments["test"]
    return (
        inner.name == "string"
        and ex._unquote(inner.arguments["source"]).lower() == "${stop}"
        and ex._unquote(inner.arguments["key-list"]) == "Y"
    )


def _from_values(parsed):
    if set(parsed) == {"from"} and isinstance(parsed["from"], str):
        return [parsed["from"]]
    if (
        set(parsed) == {"conditions", "operator"}
        and str(parsed["operator"]).upper() == "OR"
    ):
        conditions = parsed["conditions"]
        if all(set(c) == {"from"} and isinstance(c["from"], str) for c in conditions):
            return [c["from"] for c in conditions]
    raise Unsupported(f"search {json.dumps(parsed)} is not a plain from search")


def _condition(test):
    parts = test.arguments["tests"] if test.name == "allof" else [test]
    queries = []
    for part in parts:
        if part.name == "jmapquery":
            queries.append(part)
        elif not _is_stop_guard(part):
            raise Unsupported(f"unsupported condition '{part.name}'")
    if len(queries) != 1:
        raise Unsupported("expected exactly one search")
    parsed = ex._jmap_body(ex._unquote(queries[0].arguments["query"]))
    if parsed is None:
        raise Unsupported("the search could not be read")
    try:
        return "from", _from_values(parsed)
    except Unsupported:
        return "jmap", parsed


def _collect(children, flags, folder_variables):
    for command in children:
        if command.name == "set":
            name = ex._unquote(command.arguments["name"]).lower()
            value = ex._unquote(command.arguments["value"])
            if value != "Y":
                raise Unsupported(f"sets ${{{name}}} to {value}")
            if name in CARRIED_FLAGS:
                flags.add(name)
            elif folder_label(name) is not None:
                folder_variables.append(name)
            else:
                raise Unsupported(f"sets ${{{name}}}, which cannot be translated")
        elif (
            command.name == "if" and command.arguments["test"].name == "mailboxidexists"
        ):
            _collect(command.children, flags, folder_variables)
        else:
            raise Unsupported(f"unsupported command '{command.name}'")


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _part(test, values):
    if len(values) == 1:
        return [f"{test} {_quote(values[0])}"]
    quoted = [f"{INDENT}{_quote(v)}" for v in values]
    return [f"{test} [", *[q + "," for q in quoted[:-1]], quoted[-1], "]"]


def _if_lines(values):
    addresses = list(
        dict.fromkeys(v for v in values if "@" in v and not v.startswith("@"))
    )
    domains = list(dict.fromkeys(v.lstrip("@") for v in values if v not in addresses))
    parts = []
    if addresses:
        parts.append(_part('address :is "from"', addresses))
    if domains:
        parts.append(_part('address :domain "from"', domains))
    if len(parts) == 1:
        lines = list(parts[0])
        lines[0] = f"if {lines[0]}"
        lines[-1] += " {"
        return lines
    lines = ["if anyof ("]
    for index, part in enumerate(parts):
        block = [f"{INDENT}{line}" for line in part]
        if index < len(parts) - 1:
            block[-1] += ","
        lines.extend(block)
    return [*lines, ") {"]


MAX_LINE = 100


def _jmap_entries(parsed):
    compact = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    line = f"if jmapquery {_quote(compact)} {{"
    if len(INDENT + line) <= MAX_LINE:
        return [(line, True)]
    text = json.dumps(parsed, indent=3, ensure_ascii=False)
    return [
        ("if jmapquery text:", True),
        *[(line, False) for line in text.split("\n")],
        (".", False),
        ("{", True),
    ]


def _rule_text(title, condition, folder, flags):
    kind, found = condition
    mailbox_id, name = folder
    copy = "" if "skipinbox" in flags else ":copy "
    body = []
    if "flagged" in flags:
        body.append('addflag "\\\\Flagged";')
    body.append(f"fileinto {copy}:mailboxid {_quote(mailbox_id)} {_quote(name)};")
    if "stop" in flags:
        body.append("stop;")
    opening = (
        _jmap_entries(found)
        if kind == "jmap"
        else [(line, True) for line in _if_lines(found)]
    )
    entries = [
        (f"# {title}", True),
        *opening,
        *[(f"{INDENT}{line}", True) for line in body],
        ("}", True),
    ]
    return (
        "\n".join(f"{INDENT}{text}" if indented else text for text, indented in entries)
        + "\n"
    )


def _translate(command, title, folders):
    if command.name != "if":
        raise Unsupported(f"unsupported command '{command.name}'")
    condition = _condition(command.arguments["test"])
    flags, folder_variables = set(), []
    _collect(command.children, flags, folder_variables)
    if not folder_variables:
        raise Unsupported("no folder action")
    if len(folder_variables) > 1:
        raise Unsupported("several folders in one rule")
    variable = folder_variables[0]
    if variable not in folders:
        raise Unsupported(f"no filing block found for ${{{variable}}}")
    return _rule_text(title, condition, folders[variable], flags)


def migrate(script_text):
    parser = Parser()
    if not parser.parse(script_text):
        raise ValueError(parser.error)
    folders = _folders(parser.result)
    result = Migration()
    texts = []
    for command in parser.result:
        result.skipped.extend(ex.disabled_ui_titles(command))
        title = ex._ui_rule_title(command)
        if title is None:
            continue
        try:
            texts.append(_translate(command, title, folders))
        except Unsupported as error:
            result.errors.append(f"{title}: {error}")
    snippet = "\n".join(texts)
    if snippet and not result.errors:
        problem = check_sieve.check_syntax(check_sieve.FASTMAIL_REQUIRE + snippet)
        if problem:
            result.errors.append(f"generated Sieve failed the linter: {problem}")
    if not result.errors:
        result.snippet = snippet
    return result
