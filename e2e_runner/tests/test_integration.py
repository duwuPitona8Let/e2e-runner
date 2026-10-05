"""Real-browser run against demo_app. Skipped unless demo_app is running on :8080.

    cd demo_app && python3 app.py
    pytest -m integration
"""
import urllib.request
from pathlib import Path

import pytest

from e2e_runner.discovery import discover_tests
from e2e_runner.runner import run_suite

DEMO_URL = "http://localhost:8080"
DEMO_TESTS = Path(__file__).resolve().parents[2] / "demo_app" / "tests"


def _demo_app_running() -> bool:
    try:
        with urllib.request.urlopen(DEMO_URL, timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _demo_app_running(), reason="demo_app is not running on :8080"),
]


@pytest.mark.parametrize("workers", [1, 4])
def test_demo_suite_has_expected_results(workers: int) -> None:
    tests = discover_tests(DEMO_TESTS)

    run = run_suite(tests, project_name="integration", base_url=DEMO_URL, workers=workers)

    failed = sorted(r.test_case.function_name for r in run.results if r.status.value != "passed")
    assert (run.total, run.passed) == (25, 22)
    assert failed == ["test_login_as_unknown_user", "test_nonexistent_item", "test_wrong_title"]
