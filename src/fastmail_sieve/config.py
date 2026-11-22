import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath

CONFIG_FILE = "fastmail-sieve.toml"
FRAGMENT_NAMES = ("top", "middle", "bottom")
OPTIONS = ("rules-dir", "variables-file")


@dataclass(frozen=True)
class Config:
    rules_dir: str = "rules"
    variables_file: str = "variables.toml"

    @property
    def fragment_files(self):
        return tuple(f"{self.rules_dir}/{name}.sieve" for name in FRAGMENT_NAMES)


_current = Config()


def current():
    return _current


def use(config):
    global _current
    _current = config


def _trusted(directory):
    """Whether this user controls the directory: someone else's, or a world-writable
    one such as /tmp, could plant rules that a push would send to your account."""
    if not hasattr(os, "getuid"):
        return True
    info = directory.stat()
    return info.st_uid == os.getuid() and not info.st_mode & stat.S_IWOTH


def find_root(start):
    """The nearest directory, from `start` upwards, that has a config file or a
    rules fragment. `start` is the user's own choice; a parent must be trusted."""
    fragments = Config().fragment_files
    for directory in (start, *start.parents):
        if directory != start and not _trusted(directory):
            continue
        if (directory / CONFIG_FILE).is_file() or any(
            (directory / name).is_file() for name in fragments
        ):
            return directory
    return None


def _inside(root, key, value):
    """A path from the config file, which a cloned repository controls: it must be
    relative and stay inside the project, so a command cannot write elsewhere."""
    path = PurePath(value)
    inside = (
        value
        and not path.is_absolute()
        and ".." not in path.parts
        and (Path(root) / path).resolve().is_relative_to(Path(root).resolve())
    )
    if not inside:
        raise RuntimeError(
            f"{CONFIG_FILE}: {key} must be a relative path inside the project"
        )
    return value


def load_config(root):
    path = root / CONFIG_FILE
    if not path.is_file():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"{CONFIG_FILE}: {error}") from error
    unknown = sorted(set(data) - set(OPTIONS))
    if unknown:
        raise RuntimeError(
            f"{CONFIG_FILE}: unknown option {', '.join(unknown)} (known: {', '.join(OPTIONS)})"
        )
    for key, value in data.items():
        if not isinstance(value, str):
            raise RuntimeError(f"{CONFIG_FILE}: {key} must be a string")
    defaults = Config()
    return Config(
        rules_dir=_inside(root, "rules-dir", data.get("rules-dir", defaults.rules_dir)),
        variables_file=_inside(
            root,
            "variables-file",
            data.get("variables-file", defaults.variables_file),
        ),
    )
