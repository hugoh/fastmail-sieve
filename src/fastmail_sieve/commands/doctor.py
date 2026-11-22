import click

from fastmail_sieve.commands._options import invoke
from fastmail_sieve.doctor import Doctor, doctor_steps
from fastmail_sieve.steps import run_steps
from fastmail_sieve.ui.tables import make_console


@click.command(
    "doctor",
    short_help="check the project files, the credentials and what Fastmail lets them do",
)
@click.pass_context
def command(ctx):
    """Check the project files, the credentials and what Fastmail lets them do."""
    invoke(ctx, run, {})


def run(args, project):
    return run_steps(doctor_steps(Doctor(project)), make_console())
