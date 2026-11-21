# fastmail-sieve

Keep your Fastmail Sieve rules in git, and lint, explain, diff and push them
from the command line. **Unofficial**: not made or supported by Fastmail, and
it uses an undocumented Fastmail API that can change without notice (see
[How it works](#how-it-works)).

- **Edit rules as files** in three fragments (`rules/top.sieve`,
  `rules/middle.sieve`, `rules/bottom.sieve`), review them in git, and push
  them to Fastmail.
- **`lint`** is the one check: format, syntax (including Fastmail's own Sieve
  extensions such as `jmapquery` and `mailboxid`), variables, and that every
  folder id in your rules still exists with the right name. It ends with
  warnings (overlaps, duplicates, disabled rules). `lint --fix` reformats your
  rules.
- **`explain`** shows your rules and your Fastmail UI rules in plain language,
  the whole script, or its variables.
- **`migrate`** turns your Fastmail UI rules into custom Sieve rules.
- **`push`** shows the diff and asks before it changes anything.

## How it works

Fastmail builds your Sieve script from several parts: its own generated code
(spam, blocked senders, your Settings > Filters & Rules), and three places
for your own code that run before and after those parts. `fastmail-sieve`
reads the whole script, shows you all of it, and only ever writes those three
blocks, which are your three fragment files.

Each block is wrapped in a pair of marker comments, which must stay where they
are:

```text
#### Managed by fastmail-sieve: start ####
#### Managed by fastmail-sieve: end ####
```

`init --remote` adds them to a script that has none. A script that was
managed with [Fastmail-Sieve-Sync](#relationship-to-fastmail-sieve-sync)
already has its `Managed by Sieve Sync Start` and `End` markers; those are
recognised too and left as they are.
`init --remote --convert-markers` replaces them with this tool's own markers,
after asking: your rules are untouched, but Sieve-Sync no longer recognises the
blocks, so it is a one-way step.

Fastmail has no official API for this. The tool calls the private
`SieveBlocks/get` and `SieveBlocks/set` JMAP methods that Fastmail's own
Sieve editor uses, with the token and cookie of a logged-in web session (see
[Credentials](#credentials)). **That can break at any time** and carries the
risks described there. `fastmail-sieve doctor` tells you what works for your
account, and whether Fastmail now advertises an official Sieve API (RFC 9661)
that this tool could use instead.

Fastmail's [API Terms of Service](https://www.fastmail.com/policies/api-terms-of-service/)
list "use any unpublished APIs" among the prohibited uses. `SieveBlocks` is
unpublished. It is not clear whether that clause covers a personal tool that
only works on your own account, and this project is not a lawyer: read the
terms and decide for yourself before you use it.

## Install

```sh
uv tool install fastmail-sieve          # or: pipx install fastmail-sieve
uvx fastmail-sieve --help               # or run it without installing
```

Python 3.11 or newer. The optional `auth` extra (`fastmail-sieve[auth]`) is
only for `auth --discover`. The command is also installed as `fmsieve`.

## Quick start

```sh
mkdir my-sieve && cd my-sieve
fastmail-sieve init              # rules/, variables.toml, .gitignore
fastmail-sieve auth              # store your token and cookie (see Credentials)
fastmail-sieve init --remote     # once: add the managed blocks to Fastmail
fastmail-sieve pull              # bring Fastmail's current blocks into rules/
$EDITOR rules/middle.sieve
fastmail-sieve lint --fix        # reformat, then check everything
fastmail-sieve diff              # what a push would change
fastmail-sieve push              # shows the diff, asks, pushes, verifies
```

## Commands

| Command | Does |
|---------|------|
| `init` | Create `rules/`, `variables.toml` and a `.gitignore` line; never overwrites. `--remote` also adds the managed blocks to Fastmail's script (once, asks first); `--convert-markers` also replaces Sieve-Sync's marker comments with this tool's own (one way) |
| `auth` | Check the token and cookie against Fastmail and store them in the keychain. `auth status` shows which credentials are available and where each comes from |
| `doctor` | Check the project files, the credentials and what Fastmail lets them do |
| `pull` | Overwrite the three fragments with Fastmail's managed blocks. It lists the files with local changes and asks first (`--yes` skips the question) |
| `push` | Check everything, show the diff, ask, push the managed blocks, then verify with a fresh pull. `--yes` skips the question |
| `diff` | Show what a push would change (`+` added, `-` removed) |
| `assemble` | Print the full script (Fastmail's parts plus your fragments); `--output FILE` writes it |
| `lint` | The one check, as a checklist that stops at the first failure: format and syntax of your rules, then the assembled script (syntax, markers, variables), the folder stable ids and names, and finally the warnings (overlaps, duplicate or conflicting UI rules, disabled UI rules, stale variable descriptions), which are shown but do not fail. `--fix` reformats your rules first (indentation and `:mailboxid` folder names); `--strict` makes warnings fail; `--offline` skips everything that needs Fastmail; `--from-file FILE` checks a saved script; `--live` checks Fastmail's script exactly as it is now and ignores your files (see below) |
| `explain [TOPIC]` | `rules` (the default): a summary table, then your rules and your UI rules as tables. `script`: the whole script in execution order. `variables`: the script's variables and where they are set and read |
| `migrate` | Print custom rules equivalent to your enabled Fastmail UI rules |
| `folders` | List Fastmail folders and their ids (`folders tax` filters by path) |

### Local and live

Two views of the script exist. **Local** (the default) is what a `push`
would produce: Fastmail's script with your `rules/` files in the managed
blocks. **Live** is Fastmail's script exactly as it is now. `lint --live` and
`explain --live` judge the live one and never read your rules, so they catch
what only exists there: a folder you deleted in Fastmail, or a rule made in
Fastmail's own editor. `diff` shows how the two differ.

Commands that need the script (`assemble`, `diff`, `explain`, `lint`,
`migrate`) fetch it themselves; pass `--from-file FILE` to use a
saved copy with no network. `fastmail-sieve COMMAND --help` lists the options.

## Credentials

`fastmail-sieve` needs the **browser session token and cookie** of a logged-in
Fastmail session. Fastmail has no Sieve scope for API tokens, so a normal API
token cannot read or write the script (it is enough for folder lookups, see
below).

> **The token and cookie are a full web session.** Whoever has both can act as
> you in Fastmail: read, send and delete mail, change filters (including
> forwarding rules) and create API tokens. Treat them like your password.
> Logging out of that session in Fastmail revokes them. How long a pair lasts is
> not documented by Fastmail.

### Getting them

1. In a browser signed in to Fastmail, open Settings > Filters & Rules > Edit
   custom Sieve code, and open the developer tools on the Network tab.
2. Edit anything in the Sieve box and click Save. Then cancel the edit: do not
   keep it.
3. Find the request that appears (a POST to `api.fastmail.com`).
4. Either right-click it and choose Copy > Copy as cURL, then run
   `pbpaste | fastmail-sieve auth --stdin` (the command is read from standard
   input, so nothing secret lands in your shell history), or copy the value
   after `Authorization: Bearer` (it starts with `fma1-`) and the `Cookie`
   header and run `fastmail-sieve auth` to paste them into two hidden prompts.

`auth` checks the pair against Fastmail and stores it in the keychain (service
`fastmail-sieve-rules`). Run it again when commands fail with HTTP 401.

`fastmail-sieve auth --discover` can look for the cookie for you in the Fastmail
desktop app and in Safari and Chrome. **It reads data that belongs to other
apps**: it asks the macOS keychain for the "Fastmail Safe Storage" key and
decrypts the app's cookie database. It is off by default, needs the `auth`
extra (`pip install 'fastmail-sieve[auth]'`), and prints what it will read
before it does.

### Where credentials are read from

In this order, the first that has them wins:

| Source | How |
|--------|-----|
| Environment | `FASTMAIL_SIEVE_TOKEN` and `FASTMAIL_SIEVE_COOKIE` |
| Helper command | `FASTMAIL_SIEVE_CREDENTIAL_COMMAND` prints JSON on stdout |
| Keychain | what `fastmail-sieve auth` stored |

The helper command lets a secret manager supply the pair so that nothing is
stored by this tool. It is run without a shell (use `sh -c '...'` for a
pipeline) and must print `{"token": "fma1-…", "cookie": "…"}`, optionally with
`"api_token"`. For example, `FASTMAIL_SIEVE_CREDENTIAL_COMMAND='op read
op://Private/fastmail-sieve/json'`. It is read from your environment only,
never from a file in the repository.

**Optional API token for folder lookups.** A read-only Fastmail API token
(Settings > Privacy & Security > Connected apps & API tokens, Email scope) in
`FASTMAIL_API_TOKEN` is used for `folders` and the folder checks in `lint`
instead of the session pair. It cannot read or write the script.

There is no command-line option for a token or cookie, because arguments show
up in `ps` and in shell history. Secrets are never printed: `doctor` and error
messages name sources and tiers, not values. Without a keychain (headless
Linux, CI) use environment variables or the helper command. `lint --offline`
needs no credentials at all, so run that in CI; pushing from CI is not
recommended.

`fastmail-sieve auth status` shows, without contacting Fastmail, each source in
the order it is tried (environment, helper command, keychain), what it provides
and whether it is complete, and which credentials each kind of command would
use: the script needs the session pair, while `folders` prefers an API token.
It never prints a value, and it reports a failing helper command or a missing
keychain as a state instead of stopping.

`fastmail-sieve doctor` checks the project files, the credentials, what
Fastmail lets them do (folders, the script, managed blocks) and whether
Fastmail advertises an official Sieve API, and says what to fix.

## Starting a project

`fastmail-sieve init` creates `rules/top.sieve`, `rules/middle.sieve`,
`rules/bottom.sieve`, `variables.toml` and a `.gitignore` entry, and never
overwrites a file. Run `fastmail-sieve init --remote` once to add the three
managed blocks to Fastmail's script if it has none yet (a one-time write that
keeps any code already there), then `fastmail-sieve pull`. Commands find the
project from any subdirectory, or use `-C DIR`. An optional
`fastmail-sieve.toml` in the project root can set `rules-dir` and
`variables-file`.

## Reading `explain`

Rules are numbered in the order they run: your `top` and `middle` rules, then
Fastmail's UI rules, then your `bottom` rules. Each section has its own
heading. Output is coloured on a terminal; `NO_COLOR=1` or `--color never`
turns it off, and `--width N` sets the table width.

| Marker | Meaning |
|--------|---------|
| 📌 | Pin (flag) the message |
| 📁 | Move: file into a folder and stop |
| 🔖 | Label: copy into a folder and keep going |
| 🚮 | Trash |
| 🚫 | Junk / spam |
| 🛑 | Stop applying further rules |
| ❗ | Duplicate UI rule, or your rule overlaps a UI rule |

In conditions the wording is dim and the values being matched (addresses,
domains, subjects) are shown at normal brightness; with `explain script`,
Fastmail's own rules are dim throughout. Variable wording comes from `variables.toml`.

## Folder ids and names

Rules file mail with `fileinto :mailboxid "ID" "name"`. The id is what Fastmail
uses and it survives a folder rename; the name is only a hint, but it has to
be right for `lint` to pass. In Sieve the name is the folder's path with `.`
separators and an `INBOX.` prefix: `INBOX.finance.taxes`, and
`INBOX.Inbox.Shopping` for a folder inside the Inbox. `fastmail-sieve lint --fix`
writes them that way, and `lint` compares them with the live folders. Look ids
up with `fastmail-sieve folders`.

## Migrating a UI rule to a custom rule

1. Run `fastmail-sieve migrate` and review the output. It supports UI rules
   that match plain `from` searches and file into one folder, optionally
   skipping the Inbox, pinning and stopping. Anything else is an error
   naming the rule and the reason.
2. Paste the rules into a block of `rules/middle.sieve`, then run
   `fastmail-sieve lint --fix`.
3. `fastmail-sieve diff`, then `fastmail-sieve push`.
4. Disable or delete the UI rule in Fastmail. Until you do, `explain` and
   `lint` flag the overlap.

A search that isn't a plain `from` address becomes a `jmapquery` rule that
reuses the UI rule's exact search, so it matches what the UI rule matches. This
is the only way to express a contact-card rule. Short searches are one quoted
line; long ones use a multi-line `text:` block, whose closing `.` must start at
column 0. Only things with no translation (for example a variable other than
skip-inbox, pin or stop, or several folders in one rule) are errors.

Translation differences: `from:x` in a UI rule is a text search (it also
matches display names and substrings), while the custom rule matches the
address exactly (`:domain` for bare domains). Test a sample message in
Fastmail's Sieve tester.

## Using it in CI or a pre-commit hook

`fastmail-sieve lint --offline` (add `--fix` for a pre-commit hook) needs no
credentials and no network. Everything else talks to Fastmail with a full web
session, so keep it out of CI (see [Credentials](#credentials)).

## Development

```sh
uv sync --all-extras
uv run python -m unittest discover -s tests -t .
mise run lint            # every check, via hk
mise run package-check   # build, twine check, install the wheel in a clean env
```

Versions come from git tags (`hatch-vcs`), and releases are published to PyPI
by trusted publishing from CI. The Python is a library of small modules under
`src/fastmail_sieve/` with one small module per command in `commands/`;
library code never prints or exits.

## Relationship to Fastmail-Sieve-Sync

[Fastmail-Sieve-Sync](https://github.com/fuyu0425/Fastmail-Sieve-Sync) (MIT,
by Yu-Fu Fu) keeps the managed blocks of your Fastmail Sieve script in sync
with a file. It is where this project learned that the private `SieveBlocks`
methods exist and what they carry, and it defined the `Managed by Sieve Sync`
markers around the managed blocks.

**What this project takes from it.** The approach (read and write the script
through `SieveBlocks`), the idea of marking the managed blocks, and the way the
blocks are handled. That part is reimplemented in this project's own code,
written from reading Sieve-Sync's source; no source file was copied verbatim.
Its license and copyright notice are reproduced in [`NOTICE`](NOTICE).

**Why a separate tool rather than a dependency or a fork.**

- Sieve-Sync is a command-line tool, not a library, and it is not published on
  PyPI. A package on PyPI cannot depend on a git URL, so depending on it meant
  running it as a subprocess: a temporary config file holding your token, its
  debug output to parse, and a scratch file for the script.
- The checks and the diff here need the script's parts in memory, and
  `push` verifies the result with a fresh read.
- The scope is wider than syncing: lint, explain, migrate and folder
  validation.

**If you only need to sync a file**, Sieve-Sync is smaller and may be all you
need. A script that Sieve-Sync manages keeps its markers here, so you can
switch to this tool and back. A script prepared by this tool has its own
markers, which Sieve-Sync does not recognise, so do not run both tools on the
same script. This project is not affiliated with Sieve-Sync or its author.

## Credits and license

Sieve parsing uses [sievelib](https://github.com/tonioo/sievelib). The session
and method-call flow is standard JMAP
([RFC 8620](https://www.rfc-editor.org/rfc/rfc8620)). See the previous section
and [`NOTICE`](NOTICE) for Sieve-Sync.

MIT, see `LICENSE` and `NOTICE`. "Fastmail" is a trademark of its owner; this
project is not affiliated with or endorsed by Fastmail.
