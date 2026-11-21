import tomllib
from dataclasses import dataclass

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


def find_root(start):
    """The nearest directory, from `start` upwards, that has a config file or a rules fragment."""
    fragments = Config().fragment_files
    for directory in (start, *start.parents):
        if (directory / CONFIG_FILE).is_file() or any(
            (directory / name).is_file() for name in fragments
        ):
            return directory
    return None


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
        rules_dir=data.get("rules-dir", defaults.rules_dir),
        variables_file=data.get("variables-file", defaults.variables_file),
    )
