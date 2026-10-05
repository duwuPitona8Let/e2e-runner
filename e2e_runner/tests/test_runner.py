from pathlib import Path

import pytest

from e2e_runner.discovery import discover_tests
from e2e_runner.models import TestCase as Case
from e2e_runner.models import TestStatus as Status
from e2e_runner.runner import run_suite

SUITE = """
attempts = 0

def test_pass(page, base_url):
    assert page is not None
    assert base_url == "http://app"

def test_fail():
    assert 1 == 2, "numbers differ"

def test_error():
    raise ValueError("bad value")

def test_flaky():
    global attempts
    attempts += 1
    assert attempts > 1, "first attempt fails"
"""


@pytest.fixture
def suite(write_test_file, tmp_path) -> dict[str, Case]:
    write_test_file("test_suite.py", SUITE)
    return {t.function_name: t for t in discover_tests(tmp_path / "suite")}


def _run(tests, **kwargs):
    kwargs.setdefault("base_url", "http://app")
    return run_suite(tests=list(tests), project_name="unit", **kwargs)


def test_statuses_and_messages(fake_playwright, suite) -> None:
    run = _run([suite["test_pass"], suite["test_fail"], suite["test_error"]])

    by_name = {r.test_case.function_name: r for r in run.results}
    assert by_name["test_pass"].status is Status.PASSED
    assert by_name["test_fail"].status is Status.FAILED
    assert by_name["test_fail"].error_message == "numbers differ"
    assert by_name["test_error"].status is Status.ERROR
    assert by_name["test_error"].error_message == "ValueError: bad value"
    assert (run.passed, run.failed, run.errored) == (1, 1, 1)


def test_fresh_context_per_test_with_base_url_and_timeout(fake_playwright, suite) -> None:
    _run([suite["test_pass"], suite["test_fail"]], timeout=1234)

    contexts = fake_playwright.contexts
    assert len(contexts) == 2
    assert all(c.closed for c in contexts)
    assert all(c.base_url == "http://app" and c.timeout == 1234 for c in contexts)
    assert fake_playwright.browsers_launched == fake_playwright.browsers_closed == 1


def test_screenshot_only_for_failures(fake_playwright, suite) -> None:
    run = _run([suite["test_pass"], suite["test_fail"]])

    passed, failed = run.results
    assert passed.screenshot_path is None
    assert Path(failed.screenshot_path).is_file()


def test_retry_turns_flaky_test_green(fake_playwright, suite) -> None:
    run = _run([suite["test_flaky"]], retries=1)
    assert run.results[0].status is Status.PASSED
    assert len(fake_playwright.contexts) == 2


def test_retry_gives_up_after_n_attempts(fake_playwright, suite) -> None:
    run = _run([suite["test_fail"]], retries=2)
    assert run.results[0].status is Status.FAILED
    assert len(fake_playwright.contexts) == 3  # first attempt + 2 retries


def test_fail_fast_stops_sequential_run(fake_playwright, suite) -> None:
    run = _run([suite["test_fail"], suite["test_pass"]], fail_fast=True)
    assert [r.test_case.function_name for r in run.results] == ["test_fail"]
    assert fake_playwright.browsers_closed == 1


def test_on_result_called_for_every_test(fake_playwright, suite) -> None:
    seen = []
    _run(suite.values(), on_result=seen.append)
    assert len(seen) == len(suite)


def test_trace_saved_only_for_failed_tests(fake_playwright, suite) -> None:
    run = _run([suite["test_pass"], suite["test_fail"]], trace=True)

    passed, failed = run.results
    assert all(c.tracing.started for c in fake_playwright.contexts)
    assert passed.trace_path is None
    assert failed.trace_path.endswith(".zip")
    assert Path(failed.trace_path).is_file()


def test_parallel_keeps_order_and_uses_one_browser_per_worker(fake_playwright, suite) -> None:
    tests = [suite["test_pass"], suite["test_fail"], suite["test_error"], suite["test_pass"]]

    run = _run(tests, workers=2)

    assert [r.test_case.function_name for r in run.results] == [t.function_name for t in tests]
    assert fake_playwright.browsers_launched == 2
    assert fake_playwright.browsers_closed == 2


@pytest.mark.parametrize("workers", [1, 3])
def test_browser_launch_failure_reports_errors_instead_of_crashing(fake_playwright, suite, workers) -> None:
    fake_playwright.launch_error = RuntimeError("Executable doesn't exist")

    run = _run(suite.values(), workers=workers)

    assert run.total == len(suite)
    assert all(r.status is Status.ERROR for r in run.results)
    assert "Browser failed to start" in run.results[0].error_message


def test_unloadable_test_function_is_an_error(fake_playwright) -> None:
    ghost = Case(name="x::test_ghost", file_path="/nope/test_x.py", function_name="test_ghost", module_name="nope")

    run = _run([ghost])

    assert run.results[0].status is Status.ERROR
    assert run.results[0].error_message == "Could not load test function"
