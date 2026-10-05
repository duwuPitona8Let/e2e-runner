"""Shared fixtures for e2e_runner unit tests.

Unit tests never start a real browser: ``fake_playwright`` replaces
``runner.sync_playwright`` with in-memory fakes that record what happened.
"""
from __future__ import annotations

import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from e2e_runner import cli, runner
from e2e_runner.storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(db_path=tmp_path / "storage.db")


@pytest.fixture
def write_test_file(tmp_path: Path) -> Callable[[str, str], Path]:
    """Write a test_*.py file with dedented source under tmp_path/suite; returns its path."""

    def _write(name: str, source: str) -> Path:
        path = tmp_path / "suite" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
        return path

    return _write


@pytest.fixture(autouse=True)
def isolated_artifact_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep screenshots/traces out of the real ~/.e2e_runner."""
    monkeypatch.setattr(runner, "SCREENSHOT_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(runner, "TRACE_DIR", tmp_path / "traces")


# ── Fake Playwright ──────────────────────────────────────────


class FakeTracing:
    def __init__(self) -> None:
        self.started = False
        self.saved_to: str | None = None

    def start(self, **_: object) -> None:
        self.started = True

    def stop(self, path: str | None = None) -> None:
        if path:
            Path(path).write_bytes(b"trace")
            self.saved_to = path


class FakePage:
    def screenshot(self, path: str) -> None:
        Path(path).write_bytes(b"png")


# What FakeContext.storage_state() returns: stands in for the cookies an auth_* function sets.
FAKE_STORAGE_STATE = {"cookies": [{"name": "session", "value": "logged-in"}], "origins": []}


class FakeContext:
    def __init__(self, base_url: str | None, storage_state: dict | None = None) -> None:
        self.base_url = base_url
        self.storage_state_in = storage_state
        self.timeout: int | None = None
        self.tracing = FakeTracing()
        self.closed = False

    def set_default_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def new_page(self) -> FakePage:
        return FakePage()

    def storage_state(self) -> dict:
        return FAKE_STORAGE_STATE

    def close(self) -> None:
        self.closed = True


@dataclass
class PlaywrightLog:
    """What the fake Playwright was asked to do during a test."""

    launch_error: Exception | None = None
    browsers_launched: int = 0
    browsers_closed: int = 0
    contexts: list[FakeContext] = field(default_factory=list)


class FakeBrowser:
    def __init__(self, log: PlaywrightLog) -> None:
        self.log = log

    def new_context(self, base_url: str | None = None, storage_state: dict | None = None) -> FakeContext:
        ctx = FakeContext(base_url, storage_state)
        self.log.contexts.append(ctx)
        return ctx

    def close(self) -> None:
        self.log.browsers_closed += 1


class _FakeChromium:
    def __init__(self, log: PlaywrightLog) -> None:
        self.log = log

    def launch(self, headless: bool = True) -> FakeBrowser:
        if self.log.launch_error:
            raise self.log.launch_error
        self.log.browsers_launched += 1
        return FakeBrowser(self.log)


class _FakeSyncPlaywright:
    def __init__(self, log: PlaywrightLog) -> None:
        self.chromium = _FakeChromium(log)

    def __enter__(self) -> _FakeSyncPlaywright:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def fake_playwright(monkeypatch: pytest.MonkeyPatch) -> PlaywrightLog:
    log = PlaywrightLog()
    monkeypatch.setattr(runner, "sync_playwright", lambda: _FakeSyncPlaywright(log))
    return log


@pytest.fixture
def cli_storage(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> Storage:
    """Point the CLI's lazily created Storage at a temporary database."""
    monkeypatch.setattr(cli, "_storage", storage)
    return storage
