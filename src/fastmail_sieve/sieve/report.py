import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from rich import box
from rich.console import Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from sievelib.parser import Parser

from fastmail_sieve.sieve import lint as check_sieve
from fastmail_sieve.sieve import wording as ex
from fastmail_sieve.sieve.script import mentions_end, mentions_marker, mentions_start
from fastmail_sieve.sieve.variable_docs import folder_label
from fastmail_sieve.ui.tables import cell, make_console, render_table, styled

CONDITIONALS = ("if", "elsif", "else")
MAILBOX_GUARD = re.compile(r"^mailbox id .+ exists$")
RULE_SUBJECT = re.compile(r"^the (\S+) address")
AFTER_UI = "bottom"
LIST_LIMIT = 3
ICONS = {
    "move": "📁",
    "label": "🔖",
    "trash": "🚮",
    "junk": "🚫",
    "pin": "📌",
    "stop": "🛑",
}
VARIABLE_KINDS = {
    "deletetotrash": "trash",
    "spam": "junk",
    "tospam": "junk",
    "flagged": "pin",
    "skipinbox": "skipinbox",
}


class Leaf(str):
    """A condition's wording plus the values it compares against."""

    values: list

    def __new__(cls, text, values=()):
        leaf = super().__new__(cls, text)
        leaf.values = list(values)
        return leaf


@dataclass
class Action:
    kind: str
    text: str
    short: str


@dataclass
class Rule:
    source: str
    title: str
    cond: object
    actions: list
    senders: list
    stops: bool
    number: int = 0
    ui_senders: list = field(default_factory=list)
    search: str = ""
    warnings: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    values: list = field(default_factory=list)
    search_text: str = ""


OTHERWISE = ("leaf", "otherwise")


def _group(kind, children):
    flat = []
    for child in children:
        for item in child[1] if child[0] == kind else [child]:
            if item == OTHERWISE and OTHERWISE in flat:
                continue
            flat.append(item)
    return flat[0] if len(flat) == 1 else (kind, flat)


def _clean(text):
    return RULE_SUBJECT.sub(r"\1", text)


def _tree(test, docs):
    if test.name in ("allof", "anyof"):
        kind = "all" if test.name == "allof" else "any"
        return _group(kind, [_tree(sub, docs) for sub in test.arguments["tests"]])
    if test.name == "not":
        inner = test.arguments["test"]
        if inner.name == "string":
            meaning = ex._string_meaning(inner, docs, negated=True)
            if meaning:
                return ("leaf", meaning)
        return ("not", _tree(inner, docs))
    return ("leaf", Leaf(_clean(ex._leaf(test, docs)), ex.leaf_values(test)))


def _test_queries(test):
    queries = []
    if test.name == "jmapquery":
        queries.append(ex._unquote(test.arguments["query"]))
    return queries + ex._search_queries(test)


def _search_forms(tests):
    rendered = [
        ex._jmap_conditions(query)
        for test in tests
        if test is not None
        for query in _test_queries(test)
    ]
    return " | ".join(text.lower() for text in rendered), " | ".join(rendered)


def _cond_values(node):
    if node is None:
        return []
    if node[0] == "leaf":
        return list(getattr(node[1], "values", []))
    children = [node[1]] if node[0] == "not" else node[1]
    return [value for child in children for value in _cond_values(child)]


def _is_guard(node, docs):
    if node[0] == "leaf":
        stop = (docs or {}).get("stop", {}).get("when_no")
        return node[1] == stop or bool(MAILBOX_GUARD.match(node[1]))
    return node == ("not", ("leaf", "${stop} is Y"))


def _prune(node, docs):
    if _is_guard(node, docs):
        return None
    if node[0] == "all":
        kept = [n for n in (_prune(child, docs) for child in node[1]) if n is not None]
        return _group("all", kept) if kept else None
    return node


def _combine(conds, docs):
    return _prune(_group("all", conds), docs) if conds else None


def _is_stop(command):
    if command.name == "stop":
        return True
    return (
        command.name == "set"
        and ex._unquote(command.arguments["name"]).lower() == "stop"
        and ex._unquote(command.arguments["value"]) == "Y"
    )


def _target(name):
    return name.removeprefix("INBOX.")


