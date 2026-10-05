"""Fixtures: setup/teardown hooks and shared login (use_auth / auth_<name>)."""
import pytest
from conftest import FAKE_STORAGE_STATE

from e2e_runner.discovery import DiscoveryError, discover_tests, get_conftests, get_module
from e2e_runner.models import TestStatus as Status
from e2e_runner.runner import run_suite

HOOKS = """
EVENTS = []

def setup_module(base_url):
    EVENTS.append(("setup_module", base_url))

def teardown_module():
    EVENTS.append(("teardown_module",))

def setup_function(page):
    EVENTS.append(("setup_function",))

def teardown_function():
    EVENTS.append(("teardown_function",))

def test_a():
    EVENTS.append(("test_a",))

def test_b():
    EVENTS.append(("test_b",))
    assert False, "b fails"

def test_c():
    EVENTS.append(("test_c",))
"""


def _run(tests, **kwargs):
    kwargs.setdefault("base_url", "http://app")
    return run_suite(tests=list(tests), project_name="unit", **kwargs)


def _status(run):
    return {r.test_case.function_name: r.status for r in run.results}


def _error(run, name):
    return next(r.error_message for r in run.results if r.test_case.function_name == name)


# ── setup / teardown hooks ───────────────────────────────────


def test_hooks_run_in_xunit_order(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file("test_hooks.py", HOOKS)
    tests = discover_tests(tmp_path / "suite")

    _run(tests)

    assert get_module(tests[0]).EVENTS == [
        ("setup_module", "http://app"),
        ("setup_function",), ("test_a",), ("teardown_function",),
        ("setup_function",), ("test_b",), ("teardown_function",),
        ("setup_function",), ("test_c",), ("teardown_function",),
        ("teardown_module",),
    ]  # fmt: skip


def test_module_hooks_run_once_in_parallel(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file("test_hooks.py", HOOKS)
    tests = discover_tests(tmp_path / "suite")

    _run(tests, workers=3)

    events = get_module(tests[0]).EVENTS
    assert events.count(("setup_module", "http://app")) == 1
    assert events.count(("teardown_module",)) == 1
    assert events[0][0] == "setup_module"
    assert events[-1] == ("teardown_module",)
    assert events.count(("setup_function",)) == 3


def test_setup_function_runs_on_every_retry(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file("test_hooks.py", HOOKS)
    tests = [t for t in discover_tests(tmp_path / "suite") if t.function_name == "test_b"]

    _run(tests, retries=2)

    events = get_module(tests[0]).EVENTS
    assert events.count(("setup_module", "http://app")) == 1
    assert events.count(("setup_function",)) == 3


def test_teardown_module_runs_after_fail_fast(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file("test_hooks.py", HOOKS)
    tests = discover_tests(tmp_path / "suite")

    run = _run(tests, fail_fast=True)

    assert run.total == 2  # stopped after test_b
    assert get_module(tests[0]).EVENTS[-1] == ("teardown_module",)


def test_setup_module_failure_errors_the_file_only(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file(
        "test_broken_setup.py",
        """
        TORN_DOWN = []
        def setup_module(): raise RuntimeError("db is down")
        def teardown_module(): TORN_DOWN.append(True)
        def test_x(): pass
        def test_y(): pass
        """,
    )
    write_test_file("test_other.py", "def test_ok(): pass\n")
    tests = {t.function_name: t for t in discover_tests(tmp_path / "suite")}

    run = _run(tests.values())

    assert _status(run) == {"test_x": Status.ERROR, "test_y": Status.ERROR, "test_ok": Status.PASSED}
    assert _error(run, "test_x") == "setup_module failed: RuntimeError: db is down"
    assert get_module(tests["test_x"]).TORN_DOWN == []  # nothing was set up, so nothing is torn down
    assert len(fake_playwright.contexts) == 1  # no browser context for the skipped tests


def test_failing_setup_function_is_error_not_failure(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file(
        "test_setup_fn.py",
        """
        RAN = []
        def setup_function(): assert False, "precondition"
        def test_x(): RAN.append(True)
        """,
    )
    tests = discover_tests(tmp_path / "suite")

    run = _run(tests)

    assert run.results[0].status is Status.ERROR
    assert run.results[0].error_message == "setup_function failed: AssertionError: precondition"
    assert get_module(tests[0]).RAN == []


def test_failing_teardown_function(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file(
        "test_teardown_fn.py",
        """
        def teardown_function(): raise RuntimeError("cleanup broke")
        def test_pass(): pass
        def test_fail(): assert False, "real failure"
        """,
    )

    run = _run(discover_tests(tmp_path / "suite"))

    assert _status(run) == {"test_pass": Status.ERROR, "test_fail": Status.FAILED}
    assert _error(run, "test_pass") == "teardown_function failed: RuntimeError: cleanup broke"
    assert _error(run, "test_fail") == "real failure"  # the original failure is kept


# ── shared login: use_auth / auth_<name> ─────────────────────

AUTH_CONFTEST = """
LOGINS = []

def auth_admin(page, base_url):
    LOGINS.append(base_url)
"""

LOGGED_IN = """
use_auth = "admin"

def test_one(page): pass
def test_two(page): pass
def test_three(page): pass
"""


@pytest.mark.parametrize("workers", [1, 3])
def test_login_once_and_reuse_storage_state(fake_playwright, write_test_file, tmp_path, workers) -> None:
    write_test_file("conftest.py", AUTH_CONFTEST)
    write_test_file("test_logged_in.py", LOGGED_IN)
    write_test_file("test_anonymous.py", "def test_anon(page): pass\n")
    tests = discover_tests(tmp_path / "suite")

    run = _run(tests, workers=workers)

    assert run.passed == 4
    assert get_conftests(tests[0])[0].LOGINS == ["http://app"]  # logged in exactly once
    test_contexts = [c for c in fake_playwright.contexts if c.storage_state_in is not None]
    assert len(test_contexts) == 3  # only the use_auth file; test_anon starts logged out
    assert all(c.storage_state_in == FAKE_STORAGE_STATE for c in test_contexts)
    assert all(c.closed for c in fake_playwright.contexts)  # including the login context


def test_failing_auth_errors_dependent_tests_once(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file(
        "conftest.py",
        """
        CALLS = []
        def auth_admin(page):
            CALLS.append(True)
            assert False, "wrong password"
        """,
    )
    write_test_file("test_logged_in.py", LOGGED_IN)
    tests = discover_tests(tmp_path / "suite")

    run = _run(tests)

    assert run.errored == 3
    assert _error(run, "test_one") == "auth 'admin' failed: AssertionError: wrong password"
    assert get_conftests(tests[0])[0].CALLS == [True]  # not retried for every test


@pytest.mark.parametrize(
    ("use_auth", "message"),
    [
        ('"ghost"', "auth 'ghost' not found: define auth_ghost(page) in conftest.py"),
        ("True", "use_auth must be a name like \"admin\", got True"),
    ],
)
def test_bad_use_auth(fake_playwright, write_test_file, tmp_path, use_auth, message) -> None:
    write_test_file("test_x.py", f"use_auth = {use_auth}\ndef test_x(page): pass\n")

    run = _run(discover_tests(tmp_path / "suite"))

    assert run.results[0].status is Status.ERROR
    assert run.results[0].error_message == message


def test_nearest_conftest_and_test_file_win(fake_playwright, write_test_file, tmp_path) -> None:
    write_test_file("conftest.py", "WHO = []\ndef auth_admin(page): WHO.append('root')\n")
    write_test_file("shop/conftest.py", "WHO = []\ndef auth_admin(page): WHO.append('shop')\n")
    write_test_file("shop/test_shop.py", 'use_auth = "admin"\ndef test_s(page): pass\n')
    write_test_file(
        "own/test_own.py",
        'use_auth = "admin"\nWHO = []\ndef auth_admin(page): WHO.append("own")\ndef test_o(page): pass\n',
    )
    tests = {t.function_name: t for t in discover_tests(tmp_path / "suite")}

    _run(tests.values())

    shop_conftest, root_conftest = get_conftests(tests["test_s"])
    assert shop_conftest.WHO == ["shop"]
    assert root_conftest.WHO == []
    assert get_module(tests["test_o"]).WHO == ["own"]


def test_broken_conftest_is_reported(write_test_file, tmp_path) -> None:
    write_test_file("conftest.py", "def auth_admin(:\n")
    write_test_file("test_x.py", "def test_x(): pass\n")
    errors: list[DiscoveryError] = []

    tests = discover_tests(tmp_path / "suite", errors=errors)

    assert [e.file.name for e in errors] == ["conftest.py"]
    assert [t.function_name for t in tests] == ["test_x"]
    assert tests[0].conftest_paths == ()
