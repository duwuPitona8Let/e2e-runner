"""Fixtures: setup/teardown hooks and shared login state, found by name — no imports needed.

In a test file:
    setup_module(base_url)            once, before the first test of the file
    teardown_module(base_url)         once, after the last test of the file
    setup_function(page, base_url)    before each test, on the test's page
    teardown_function(page, base_url) after each test, on the test's page
    use_auth = "admin"                every test in the file starts logged in as "admin"

In conftest.py (any directory between the tests root and the test file; nearest wins),
or in the test file itself:
    def auth_admin(page, base_url):   log in once; cookies + localStorage are saved
        ...                           (Playwright storage_state) and reused by every test

All hook arguments are optional and injected by name, like in tests.
"""
from __future__ import annotations

import inspect
import logging
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from playwright.sync_api import Browser, Page

from .discovery import get_conftests, get_module
from .models import TestCase

logger = logging.getLogger(__name__)

AUTH_PREFIX = "auth_"
USE_AUTH = "use_auth"


class HookError(Exception):
    """A setup/teardown hook or an auth function failed; the test is reported as ERROR."""


def call_with_fixtures(func: Callable, page: Page | None = None, base_url: str = "") -> Any:
    """Call ``func`` passing only the fixtures its signature asks for (page, base_url)."""
    available = {"page": page, "base_url": base_url}
    params = inspect.signature(func).parameters
    return func(**{name: value for name, value in available.items() if name in params})


@dataclass
class _ModuleState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    started: bool = False
    error: str | None = None
    torn_down: bool = False


@dataclass
class _AuthState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: bool = False
    storage_state: dict | None = None
    error: str | None = None


class Fixtures:
    """Per-run fixture state. Thread-safe: parallel workers share one instance."""

    def __init__(self, tests: list[TestCase], base_url: str, timeout: int) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._lock = threading.Lock()
        self._remaining = Counter(t.file_path for t in tests)
        self._modules: dict[str, _ModuleState] = {}
        self._auth: dict[str, _AuthState] = {}

    # ── per test ────────────────────────────────────────────

    def prepare(self, test: TestCase, browser: Browser) -> tuple[str | None, dict | None]:
        """Run setup_module (once per file) and resolve the login state.

        Returns (error, storage_state). If error is set the test must not run.
        """
        module = get_module(test)
        if module is None:
            return None, None  # reported as "Could not load test function" by the runner

        state = self._module_state(test.file_path)
        with state.lock:
            if not state.started:
                state.started = True
                setup = getattr(module, "setup_module", None)
                if callable(setup):
                    try:
                        call_with_fixtures(setup, base_url=self._base_url)
                    except Exception as exc:
                        state.error = f"setup_module failed: {type(exc).__name__}: {exc}"
        if state.error:
            return state.error, None

        auth_name = getattr(module, USE_AUTH, None)
        if auth_name is None:
            return None, None
        return self._storage_state(test, module, auth_name, browser)

    def setup_function(self, test: TestCase, page: Page) -> None:
        self._call_hook(test, "setup_function", page)

    def teardown_function(self, test: TestCase, page: Page) -> None:
        self._call_hook(test, "teardown_function", page)

    def test_done(self, test: TestCase) -> None:
        """Count a finished test; runs teardown_module after the file's last test."""
        with self._lock:
            self._remaining[test.file_path] -= 1
            last = self._remaining[test.file_path] == 0
        if last:
            self._teardown_module(test)

    def finish(self, tests: list[TestCase]) -> None:
        """Tear down files whose tests did not all run (fail-fast, browser crash)."""
        seen: set[str] = set()
        for test in tests:
            if test.file_path not in seen:
                seen.add(test.file_path)
                self._teardown_module(test)

    # ── internals ───────────────────────────────────────────

    def _module_state(self, file_path: str) -> _ModuleState:
        with self._lock:
            return self._modules.setdefault(file_path, _ModuleState())

    def _call_hook(self, test: TestCase, name: str, page: Page) -> None:
        module = get_module(test)
        hook = getattr(module, name, None) if module else None
        if not callable(hook):
            return
        try:
            call_with_fixtures(hook, page=page, base_url=self._base_url)
        except Exception as exc:
            raise HookError(f"{name} failed: {type(exc).__name__}: {exc}") from exc

    def _teardown_module(self, test: TestCase) -> None:
        state = self._module_state(test.file_path)
        with state.lock:
            # Only tear down what was set up successfully, and only once.
            if not state.started or state.error or state.torn_down:
                return
            state.torn_down = True
        module = get_module(test)
        teardown = getattr(module, "teardown_module", None) if module else None
        if callable(teardown):
            try:
                call_with_fixtures(teardown, base_url=self._base_url)
            except Exception:
                logger.warning("teardown_module failed for %s", test.file_path, exc_info=True)

    def _storage_state(
        self, test: TestCase, module: ModuleType, auth_name: object, browser: Browser
    ) -> tuple[str | None, dict | None]:
        if not isinstance(auth_name, str) or not auth_name.isidentifier():
            return f"{USE_AUTH} must be a name like \"admin\", got {auth_name!r}", None

        func = _find_auth(test, module, auth_name)
        if func is None:
            return (
                f"auth '{auth_name}' not found: define {AUTH_PREFIX}{auth_name}(page) in conftest.py",
                None,
            )

        # Keyed by the function itself: two conftest.py files may both define auth_admin.
        key = f"{func.__module__}.{func.__qualname__}"
        with self._lock:
            state = self._auth.setdefault(key, _AuthState())
        with state.lock:
            if not state.done:
                state.done = True
                try:
                    state.storage_state = self._log_in(func, browser)
                except Exception as exc:
                    state.error = f"auth '{auth_name}' failed: {type(exc).__name__}: {exc}"
        return state.error, state.storage_state

    def _log_in(self, func: Callable, browser: Browser) -> dict:
        context = browser.new_context(base_url=self._base_url or None)
        context.set_default_timeout(self._timeout)
        try:
            call_with_fixtures(func, page=context.new_page(), base_url=self._base_url)
            return context.storage_state()
        finally:
            context.close()


def _find_auth(test: TestCase, module: ModuleType, name: str) -> Callable | None:
    """auth_<name> from the test file itself, then from conftest.py files, nearest first."""
    for source in (module, *get_conftests(test)):
        func = getattr(source, AUTH_PREFIX + name, None)
        if callable(func):
            return func
    return None