def _variable_action(command, docs, moving):
    variable = ex._unquote(command.arguments["name"]).lower()
    text = ex._action(command, docs, moving)
    label = folder_label(variable)
    if label is not None:
        kind = "move" if moving else "label"
        return Action(kind, text, f"{ICONS[kind]} {label}")
    kind = VARIABLE_KINDS.get(variable, "other")
    short = {"skipinbox": "skip Inbox"}.get(kind, ICONS.get(kind, text))
    return Action(kind, text, short)


def _action_item(command, docs, moving):
    if _is_stop(command):
        return Action("stop", "🛑 stop", ICONS["stop"])
    if command.name == "set":
        return _variable_action(command, docs, moving)
    text = ex._action(command, docs, moving)
    if command.name == "fileinto":
        use = (
            ex._unquote(command.extra_arguments.get("specialuse", ""))
            .lstrip("\\")
            .lower()
        )
        kind = {"trash": "trash", "junk": "junk"}.get(use) or (
            "label" if "copy" in command.arguments else "move"
        )
        mailbox = _target(ex._unquote(command.arguments["mailbox"]))
        short = ICONS[kind] if kind in ("trash", "junk") else f"{ICONS[kind]} {mailbox}"
        return Action(kind, text, short)
    if command.name == "addflag" and text == ex.PIN_ACTION:
        return Action("pin", text, ICONS["pin"])
    return Action("other", text, text)


def _dedupe(actions):
    seen, unique = set(), []
    for action in actions:
        if (action.kind, action.text) not in seen:
            seen.add((action.kind, action.text))
            unique.append(action)
    return unique


class _Builder:
    def __init__(self, source, heading, docs, fixed_title=None):
        self.source, self.docs, self.fixed_title = source, docs, fixed_title
        self.heading = re.sub(r"\s*\(.*\)$", "", heading) if heading else None
        self.rules = []

    def _node(self, command):
        if command.name == "else":
            return ("leaf", "otherwise")
        node = _tree(command.arguments["test"], self.docs)
        return (
            _group("all", [("leaf", "otherwise"), node])
            if command.name == "elsif"
            else node
        )

    def run(self, command):
        actions = []
        self.process([command], [], [], actions, 0)
        self.flush([], [], actions, 0)
        return self.rules

    def process(self, commands, conds, tests, actions, depth):
        for command in commands:
            if command.name not in CONDITIONALS:
                actions.append(command)
                continue
            node = self._node(command)
            if _prune(node, self.docs) is None:
                self.process(command.children, conds, tests, actions, depth)
                continue
            self.flush(conds, tests, actions, depth)
            inner = []
            test = command.arguments.get("test")
            self.process(
                command.children, [*conds, node], [*tests, test], inner, depth + 1
            )
            self.flush([*conds, node], [*tests, test], inner, depth + 1)

    def flush(self, conds, tests, pending, depth):
        if not pending:
            return
        commands = list(pending)
        pending.clear()
        commands_stop = any(_is_stop(c) for c in commands)
        items = _dedupe([_action_item(c, self.docs, commands_stop) for c in commands])
        senders = [s for t in tests if t is not None for s in ex._custom_senders(t)]
        rule = Rule(
            self.source,
            "",
            _combine(conds, self.docs),
            items,
            senders,
            any(a.kind == "stop" for a in items),
        )
        rule.title = self._title(items, depth)
        rule.values = list(dict.fromkeys(_cond_values(rule.cond)))
        rule.search, rule.search_text = _search_forms(tests)
        self.rules.append(rule)

    def _title(self, items, depth):
        if self.fixed_title:
            return self.fixed_title
        shorts = next((a.short for a in items if a.kind in ("move", "label")), None)
        target = shorts.split(" ", 1)[-1] if shorts else None
        summary = _action_summary(items)
        if self.heading and depth >= 2:
            if target:
                return f"{self.heading} → {target}"
            if summary:
                return summary
        if self.heading:
            return self.heading
        if target:
            return f"→ {target}"
        return summary or f"{self.source} rule"


ACTION_SUMMARIES = (("pin", "Pinning"), ("trash", "Trash"), ("junk", "Junk"))


def _action_summary(items):
    kinds = {item.kind for item in items}
    return next((word for kind, word in ACTION_SUMMARIES if kind in kinds), None)


def _heading(command):
    return next(
        (h.removeprefix("## ") for h in ex.headings(command) if not mentions_marker(h)),
        None,
    )


def _fragment_rules(name, text, docs):
    parser = Parser()
    if not parser.parse(check_sieve.FASTMAIL_REQUIRE + text):
        raise ValueError(f"{name}: {parser.error}")
    source = Path(name).stem
    rules = []
    for command in parser.result:
        if command.name != "require":
            rules.extend(_Builder(source, _heading(command), docs).run(command))
    return rules


