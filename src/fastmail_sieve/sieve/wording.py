import json
import re

from fastmail_sieve.sieve.variable_docs import lookup

SPECIAL_USE_MARKERS = {"trash": "🚮", "junk": "🚫"}
PIN_ACTION = "📌 pin (flag) the message"
FLAG_COMMANDS = {
    "addflag": "Add flag",
    "removeflag": "Remove flag",
    "setflag": "Set flag",
}
MATCH_WORDS = {
    ":is": "is",
    ":contains": "contains",
    ":matches": "matches",
    ":regex": "matches regex",
}
RELATIONAL_OPERATORS = {
    "gt": ">",
    "ge": ">=",
    "lt": "<",
    "le": "<=",
    "eq": "==",
    "ne": "!=",
}
SINGLE_VARIABLE = re.compile(r"^\$\{([^}]+)\}$")
UI_RULE_PREFIX = "Search:"
ADDRESS_PARTS = {
    ":domain": "domain",
    ":localpart": "local part",
    ":user": "user",
    ":detail": "detail",
}
SECTION_END = re.compile(r"^#+\s*}}}\s*$")


def _unquote(value):
    if isinstance(value, list):
        return [_unquote(v) for v in value]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _words(value, joiner=" or "):
    values = _unquote(value)
    return joiner.join(values if isinstance(values, list) else [values])


def _jmap_text(query):
    return (
        query[len("text:") :].rsplit("\n.", 1)[0]
        if query.startswith("text:")
        else query
    )


def _jmap_body(query):
    body = _jmap_text(query)
    try:
        return json.loads(_unquote(body) if not body.lstrip().startswith("{") else body)
    except ValueError:
        return None


def _jmap_conditions(query):
    parsed = _jmap_body(query)
    if parsed is None:
        return " ".join(_jmap_text(query).split())
    return _jmap_filter(parsed)


def _jmap_from_values(node):
    if "conditions" in node:
        return [
            v for condition in node["conditions"] for v in _jmap_from_values(condition)
        ]
    value = node.get("from")
    return [value.lower()] if isinstance(value, str) else []


def _jmap_filter(node):
    if "conditions" in node:
        operator = f" {node.get('operator', 'AND').lower()} "
        return operator.join(_jmap_filter(c) for c in node["conditions"])
    return ", ".join(f"{key}: {value}" for key, value in node.items())


def _match_phrase(test):
    match_type = test.arguments.get("match-type", ":is")
    if match_type == ":value":
        operator = RELATIONAL_OPERATORS[_unquote(test.extra_arguments["match-type"])]
        return f"{operator} {_words(test.arguments['key-list'])}", " (numeric)"
    return (
        f"{MATCH_WORDS.get(match_type, match_type)} {_words(test.arguments['key-list'])}",
        "",
    )


def _variable_entry(reference, docs):
    if docs is None:
        return None
    match = SINGLE_VARIABLE.match(reference)
    return lookup(match.group(1).lower(), docs) if match else None


def _string_meaning(test, docs, negated=False):
    arguments = test.arguments
    entry = _variable_entry(_words(arguments["source"]), docs)
    if entry is None or arguments.get("match-type", ":is") != ":is":
        return None
    values = _unquote(arguments["key-list"])
    if values in ("Y", ["Y"]):
        return entry.get("when_no" if negated else "when_yes")
    if not negated and entry.get("label"):
        return f"{entry['label']} is {_words(arguments['key-list'])}"
    return None


def _leaf(test, docs=None):
    arguments = test.arguments
    if test.name == "string":
        meaning = _string_meaning(test, docs)
        if meaning:
            return meaning
    if test.name in ("address", "envelope"):
        names = _words(arguments["header-list"], " or ")
        phrase, suffix = _match_phrase(test)
        part = ADDRESS_PARTS.get(arguments.get("address-part"))
        if test.name == "envelope":
            return f"envelope {names} {phrase}{suffix}"
        subject = f"the {names} address" + (f" {part}" if part else "")
        return f"{subject} {phrase}{suffix}"
    if test.name == "header":
        phrase, suffix = _match_phrase(test)
        return f"header {_words(arguments['header-names'])} {phrase}{suffix}"
    if test.name == "string":
        phrase, suffix = _match_phrase(test)
        return f"{_words(arguments['source'])} {phrase}{suffix}"
    if test.name == "hasflag":
        return f"the message has flag {_words(arguments['list-of-flags'])}"
    if test.name == "jmapquery":
        return f"the search matches {_jmap_conditions(_unquote(arguments['query']))}"
    if test.name == "mailboxidexists":
        return f"mailbox id {_words(arguments['mailbox-ids'])} exists"
    if test.name == "true":
        return "always"
    detail = ", ".join(f"{k}={_words(v)}" for k, v in arguments.items() if k != "test")
    return f"{test.name} {detail}".strip()


def _jmap_values(node):
    if "conditions" in node:
        return [v for condition in node["conditions"] for v in _jmap_values(condition)]
    return [value for value in node.values() if isinstance(value, str)]


