from __future__ import annotations

import json
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

# key -> comment, in file order; None marks a blank line between groups.
_LAYOUT: list[tuple[str, str] | None] = [
    ("project", "project name saved in history"),
    ("base_url", "URL of the app under test, e.g. http://localhost:8080"),
    ("tests", "path to tests directory or file"),
    None,
    ("workers", "parallel workers (1 = sequential)"),
    ("timeout", "browser action timeout in ms"),
    ("retry", "retry failed tests N times"),
    ("fail_fast", "stop on first failure"),
    ("headed", "show browser window during tests"),
    ("trace", "save Playwright trace (.zip) for failed tests"),
    None,
    ("html_report", "path to save HTML report (empty = skip)"),
    ("json_report", "path to save JSON report (empty = skip)"),
]


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a valid YAML scalar


def render_config(values: dict[str, Any]) -> str:
    """e2e.yaml text with comments for the given values (missing keys use DEFAULTS)."""
    lines = ["# e2e runner configuration", "# CLI flags always override values in this file.", ""]
    for entry in _LAYOUT:
        if entry is None:
            lines.append("")
            continue
        key, comment = entry
        field = f"{key}: {_yaml_scalar(values.get(key, DEFAULTS[key]))}"
        lines.append(f"{field:<36} # {comment}")
    return "\n".join(lines) + "\n"


CONFIG_TEMPLATE = render_config(DEFAULTS)


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
