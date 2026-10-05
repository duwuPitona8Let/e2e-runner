from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "e2e.yaml"

DEFAULTS: dict[str, Any] = {
    "project":     "default",
    "base_url":    "",
    "tests":       ".",
    "workers":     1,
    "timeout":     30000,
    "retry":       0,
    "fail_fast":   False,
    "headed":      False,
    "trace":       False,
    "html_report": "",
    "json_report": "",
}

CONFIG_TEMPLATE = """\
# e2e runner configuration
# CLI flags always override values in this file.

project: default        # project name saved in history
base_url: ""            # URL of the app under test, e.g. http://localhost:8080
tests: .                # path to tests directory or file

workers: 1              # parallel workers (1 = sequential)
timeout: 30000          # browser action timeout in ms
retry: 0                # retry failed tests N times
fail_fast: false        # stop on first failure
headed: false           # show browser window during tests
trace: false            # save Playwright trace (.zip) for failed tests

html_report: ""         # path to save HTML report (empty = skip)
json_report: ""         # path to save JSON report (empty = skip)
"""


class ConfigError(Exception):
    """e2e.yaml exists but is malformed or has values of the wrong type."""


def find_config() -> Path | None:
    """Walk up from cwd looking for e2e.yaml."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path) -> dict[str, Any]:
    """Read e2e.yaml and merge it over DEFAULTS. Raises ConfigError on bad content."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping of key: value, got {type(data).__name__}")

    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise ConfigError(f"{path}: unknown key(s): {', '.join(map(str, unknown))}")

    return {key: _coerce(path, key, data.get(key, default), default) for key, default in DEFAULTS.items()}


def _coerce(path: Path, key: str, value: Any, default: Any) -> Any:
    """Convert a YAML value to the type of its default, e.g. retry: "2" -> 2."""
    if value is None:
        return default
    # bool is checked before int because bool is a subclass of int.
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise ConfigError(f"{path}: '{key}' must be true or false, got {value!r}")
    if isinstance(default, int):
        if isinstance(value, bool):
            raise ConfigError(f"{path}: '{key}' must be an integer, got {value!r}")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{path}: '{key}' must be an integer, got {value!r}") from None
    return str(value)
