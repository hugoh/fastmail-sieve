import click

from fastmail_sieve.commands._options import invoke, progress_console
from fastmail_sieve.fastmail.credentials import load_credentials
from fastmail_sieve.fastmail.mailboxes import fetch_mailboxes, render


@click.command("folders", short_help="list Fastmail folders and their ids")
@click.argument("filter", required=False)
@click.pass_context
def command(ctx, **options):
    """List Fastmail folders and their ids. FILTER limits them to folders whose
    path contains that text."""
    invoke(ctx, run, options)


def run(args, project):
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
