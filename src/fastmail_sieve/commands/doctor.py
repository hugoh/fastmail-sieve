from rich.console import Console

from fastmail_sieve.doctor import Doctor, doctor_steps
from fastmail_sieve.steps import run_steps


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "doctor",
        help="check the project files, the credentials and what Fastmail lets them do",
    )
    parser.set_defaults(run=run)


def run(args):
    return run_steps(doctor_steps(Doctor()), Console(highlight=False))
