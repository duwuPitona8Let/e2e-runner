from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

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

html_report: ""         # path to save HTML report (empty = skip)
json_report: ""         # path to save JSON report (empty = skip)
"""


def find_config() -> Optional[Path]:
    """Walk up from cwd looking for e2e.yaml."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return {k: data.get(k, v) for k, v in DEFAULTS.items()}