def _ui_rule(command, title, docs):
    queries = ex._search_queries(command)
    rules = _Builder("ui", None, docs, fixed_title=title).run(command)
    for rule in rules:
        rule.ui_senders = ex._ui_senders(queries)
        rule.search, rule.search_text = _search_forms([command.arguments["test"]])
        rule.senders = [("search", sender) for sender in rule.ui_senders]
    return rules


def _ui_rules(scratch_text, docs):
    parser = Parser()
    if not parser.parse(scratch_text):
        raise ValueError(parser.error)
    rules = []
    for command in parser.result:
        title = ex._ui_rule_title(command)
        if title is not None:
            rules.extend(_ui_rule(command, title, docs))
    return rules


def disabled_ui_rules(scratch_text):
    parser = Parser()
    if not parser.parse(scratch_text):
        raise ValueError(parser.error)
    return [
        title for command in parser.result for title in ex.disabled_ui_titles(command)
    ]


def _body_key(rule):
    return (repr(rule.cond), tuple(a.text for a in rule.actions))


def _warn_duplicates(ui_rules):
    for index, rule in enumerate(ui_rules):
        for other in ui_rules[:index]:
            if rule.search and other.search == rule.search:
                same = _body_key(other) == _body_key(rule)
                kind = "duplicate of" if same else "same search as"
                suffix = "" if same else " but different actions"
                rule.warnings.append(f"❗ {kind} rule {other.number}{suffix}")
                label = _source_label(rule)
                if same:
                    text = f"rule {rule.number} ({label}) repeats rule {other.number} ({label})"
                    rule.issues.append(("duplicate", text))
                else:
                    text = (
                        f"rule {rule.number} ({label}) has the same search as "
                        f"rule {other.number} but different actions"
                    )
                    rule.issues.append(("conflict", text))
                break


def _overlap_sender(custom, ui):
    for sender in custom.senders:
        for ui_sender in ui.ui_senders:
            if sender[0] != "search" and ex._overlaps(sender, ui_sender):
                return sender[1]
    return None


def _overlap_reason(custom, ui):
    """(short text, sentence subject) for what the two rules both match, or None."""
    sender = _overlap_sender(custom, ui)
    if sender is not None:
        return sender, f"mail from {sender}"
    if custom.search and custom.search == ui.search:
        same = f"the same search ({custom.search_text})"
        return same, same
    return None


def _note_overlap(custom, ui, reason, custom_first):
    if custom_first:
        effect = f"rule {ui.number} never applies" if custom.stops else "both apply"
    else:
        effect = f"rule {custom.number} runs after rule {ui.number}"
    lower, higher = sorted((custom, ui), key=lambda rule: rule.number)
    text = (
        f"rule {lower.number} ({_source_label(lower)}) vs rule {higher.number} "
        f"({_source_label(higher)}) on {reason}: {effect}"
    )
    lower.issues.append(("overlap", text))


FILING_KINDS = ("move", "label", "trash", "junk")


def _files(rule):
    return any(action.kind in FILING_KINDS for action in rule.actions)


def _warn_overlaps(rules):
    for ui in (r for r in rules if r.source == "ui" and _files(r)):
        for custom in (r for r in rules if r.source != "ui" and _files(r)):
            found = _overlap_reason(custom, ui)
            if found is None:
                continue
            reason, subject = found
            first = custom.source != AFTER_UI
            _note_overlap(custom, ui, reason, first)
            there = f"rule {ui.number} ({ui.title})"
            here = f"rule {custom.number} ({custom.title})"
            if first and custom.stops:
                custom.warnings.append(
                    f"❗ {subject} also matches {there}, which never applies"
                )
                ui.warnings.append(
                    f"❗ never applies to {subject}: {here} stops it first"
                )
            elif first:
                custom.warnings.append(f"❗ {subject} also matches {there}: both apply")
                ui.warnings.append(f"❗ {subject} also matches {here}: both apply")
            else:
                custom.warnings.append(
                    f"❗ {subject} also matches {there}, which runs first"
                )
                ui.warnings.append(
                    f"❗ {subject} also matches {here}, which runs after"
                )


def _finish(rules):
    for number, rule in enumerate(rules, start=1):
        rule.number = number
    _warn_duplicates([rule for rule in rules if rule.source == "ui"])
    _warn_overlaps(rules)
    return rules


