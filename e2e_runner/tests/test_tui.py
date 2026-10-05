"""TUI tests in Textual's headless mode (App.run_test). Browser and codegen are faked."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from test_recorder import CODEGEN_LOGIN
from textual.widgets import Button, DataTable, Input, Static

from e2e_runner import recorder, tui
from e2e_runner.config import load_config
from e2e_runner.discovery import discover_tests
from e2e_runner.models import Project
from e2e_runner.models import TestCase as Case
from e2e_runner.models import TestResult as Result
from e2e_runner.models import TestRun as Run
from e2e_runner.models import TestStatus as Status


@pytest.fixture(autouse=True)
def tui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, storage) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tui, "_storage", storage)


class NotifyLog(list):
    def __call__(self, message, *, title="", severity="information", timeout=None, **_):
        self.append((severity, str(message)))


def run_app(scenario):
    """Run ``scenario(app, pilot, notes)`` inside a headless E2EApp."""

    async def _main():
        app = tui.E2EApp()
        notes = NotifyLog()
        app.notify = notes  # capture toasts instead of rendering them
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await scenario(app, pilot, notes)

    asyncio.run(_main())


async def press(pilot, screen, button_id: str) -> None:
    screen.query_one(f"#{button_id}", Button).press()
    await pilot.pause()


# ── 1. e2e.yaml ──────────────────────────────────────────────


def test_main_screen_loads_e2e_yaml(tmp_path) -> None:
    (tmp_path / "e2e.yaml").write_text("project: shop\nworkers: 3\ntrace: true\ntests: suite\n")

    async def scenario(app, pilot, notes):
        main = app.screen
        assert (main.config.project, main.config.workers, main.config.trace) == ("shop", 3, True)
        assert main.config.tests_path == "suite"
        summary = str(main.query_one("#config-summary", Static).render())
        assert "e2e.yaml" in summary
        assert "shop" in summary
        assert notes == []

    run_app(scenario)


def test_bad_e2e_yaml_is_reported_and_defaults_used(tmp_path) -> None:
    (tmp_path / "e2e.yaml").write_text("workers: abc\n")

    async def scenario(app, pilot, notes):
        assert app.screen.config.workers == 1
        assert app.screen.config.source is None
        assert any(sev == "error" and "'workers' must be an integer" in msg for sev, msg in notes)

    run_app(scenario)


def test_settings_save_to_e2e_yaml(tmp_path) -> None:
    async def scenario(app, pilot, notes):
        main = app.screen
        await press(pilot, main, "btn-settings")
        settings = app.screen
        settings.query_one("#project", Input).value = "shop"
        settings.query_one("#base_url", Input).value = "http://shop.local"
        settings.query_one("#workers", Input).value = "4"
        await press(pilot, settings, "save-yaml")

        assert app.screen is main
        saved = load_config(tmp_path / "e2e.yaml")
        assert (saved["project"], saved["base_url"], saved["workers"]) == ("shop", "http://shop.local", 4)
        assert main.config.source == tmp_path / "e2e.yaml"
        assert "shop" in str(main.query_one("#config-summary", Static).render())

    run_app(scenario)


def test_settings_rejects_invalid_values_without_saving(tmp_path) -> None:
    async def scenario(app, pilot, notes):
        await press(pilot, app.screen, "btn-settings")
        settings = app.screen
        settings.query_one("#workers", Input).value = "500"
        await press(pilot, settings, "save-yaml")

        assert app.screen is settings  # stays open
        assert "от 1 до 32" in str(settings.query_one("#settings-error", Static).render())
        assert not (tmp_path / "e2e.yaml").exists()

    run_app(scenario)


# ── 3. project ───────────────────────────────────────────────


def test_run_uses_project_name_and_its_url(fake_playwright, write_test_file, storage, tmp_path) -> None:
    write_test_file("test_a.py", "def test_ok(page): pass\n")
    storage.add_project(Project(name="shop", base_url="http://shop.local"))
    (tmp_path / "e2e.yaml").write_text("project: shop\ntests: suite\n")  # no base_url

    async def scenario(app, pilot, notes):
        await press(pilot, app.screen, "btn-run")  # no warning modal: URL comes from the project
        assert isinstance(app.screen, tui.ResultsScreen)
        await app.workers.wait_for_complete()
        await pilot.pause()

        (run,) = storage.list_runs()
        assert (run["project_name"], run["passed"]) == ("shop", 1)
        assert fake_playwright.contexts[0].base_url == "http://shop.local"

    run_app(scenario)


# ── 2. trace in history ──────────────────────────────────────


def _saved_run(storage, tmp_path) -> int:
    trace, shot = tmp_path / "t.zip", tmp_path / "s.png"
    trace.write_bytes(b"zip")
    shot.write_bytes(b"png")
    case = Case("t::test_x", "t.py", "test_x")
    started = datetime(2026, 1, 1, 12, 0)
    run = Run(
        project_name="p",
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        results=[
            Result(case, Status.FAILED, 1.0, "boom", str(shot), str(trace)),  # trace + screenshot
            Result(case, Status.FAILED, 1.0, "boom", str(shot)),  # screenshot only
            Result(case, Status.PASSED, 1.0),  # nothing
        ],
    )
    return storage.save_run(run).id


def test_history_detail_opens_trace_first(storage, tmp_path, monkeypatch) -> None:
    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(tui, "_open_trace", lambda p: opened.append(("trace", p.name)))
    monkeypatch.setattr(tui, "_open_path", lambda p: opened.append(("file", p.name)))
    run_id = _saved_run(storage, tmp_path)

    async def scenario(app, pilot, notes):
        await app.push_screen(tui.HistoryDetailScreen(run_id))
        await pilot.pause()
        table = app.screen.query_one("#detail-table", DataTable)
        table.focus()

        assert "🧭 📷" in str(table.get_row_at(0)[3])
        await pilot.press("enter")  # row 0: trace wins
        await pilot.press("s")  # explicit screenshot
        table.move_cursor(row=1)
        await pilot.press("enter")  # row 1: no trace -> screenshot
        await pilot.press("t")  # row 1: no trace -> warning
        table.move_cursor(row=2)
        await pilot.press("enter")  # row 2: nothing -> warning

        assert opened == [("trace", "t.zip"), ("file", "s.png"), ("file", "s.png")]
        warnings = [msg for sev, msg in notes if sev == "warning"]
        assert warnings == ["Trace недоступен для этого теста", "Скриншот недоступен для этого теста"]

    run_app(scenario)


# ── 4. record ───────────────────────────────────────────────


def test_record_button_saves_test(tmp_path, monkeypatch) -> None:
    (tmp_path / "e2e.yaml").write_text("base_url: http://localhost:8080\ntests: suite\n")
    calls: list[str] = []
    monkeypatch.setattr(recorder, "_run_codegen", lambda url: calls.append(url) or CODEGEN_LOGIN)

    async def scenario(app, pilot, notes):
        await press(pilot, app.screen, "btn-record")
        modal = app.screen
        assert isinstance(modal, tui.RecordModal)
        assert modal.query_one("#record-url", Input).value == "http://localhost:8080"
        assert modal.query_one("#record-output", Input).value == str(Path("suite") / "test_recorded.py")
        modal.query_one("#record-name", Input).value = "test_login"
        await press(pilot, modal, "record-ok")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == ["http://localhost:8080"]
        assert [t.function_name for t in discover_tests(tmp_path / "suite")] == ["test_login"]
        assert any("Сохранён test_login()" in msg for sev, msg in notes)

    run_app(scenario)


def test_record_failure_is_reported(tmp_path, monkeypatch) -> None:
    def _fail(url):
        raise recorder.RecordError("playwright codegen exited with code 1 without saving a recording")

    monkeypatch.setattr(recorder, "_run_codegen", _fail)

    async def scenario(app, pilot, notes):
        await press(pilot, app.screen, "btn-record")
        app.screen.query_one("#record-url", Input).value = "http://localhost:8080"
        await press(pilot, app.screen, "record-ok")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert any(sev == "error" and "Запись не удалась" in msg for sev, msg in notes)

    run_app(scenario)


@pytest.mark.parametrize(
    ("url", "output", "name", "message"),
    [
        ("ftp://x", "t/test_a.py", "", "http:// или https://"),
        ("http://x", "t/test_a.txt", "", ".py"),
        ("http://x", "t/test_a.py", "login", "test_"),
    ],
)
def test_record_modal_validation(url, output, name, message) -> None:
    async def scenario(app, pilot, notes):
        await press(pilot, app.screen, "btn-record")
        modal = app.screen
        modal.query_one("#record-url", Input).value = url
        modal.query_one("#record-output", Input).value = output
        modal.query_one("#record-name", Input).value = name
        await press(pilot, modal, "record-ok")

        assert app.screen is modal  # not dismissed
        assert message in str(modal.query_one("#record-error", Static).render())

    run_app(scenario)