def leaf_values(test):
    """The strings a test compares against, in their original case."""
    arguments = test.arguments
    if test.name in ("address", "envelope", "header", "string"):
        keys = _unquote(arguments["key-list"])
        keys = keys if isinstance(keys, list) else [keys]
        return (
            []
            if test.name == "string" and keys == ["Y"]
            else [str(key) for key in keys]
        )
    if test.name == "hasflag":
        flags = _unquote(arguments["list-of-flags"])
        return [str(flag) for flag in (flags if isinstance(flags, list) else [flags])]
    if test.name == "jmapquery":
        parsed = _jmap_body(_unquote(arguments["query"]))
        return _jmap_values(parsed) if parsed else []
    return []


def _special_use_marker(command):
    use = _unquote(command.extra_arguments.get("specialuse", "")).lstrip("\\").lower()
    return SPECIAL_USE_MARKERS.get(use)


def _mailbox(command, label):
    marker = _special_use_marker(command)
    if marker:
        label = f"{marker} {label.split(' ', 1)[1]}"
    name = _unquote(command.arguments["mailbox"])
    extras = command.extra_arguments
    notes = []
    if "mailboxid" in extras:
        notes.append(f"mailbox id {_unquote(extras['mailboxid'])}")
    if "specialuse" in extras:
        notes.append(f"special-use {_unquote(extras['specialuse'])}")
    return f"{label} {name}" + (f" ({', '.join(notes)})" if notes else "")


def _set_meaning(command, docs, moving=False):
    entry = _variable_entry("${" + _unquote(command.arguments["name"]) + "}", docs)
    if entry is None:
        return None
    value = _unquote(command.arguments["value"])
    if value == "Y" and moving and entry.get("set_yes_move"):
        return entry["set_yes_move"]
    if value == "Y" and entry.get("set_yes"):
        return entry["set_yes"]
    if entry.get("label"):
        return f"set {entry['label']} to {value}"
    return None


def _action(command, docs=None, moving=False):
    name, arguments = command.name, command.arguments
    if name == "fileinto":
        return _mailbox(
            command, "🔖 copy into" if "copy" in arguments else "📁 file into"
        )
    if name == "implicit_keep_target":
        return _mailbox(command, "deliver by default to")
    if name == "stop":
        return "🛑 stop processing"
    if name == "discard":
        return "discard the message"
    if name == "keep":
        return "keep in the inbox"
    if name == "set":
        meaning = _set_meaning(command, docs, moving)
        if meaning:
            return meaning
        return (
            f"set ${{{_unquote(arguments['name'])}}} to {_unquote(arguments['value'])}"
        )
    if (
        name == "addflag"
        and _words(arguments["list-of-flags"]).lower().lstrip("\\") == "flagged"
    ):
        return PIN_ACTION
    if name in FLAG_COMMANDS:
        return f"{FLAG_COMMANDS[name].lower()} {_words(arguments['list-of-flags'])}"
    if name == "processcalendar":
        return "process calendar invites"
    if name == "addheader":
        return f"add header {_unquote(arguments['field-name'])}: {_unquote(arguments['value'])}"
    detail = ", ".join(f"{k}={_words(v)}" for k, v in arguments.items())
    return f"{name} {detail}".strip()


def headings(command):
    for raw in getattr(command, "hash_comments", []):
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if SECTION_END.match(line):
            continue
        text = line.strip("# ").replace("{{{", "").strip()
        if text:
            yield f"## {text}"


def _search_title(heading):
    text = heading.removeprefix("## ")
    if not text.startswith(UI_RULE_PREFIX):
        return None
    return text.removeprefix(UI_RULE_PREFIX).strip().strip('"')


def _ui_rule_title(command):
    found = list(headings(command))
    return _search_title(found[-1]) if found else None


def disabled_ui_titles(command):
    found = list(headings(command))
    earlier = found[:-1] if _ui_rule_title(command) is not None else found
    return [title for title in map(_search_title, earlier) if title is not None]


def _visit_values(value, on_command):
    if hasattr(value, "arguments"):
        on_command(value)
        _visit_values(value.arguments, on_command)
    elif isinstance(value, dict):
        for nested in value.values():
            _visit_values(nested, on_command)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _visit_values(item, on_command)


def _search_queries(command):
    queries = []

    def collect(nested):
        if nested.name == "jmapquery":
            queries.append(_unquote(nested.arguments["query"]))

    _visit_values(command.arguments, collect)
    return queries


def _ui_senders(queries):
    senders = []
    for query in queries:
        parsed = _jmap_body(query)
        if parsed is not None:
            senders.extend(_jmap_from_values(parsed))
    return senders


def _custom_senders(test):
    if test.name in ("allof", "anyof"):
        return [s for sub in test.arguments["tests"] for s in _custom_senders(sub)]
    if test.name != "address":
        return []
    arguments = test.arguments
    if "from" not in [
        h.lower() for h in _unquote(arguments["header-list"]) if isinstance(h, str)
    ] and (_unquote(arguments["header-list"]) != "from"):
        return []
    if arguments.get("match-type", ":is") != ":is":
        return []
    kind = "domain" if arguments.get("address-part") == ":domain" else "address"
    keys = _unquote(arguments["key-list"])
    return [(kind, key.lower()) for key in (keys if isinstance(keys, list) else [keys])]


def _domain(value):
    return value.split("@")[-1]


def _overlaps(sender, ui_sender):
    kind, value = sender
    bare = ui_sender.lstrip("@")
    if kind == "address":
        return value == ui_sender or (
            ("@" not in ui_sender or ui_sender.startswith("@"))
            and _domain(value) == bare
        )
    return _domain(ui_sender) == value or _domain(ui_sender).endswith("." + value)
