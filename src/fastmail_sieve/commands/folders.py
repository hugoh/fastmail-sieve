from fastmail_sieve.commands._options import progress_console
from fastmail_sieve.fastmail.credentials import load_credentials
from fastmail_sieve.fastmail.mailboxes import fetch_mailboxes, render


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "folders", help="list Fastmail folders and their ids"
    )
    parser.add_argument(
        "filter", nargs="?", help="only folders whose path contains this text"
    )
    parser.set_defaults(run=run)


def run(args):
    console = progress_console()
    credentials = load_credentials(session_required=False)
    try:
        with console.status("Reading the folders from Fastmail…"):
            mailboxes = fetch_mailboxes(credentials)
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(
            f"Could not read the folders from Fastmail: {error}"
        ) from error
    lines = render(mailboxes, args.filter)
    print("\n".join(lines) if lines else "No matching folders.")
    return 0