def build_rules(fragments, scratch_text, docs=None):
    before, after = [], []
    for name, text in fragments.items():
        if text.strip():
            rules = _fragment_rules(name, text, docs)
            (after if Path(name).stem == AFTER_UI else before).extend(rules)
    return _finish([*before, *_ui_rules(scratch_text, docs), *after])


BLOCK_SOURCES = ("top", "middle", "bottom")


def build_full_rules(text, docs=None):
    parser = Parser()
    if not parser.parse(text):
        raise ValueError(parser.error)
    rules, block, inside, last_heading = [], 0, False, None
    for command in parser.result:
        if command.name == "require":
            continue
        for heading in ex.headings(command):
            if mentions_start(heading):
                block, inside = block + 1, True
            elif mentions_end(heading):
                inside = False
        own = _heading(command)
        last_heading = own or last_heading
        title = ex._ui_rule_title(command)
        if title is not None:
            rules.extend(_ui_rule(command, title, docs))
        elif inside:
            source = BLOCK_SOURCES[min(block, len(BLOCK_SOURCES)) - 1]
            rules.extend(_Builder(source, own, docs).run(command))
        else:
            rules.extend(_Builder("fastmail", own or last_heading, docs).run(command))
    return _finish(rules)


def _lines(node):
    kind = node[0]
    if kind == "leaf":
        return [node[1]]
    if kind == "not":
        child = node[1]
        if child[0] in ("all", "any"):
            head = "NOT all of:" if child[0] == "all" else "NOT any of:"
            return [head, *[f"    {line}" for line in _lines(child)]]
        sub = _lines(child)
        return [f"NOT {sub[0]}", *[f"    {line}" for line in sub[1:]]]
    word = "AND" if kind == "all" else "OR"
    out = []
    for index, child in enumerate(node[1]):
        prefix = f"{word} " if index else ""
        if child[0] in ("all", "any"):
            head = "all of:" if child[0] == "all" else "any of:"
            out.append(f"{prefix}{head}")
            out.extend(f"    {line}" for line in _lines(child))
        elif child[0] == "not" and child[1][0] in ("all", "any"):
            inner = child[1]
            head = "NOT all of:" if inner[0] == "all" else "NOT any of:"
            out.append(f"{prefix}{head}")
            out.extend(f"    {line}" for line in _lines(inner))
        else:
            sub = _lines(child)
            out.append(f"{prefix}{sub[0]}")
            out.extend(f"    {line}" for line in sub[1:])
    return out


def _source_label(rule):
    return {"ui": "UI", "fastmail": "Fastmail"}.get(rule.source, rule.source)


def _label(text, style, dim=False):
    return cell(text, "dim" if dim else f"bold {style}")


def _value_pattern(value):
    start = r"(?<![\w@.])" if value[0].isalnum() else ""
    end = r"(?![\w@])" if value[-1].isalnum() else ""
    return f"{start}{re.escape(value)}{end}"


def _split_values(text, values):
    patterns = [
        _value_pattern(v) for v in sorted(set(values), key=len, reverse=True) if v
    ]
    if not patterns:
        return [(text, False)] if text else []
    parts, position = [], 0
    for match in re.finditer("|".join(patterns), text):
        if match.start() > position:
            parts.append((text[position : match.start()], False))
        parts.append((match.group(), True))
        position = match.end()
    if position < len(text):
        parts.append((text[position:], False))
    return parts


def _condition_line(line, dim=False, values=()):
    indent = len(line) - len(line.lstrip())
    body = line.strip()
    text = Text()
    keyword = re.match(r"(AND|OR|NOT)\b", body)
    if keyword and not dim:
        text.append(cell(keyword.group(1), "yellow"))
        body = body[keyword.end() :]
    for part, is_value in _split_values(body, () if dim else values):
        text.append(cell(part, "bold" if is_value else "dim"))
    return Padding(text, (0, 0, 0, indent))


def _is_generated(rule):
    return rule.source == "fastmail"


def _details(rule):
    dim = _is_generated(rule)
    title = cell(rule.title, "dim" if dim else "bold")
    steps = Table.grid(padding=(0, 1), expand=True)
    steps.add_column(no_wrap=True)
    steps.add_column(ratio=1)
    conditions = _lines(rule.cond) if rule.cond else ["always"]
    steps.add_row(
        _label("IF", "cyan", dim),
        Group(*[_condition_line(line, dim, rule.values) for line in conditions]),
    )
    actions = [cell(action.text, "dim" if dim else "bold") for action in rule.actions]
    steps.add_row(_label("DO", "green", dim), Group(*actions))
    warnings = [cell(warning, "yellow") for warning in rule.warnings]
    return Group(title, steps, *warnings)


