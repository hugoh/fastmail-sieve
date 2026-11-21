from sievelib import commands
from sievelib.parser import Parser

from fastmail_sieve.sieve.script import BLOCK_COUNT as MANAGED_BLOCKS
from fastmail_sieve.sieve.script import ENDS, MARKER_PAIRS, STARTS, contains_marker

_STRING = ["string"]


class FileintoCommand(commands.FileintoCommand):
    args_definition = [
        {
            "name": "specialuse",
            "type": ["tag"],
            "values": [":specialuse"],
            "extra_arg": {"type": _STRING},
            "required": False,
            "extension": "special-use",
        },
        {
            "name": "mailboxid",
            "type": ["tag"],
            "values": [":mailboxid"],
            "extra_arg": {"type": _STRING},
            "required": False,
            "extension": "mailboxid",
        },
        *commands.FileintoCommand.args_definition,
    ]


class Implicit_keep_targetCommand(commands.ActionCommand):
    extension = "vnd.cyrus.implicit_keep_target"
    args_definition = [
        {
            "name": "mailboxid",
            "type": ["tag"],
            "values": [":mailboxid"],
            "extra_arg": {"type": _STRING},
            "required": False,
        },
        {"name": "mailbox", "type": _STRING, "required": True},
    ]


class ProcesscalendarCommand(commands.ActionCommand):
    extension = "processcalendar"
    args_definition = [  # ty: ignore[invalid-assignment]
        {
            "name": "allowpublic",
            "type": ["tag"],
            "values": [":allowpublic"],
            "required": False,
        },
        {
            "name": "deletecancelled",
            "type": ["tag"],
            "values": [":deletecancelled"],
            "required": False,
        },
        *(
            {
                "name": name,
                "type": ["tag"],
                "values": [f":{name}"],
                "extra_arg": {"type": _STRING},
                "required": False,
            }
            for name in ("calendarid", "outcome", "reason")
        ),
    ]


class JmapqueryCommand(commands.TestCommand):
    extension = "vnd.cyrus.jmapquery"
    args_definition = [{"name": "query", "type": _STRING, "required": True}]


class MailboxidexistsCommand(commands.TestCommand):
    extension = "mailboxid"
    args_definition = [
        {"name": "mailbox-ids", "type": _STRING + ["stringlist"], "required": True}
    ]


class AddheaderCommand(commands.ActionCommand):
    extension = "editheader"
    args_definition = [
        {"name": "last", "type": ["tag"], "values": [":last"], "required": False},
        {"name": "field-name", "type": _STRING, "required": True},
        {"name": "value", "type": _STRING, "required": True},
    ]


class StringCommand(commands.TestCommand):
    extension = "variables"
    args_definition = [
        commands.comparator,
        commands.match_type,
        {"name": "source", "type": _STRING + ["stringlist"], "required": True},
        {"name": "key-list", "type": _STRING + ["stringlist"], "required": True},
    ]


commands.comparator["extra_arg"]["values"].append('"i;ascii-numeric"')

commands.add_commands(
    [
        StringCommand,
        AddheaderCommand,
        FileintoCommand,
        Implicit_keep_targetCommand,
        ProcesscalendarCommand,
        JmapqueryCommand,
        MailboxidexistsCommand,
    ]
)


def check_syntax(text):
    parser = Parser()
    return None if parser.parse(text) else parser.error


FASTMAIL_REQUIRE = (
    'require ["fileinto", "reject", "vacation", "envelope", "body", "relational", "regex", '
    '"subaddress", "copy", "mailbox", "mboxmetadata", "servermetadata", "date", "index", '
    '"comparator-i;ascii-numeric", "variables", "imap4flags", "editheader", "duplicate", '
    '"vacation-seconds", "fcc", "vnd.cyrus.jmapquery", "vnd.cyrus.log", "mailboxid", '
    '"special-use", "vnd.cyrus.snooze", "processcalendar", "vnd.cyrus.implicit_keep_target"];\n'
)


def check_fragments(*fragments):
    if any(contains_marker(f) for f in fragments):
        return "fragments must not contain managed-block markers"
    return check_syntax(FASTMAIL_REQUIRE + "".join(fragments))


def check_markers(text):
    found = [line for line in text.splitlines() if line in STARTS + ENDS]
    pairs = list(zip(found[0::2], found[1::2], strict=False))
    if len(found) != 2 * MANAGED_BLOCKS or any(
        pair not in MARKER_PAIRS for pair in pairs
    ):
        return (
            f"expected {MANAGED_BLOCKS} start/end marker pairs in order, found {found}"
        )
    return None
