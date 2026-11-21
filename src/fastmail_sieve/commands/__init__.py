from fastmail_sieve.commands import (
    assemble,
    auth,
    diff,
    doctor,
    explain,
    folders,
    init,
    lint,
    migrate,
    pull,
    push,
)

GROUPS = (
    ("Set up", (init, auth, doctor)),
    ("Sync with Fastmail", (pull, diff, push)),
    ("Check", (lint,)),
    ("Understand", (explain,)),
    ("Tools", (migrate, folders, assemble)),
)
ALL = tuple(command for _, commands in GROUPS for command in commands)
