import http.client
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import click

from fastmail_sieve import commands, config
from fastmail_sieve.ui.tables import echo

PROG = "fastmail-sieve"


def package_version():
    try:
        return version(PROG)
    except PackageNotFoundError:
        return "unknown"


class GroupedGroup(click.Group):
    """A command group whose help lists the commands by what they are for."""

    def format_commands(self, ctx, formatter):
        limit = formatter.width - 6 - max(len(name) for name in self.commands)
        for title, modules in commands.GROUPS:
            rows = [
                (name, self.commands[name].get_short_help_str(limit))
                for name in (module.command.name for module in modules)
                if name
            ]
            with formatter.section(title):
                formatter.write_dl(rows)


def _show_version(ctx, param, value):
    if value:
        click.echo(f"{PROG} {package_version()}")
        ctx.exit()


@click.group(
    cls=GroupedGroup,
    name=PROG,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Run `fastmail-sieve COMMAND --help` for a command's options.",
)
@click.option(
    "--version",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_version,
    help="Show the version and exit.",
)
@click.option(
    "-C",
    "--project",
    "project_dir",
    metavar="DIR",
    help="use the project in DIR (default: the current directory, or the nearest "
    "parent that has rules fragments or a fastmail-sieve.toml)",
)
@click.pass_context
def cli(ctx, project_dir):
    """Keep Fastmail Sieve rules in git: lint, explain, migrate and sync."""
    ctx.obj = lambda command_name: find_project(project_dir, command_name)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help(), err=True)
        ctx.exit(2)


for _module in commands.ALL:
    cli.add_command(_module.command)


def find_project(directory, command_name):
    """The project to work on, without changing directory: in `directory` (or the
    current one) for `init`, otherwise the nearest project at or above it."""
    start = Path.cwd()
    if directory:
        start = Path(directory)
        if not start.is_dir():
            raise RuntimeError(f"{directory} is not a directory")
        start = start.resolve()
    if command_name == "init":
        return config.Project.load(start)
    root = config.find_root(start)
    if root is None:
        return config.Project(start)
    if root != start:
        echo(f"using the project at {root}", err=True)
    return config.Project.load(root)


def main(argv=None):
    try:
        return cli.main(args=argv, prog_name=PROG, standalone_mode=False) or 0
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort:
        return 130
    except (RuntimeError, OSError, ValueError, http.client.HTTPException) as error:
        echo(f"✗ {error}", err=True, style="red")
        return 1
    except KeyboardInterrupt:
        return 130