def _render(table, console):
    return [("raw", line) for line in render_table(table, console)]


def _rules_table(rules, console):
    table = Table(box=box.ROUNDED, header_style="bold", show_lines=True, expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Details", ratio=1)
    for rule in rules:
        style = "dim" if _is_generated(rule) else ""
        table.add_row(
            cell(str(rule.number), style),
            cell(_source_label(rule), style),
            _details(rule),
        )
    return _render(table, console)


def _sender_text(rule):
    names = [value for _, value in rule.senders]
    shown = ", ".join(names[:LIST_LIMIT])
    extra = len(names) - LIST_LIMIT
    return shown + (f" +{extra} more" if extra > 0 else "")


def _summary_table(rules, console):
    table = Table(box=box.ROUNDED, header_style="bold")
    table.add_column("Sender", overflow="fold")
    table.add_column("Outcome", overflow="fold")
    table.add_column("Rule", no_wrap=True)
    for rule in rules:
        reference = cell(f"{rule.number} {_source_label(rule)}", "dim")
        if rule.warnings:
            reference.append(cell(" ❗", "yellow"))
        outcome = cell(" ".join(action.short for action in rule.actions), "bold")
        table.add_row(cell(_sender_text(rule)), outcome, reference)
    return _render(table, console)


def _summary(rules, console):
    with_senders = [rule for rule in rules if rule.senders]
    if not with_senders:
        return []
    return [
        ("head", "SUMMARY"),
        *_summary_table(with_senders, console),
        ("blank", ""),
    ]


SECTIONS = {
    "mine": "YOUR RULES",
    "ui": "FASTMAIL UI RULES",
    "after": "YOUR RULES (AFTER THE UI RULES)",
}


def _section_of(rule):
    if rule.source == "ui":
        return "ui"
    return "after" if rule.source == AFTER_UI else "mine"


def _sections(rules):
    grouped = {}
    for rule in rules:
        grouped.setdefault(_section_of(rule), []).append(rule)
    return [(key, grouped[key]) for key in SECTIONS if key in grouped]


def _disabled_note(disabled):
    return [("note", f"⏸ Disabled in Fastmail: {title}") for title in disabled]


def _section_title(rule):
    if rule.source == "ui":
        return SECTIONS["ui"]
    if rule.source == "fastmail":
        return "FASTMAIL GENERATED"
    return f"YOUR RULES ({rule.source})"


def _runs(rules):
    runs = []
    for rule in rules:
        title = _section_title(rule)
        if runs and runs[-1][0] == title:
            runs[-1][1].append(rule)
        else:
            runs.append((title, [rule]))
    return runs


def _layout_sequence(rules, console, disabled):
    out = _summary(rules, console)
    note = "Rules are listed in the order they run. Fastmail's own rules are dimmed."
    out += [("head", "RULES"), ("note", note), ("blank", "")]
    for title, run in _runs(rules):
        out += [("section", f"── {title} ──"), *_rules_table(run, console)]
        if run[0].source == "ui":
            out += _disabled_note(disabled)
        out.append(("blank", ""))
    return out[:-1]


def _layout(rules, console, disabled=()):
    out = _summary(rules, console)
    note = (
        "Every rule below runs only while nothing earlier has stopped the message. "
        "Order: your rules, then Fastmail's UI rules, then your bottom rules."
    )
    out += [
        ("head", "RULES"),
        *[("note", line) for line in textwrap.wrap(note, console.width)],
        ("blank", ""),
    ]
    for key, section_rules in _sections(rules):
        out += [
            ("section", f"── {SECTIONS[key]} ──"),
            *_rules_table(section_rules, console),
        ]
        if key == "ui":
            out += _disabled_note(disabled)
        out.append(("blank", ""))
    return out[:-1]


def _paint(kind, text, console):
    if kind in ("head", "section"):
        return styled(console, text, "bold")
    if kind == "note":
        return styled(console, text, "dim")
    return text


def render(rules, console=None, disabled=(), sequence=False):
    if not rules:
        return "No rules."
    console = console or make_console("never")
    build = _layout_sequence if sequence else _layout
    layout = build(rules, console, disabled)
    return "\n".join(_paint(kind, text, console) for kind, text in layout)
