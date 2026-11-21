import re
import tomllib

FOLDER_LABEL = re.compile(r"^l\d+_(.+)$")


def load_descriptions(text):
    return {name.lower(): table for name, table in tomllib.loads(text).items()}


def folder_label(name):
    folder = FOLDER_LABEL.match(name)
    if not folder:
        return None
    return folder.group(1).replace("_", " ").strip().removeprefix("inbox ").strip()


def lookup(name, descriptions):
    entry = descriptions.get(name)
    if entry:
        return entry
    label = folder_label(name)
    if label is None:
        return None
    return {
        "description": (
            f"Set by a Fastmail rule to file a copy of the message into the '{label}' folder."
        ),
        "when_yes": f"a rule selected the {label} folder",
        "set_yes": f"🔖 label: copy into the {label} folder",
        "set_yes_move": f"📁 move to the {label} folder",
    }
