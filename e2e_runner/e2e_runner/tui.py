from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Digits,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
    Switch,
)

from .discovery import discover_tests
from .models import TestResult, TestRun, TestStatus
from .reporter import generate_html_report, generate_json_report
from .runner import run_suite
from .storage import Storage

_storage = Storage()

LOGO = """
 ███████╗██████╗ ███████╗
 ██╔════╝╚════██╗██╔════╝
 █████╗   █████╔╝█████╗
 ██╔══╝  ██╔═══╝ ██╔══╝
 ███████╗███████╗███████╗
 ╚══════╝╚══════╝╚══════╝
      T E S T  R U N N E R
""".strip()

STATUS_STYLE = {
    TestStatus.PASSED:  ("PASS",  "green"),
    TestStatus.FAILED:  ("FAIL",  "red"),
    TestStatus.ERROR:   ("ERROR", "yellow"),
    TestStatus.SKIPPED: ("SKIP",  "dim"),
}


class Config:
    def __init__(self) -> None:
        self.tests_path  = "."
        self.base_url    = ""
        self.workers     = 1
        self.timeout     = 30000
        self.retry       = 0
        self.fail_fast   = False
        self.headed      = False
        self.html_report = ""
        self.json_report = ""


# ─────────────────────────────────────────────────────────────
#  Warning modal (Base URL not set)
# ─────────────────────────────────────────────────────────────

class WarningModal(ModalScreen):
    def compose(self) -> ComposeResult:
        yield Container(
            Static("⚠   Base URL не задан", id="modal-title"),
            Static(
                "Вы не указали адрес тестируемого приложения.\n"
                "Тесты, которые используют URL, могут упасть.\n\n"
                "Продолжить запуск?",
                id="modal-body",
            ),
            Horizontal(
                Button("Продолжить", variant="warning", id="modal-ok"),
                Button("Отмена",     variant="default", id="modal-cancel"),
                classes="modal-btns",
            ),
            id="modal-box",
        )

    @on(Button.Pressed, "#modal-ok")
    def ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#modal-cancel")
    def cancel(self) -> None:
        self.dismiss(False)


# ─────────────────────────────────────────────────────────────
#  File browser modal
# ─────────────────────────────────────────────────────────────

class FileBrowserModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss_modal", "Отмена")]

    def __init__(self, start_path: str) -> None:
        super().__init__()
        self._start = Path(start_path).resolve() if Path(start_path).exists() else Path.cwd()
        self._selected: Path | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("📁  Выберите папку с тестами", id="fb-title"),
            Static(str(self._start), id="fb-current"),
            DirectoryTree(str(self._start), id="fb-tree"),
            Horizontal(
                Button("Выбрать", variant="success", id="fb-ok"),
                Button("Отмена",  variant="default", id="fb-cancel"),
                classes="modal-btns",
            ),
            id="fb-box",
        )

    @on(DirectoryTree.DirectorySelected)
    def dir_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected = event.path
        self.query_one("#fb-current", Static).update(str(event.path))

    @on(DirectoryTree.FileSelected)
    def file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._selected = event.path
        self.query_one("#fb-current", Static).update(str(event.path))

    @on(Button.Pressed, "#fb-ok")
    def ok(self) -> None:
        self.dismiss(str(self._selected) if self._selected else None)

    @on(Button.Pressed, "#fb-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────────────────
#  Settings screen
# ─────────────────────────────────────────────────────────────

class SettingsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Назад")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(
            Static("⚙  Настройки запуска", id="settings-title"),
            Static("", id="settings-error"),

            Static("Путь к тестам", classes="field-label"),
            Horizontal(
                Input(value=self.config.tests_path, id="tests_path", placeholder="tests/"),
                Button("📁", id="browse-path", classes="browse-btn"),
                classes="path-row",
            ),
            Static("Папка или файл с тестами (test_*.py)", classes="field-hint"),

            Static("Base URL", classes="field-label"),
            Input(value=self.config.base_url, id="base_url", placeholder="http://localhost:8080"),
            Static("Адрес тестируемого приложения, например http://localhost:8080", classes="field-hint"),

            Horizontal(
                Vertical(
                    Static("Параллельные потоки", classes="field-label"),
                    Input(value=str(self.config.workers), id="workers", placeholder="1"),
                    Static("Сколько тестов запускать одновременно (1 = по очереди)", classes="field-hint"),
                ),
                Vertical(
                    Static("Таймаут (мс)", classes="field-label"),
                    Input(value=str(self.config.timeout), id="timeout", placeholder="30000"),
                    Static("Максимальное время ожидания одного действия в мс (1000 мс = 1 сек)", classes="field-hint"),
                ),
                Vertical(
                    Static("Retry", classes="field-label"),
                    Input(value=str(self.config.retry), id="retry", placeholder="0"),
                    Static("Сколько раз повторить упавший тест перед тем как считать его неудачным", classes="field-hint"),
                ),
                classes="fields-row",
            ),

            Horizontal(
                Container(
                    Static("⚡ Fail-fast", classes="switch-label"),
                    Switch(value=self.config.fail_fast, id="fail_fast"),
                    Static("Остановить все тесты при первом падении", classes="switch-hint"),
                    classes="switch-card",
                ),
                Container(
                    Static("👁  Headed", classes="switch-label"),
                    Switch(value=self.config.headed, id="headed"),
                    Static("Показывать окно браузера во время теста", classes="switch-hint"),
                    classes="switch-card",
                ),
                classes="switches-row",
            ),

            Static("HTML отчёт (необязательно)", classes="field-label"),
            Input(value=self.config.html_report, id="html_report", placeholder="report.html"),
            Static("Путь для сохранения красивого HTML-отчёта, например report.html", classes="field-hint"),

            Static("JSON отчёт (необязательно)", classes="field-label"),
            Input(value=self.config.json_report, id="json_report", placeholder="report.json"),
            Static("Путь для сохранения машиночитаемого JSON-отчёта", classes="field-hint"),

            Horizontal(
                Button("  Сохранить", variant="success", id="save"),
                Button("  Отмена",   id="cancel"),
                classes="form-btns",
            ),
            id="settings-form",
        )
        yield Footer()

    def _show_error(self, msg: str) -> None:
        self.query_one("#settings-error", Static).update(f"[bold red]✗  {msg}[/bold red]")

    def _clear_error(self) -> None:
        self.query_one("#settings-error", Static).update("")

    @on(Button.Pressed, "#browse-path")
    async def browse(self) -> None:
        current = self.query_one("#tests_path", Input).value or "."

        def handle(path: str | None) -> None:
            if path is not None:
                self.query_one("#tests_path", Input).value = path

        await self.app.push_screen(FileBrowserModal(current), handle)

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        def val(id_: str) -> str:
            return self.query_one(f"#{id_}", Input).value.strip()

        self._clear_error()

        base_url = val("base_url")
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            self._show_error("Base URL должен начинаться с http:// или https://")
            return

        try:
            workers = int(val("workers") or "1")
            if workers < 1:
                raise ValueError
        except ValueError:
            self._show_error("Параллельные потоки: введите целое число ≥ 1")
            return

        try:
            timeout = int(val("timeout") or "30000")
            if not (1000 <= timeout <= 300000):
                raise ValueError
        except ValueError:
            self._show_error("Таймаут: введите число от 1000 до 300000 мс")
            return

        try:
            retry = int(val("retry") or "0")
            if retry < 0:
                raise ValueError
        except ValueError:
            self._show_error("Retry: введите целое число ≥ 0")
            return

        self.config.tests_path  = val("tests_path") or "."
        self.config.base_url    = base_url
        self.config.html_report = val("html_report")
        self.config.json_report = val("json_report")
        self.config.workers     = workers
        self.config.timeout     = timeout
        self.config.retry       = retry
        self.config.fail_fast   = self.query_one("#fail_fast", Switch).value
        self.config.headed      = self.query_one("#headed",    Switch).value
        self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────
#  Results screen
# ─────────────────────────────────────────────────────────────

class ResultsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Назад")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config  = config
        self._total  = 0
        self._run: TestRun | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("", id="run-status"),
            ProgressBar(id="progress", show_eta=False),
            Horizontal(
                Container(Digits("0", id="d-passed"),  Static("PASSED",  classes="stat-label"), classes="stat-card stat-pass"),
                Container(Digits("0", id="d-failed"),  Static("FAILED",  classes="stat-label"), classes="stat-card stat-fail"),
                Container(Digits("0", id="d-errored"), Static("ERRORS",  classes="stat-label"), classes="stat-card stat-err"),
                Container(Digits("0", id="d-total"),   Static("TOTAL",   classes="stat-label"), classes="stat-card stat-total"),
                id="stats-row",
            ),
            DataTable(id="results-table"),
            id="results-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#results-table", DataTable)
        t.add_columns("  Тест", "Статус", "Время")
        t.cursor_type = "row"
        self.run_tests()

    @work(thread=True)
    def run_tests(self) -> None:
        path  = Path(self.config.tests_path)
        tests = discover_tests(path)

        if not tests:
            self.app.call_from_thread(self._set_status, "[yellow]Тесты не найдены[/yellow]")
            return

        self._total = len(tests)
        self.app.call_from_thread(self._init_progress, self._total)
        self.app.call_from_thread(
            self._set_status,
            f"[bold]Запуск [cyan]{self._total}[/cyan] тестов...[/bold]",
        )

        def on_result(result: TestResult) -> None:
            self.app.call_from_thread(self._add_row, result)

        self._run = run_suite(
            tests=tests,
            project_name="tui",
            base_url=self.config.base_url,
            headless=not self.config.headed,
            timeout=self.config.timeout,
            workers=self.config.workers,
            retries=self.config.retry,
            fail_fast=self.config.fail_fast,
            on_result=on_result,
        )
        _storage.save_run(self._run)

        if self.config.html_report:
            generate_html_report(self._run, Path(self.config.html_report))
        if self.config.json_report:
            generate_json_report(self._run, Path(self.config.json_report))

        self.app.call_from_thread(self._finish)

    def _set_status(self, text: str) -> None:
        self.query_one("#run-status", Static).update(text)

    def _init_progress(self, total: int) -> None:
        self.query_one("#progress", ProgressBar).update(total=total)

    def _add_row(self, result: TestResult) -> None:
        label, color = STATUS_STYLE[result.status]
        self.query_one("#results-table", DataTable).add_row(
            result.test_case.name,
            f"[{color}]{label}[/{color}]",
            f"{result.duration:.2f}s",
        )
        self.query_one("#progress", ProgressBar).advance(1)
        run = self._run
        if run:
            self.query_one("#d-passed",  Digits).update(str(run.passed))
            self.query_one("#d-failed",  Digits).update(str(run.failed))
            self.query_one("#d-errored", Digits).update(str(run.errored))
            self.query_one("#d-total",   Digits).update(str(run.total))

    def _finish(self) -> None:
        run = self._run
        if not run:
            return
        verdict = "PASSED" if run.failed == 0 and run.errored == 0 else "FAILED"
        color   = "green" if verdict == "PASSED" else "red"
        self._set_status(
            f"[bold {color}] {verdict} [/bold {color}]  "
            f"[dim]{run.duration:.2f}s[/dim]"
        )
        self.query_one("#d-passed",  Digits).update(str(run.passed))
        self.query_one("#d-failed",  Digits).update(str(run.failed))
        self.query_one("#d-errored", Digits).update(str(run.errored))
        self.query_one("#d-total",   Digits).update(str(run.total))


# ─────────────────────────────────────────────────────────────
#  History detail screen
# ─────────────────────────────────────────────────────────────

class HistoryDetailScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Назад")]

    def __init__(self, run_id: int) -> None:
        super().__init__()
        self.run_id = run_id
        self._results: list[TestResult] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("", id="detail-header"),
            Horizontal(
                Container(Digits("0", id="dd-passed"),  Static("PASSED",  classes="stat-label"), classes="stat-card stat-pass"),
                Container(Digits("0", id="dd-failed"),  Static("FAILED",  classes="stat-label"), classes="stat-card stat-fail"),
                Container(Digits("0", id="dd-errored"), Static("ERRORS",  classes="stat-label"), classes="stat-card stat-err"),
                Container(Digits("0", id="dd-total"),   Static("TOTAL",   classes="stat-label"), classes="stat-card stat-total"),
                id="stats-row",
            ),
            DataTable(id="detail-table"),
            Static("[dim]Enter — открыть скриншот упавшего теста[/dim]", id="detail-hint"),
            Horizontal(
                Button("↓  Экспортировать", variant="primary", id="btn-export"),
                classes="detail-btns",
            ),
            id="detail-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        run = _storage.get_run(self.run_id)
        results = _storage.get_run_results(self.run_id)

        if run:
            verdict = "PASSED" if run["failed"] == 0 and run["errored"] == 0 else "FAILED"
            color   = "green" if verdict == "PASSED" else "red"
            self.query_one("#detail-header", Static).update(
                f"[bold {color}] {verdict} [/bold {color}]  "
                f"[dim]Прогон #{run['id']} · {run['started_at'][:19]} · {run['duration']:.1f}s[/dim]"
            )
            self.query_one("#dd-passed",  Digits).update(str(run["passed"]))
            self.query_one("#dd-failed",  Digits).update(str(run["failed"]))
            self.query_one("#dd-errored", Digits).update(str(run["errored"]))
            self.query_one("#dd-total",   Digits).update(str(run["total"]))

        self._results = results

        t = self.query_one("#detail-table", DataTable)
        t.add_columns("  Тест", "Статус", "Время", "Ошибка")
        t.cursor_type = "row"
        for r in results:
            label, color = STATUS_STYLE[r.status]
            error = (r.error_message or "").split("\n")[0][:60]
            t.add_row(
                r.test_case.name,
                f"[{color}]{label}[/{color}]",
                f"{r.duration:.2f}s",
                f"[dim]{error}[/dim]" if error else "",
            )

    @on(DataTable.RowSelected, "#detail-table")
    def open_screenshot(self, event: DataTable.RowSelected) -> None:
        import subprocess, sys
        idx = event.cursor_row
        if idx >= len(self._results):
            return
        result = self._results[idx]
        if not result.screenshot_path:
            self.app.notify("Скриншот недоступен для этого теста", severity="warning")
            return
        path = Path(result.screenshot_path)
        if not path.exists():
            self.app.notify(f"Файл не найден: {path}", severity="error")
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        else:
            import os
            os.startfile(str(path))
        self.app.notify(f"Открываю: {path.name}")

    @on(Button.Pressed, "#btn-export")
    def btn_export(self) -> None:
        self._do_export()

    @work(thread=True)
    def _do_export(self) -> None:
        from datetime import datetime
        run_data = _storage.get_run(self.run_id)
        results  = _storage.get_run_results(self.run_id)
        if not run_data:
            self.app.call_from_thread(self.app.notify, "Прогон не найден", severity="error")
            return
        test_run = TestRun(
            id=self.run_id,
            project_name=run_data["project_name"],
            started_at=datetime.fromisoformat(run_data["started_at"]),
            finished_at=datetime.fromisoformat(run_data["finished_at"]) if run_data["finished_at"] else None,
            results=results,
        )
        html_path = Path(f"report_{self.run_id}.html")
        json_path = Path(f"report_{self.run_id}.json")
        generate_html_report(test_run, html_path)
        generate_json_report(test_run, json_path)
        self.app.call_from_thread(
            self.app.notify,
            f"Сохранено: {html_path.resolve()}",
            severity="information",
            timeout=6,
        )


# ─────────────────────────────────────────────────────────────
#  History screen
# ─────────────────────────────────────────────────────────────

class ConfirmModal(ModalScreen):
    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static("⚠  Подтверждение", id="modal-title"),
            Static(self._message, id="modal-body"),
            Horizontal(
                Button("Удалить", variant="error",   id="modal-ok"),
                Button("Отмена",  variant="default", id="modal-cancel"),
                classes="modal-btns",
            ),
            id="modal-box",
        )

    @on(Button.Pressed, "#modal-ok")
    def ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#modal-cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class HistoryScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Назад")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("  История запусков  [dim](Enter — открыть детали)[/dim]", id="history-title"),
            DataTable(id="history-table"),
            Horizontal(
                Button("🗑  Очистить историю", variant="error", id="btn-clear-history"),
                classes="detail-btns",
            ),
            id="history-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._reload_table()

    def _reload_table(self) -> None:
        t = self.query_one("#history-table", DataTable)
        t.clear(columns=True)
        t.add_columns("ID", "Проект", "Дата", "Всего", "✓ Прошло", "✗ Упало", "Время")
        t.cursor_type = "row"
        for r in _storage.list_runs(limit=30):
            ok    = r["failed"] == 0 and r["errored"] == 0
            color = "green" if ok else "red"
            t.add_row(
                str(r["id"]),
                r["project_name"],
                r["started_at"][:19],
                str(r["total"]),
                f"[green]{r['passed']}[/green]",
                f"[{color}]{r['failed']}[/{color}]",
                f"{r['duration']:.1f}s",
                key=str(r["id"]),
            )

    @on(DataTable.RowSelected, "#history-table")
    def open_detail(self, event: DataTable.RowSelected) -> None:
        run_id = int(event.row_key.value)
        self.app.push_screen(HistoryDetailScreen(run_id))

    @on(Button.Pressed, "#btn-clear-history")
    def btn_clear(self) -> None:
        runs = _storage.list_runs(limit=10000)
        if not runs:
            self.app.notify("История уже пуста", severity="warning")
            return

        def handle(confirmed: bool | None) -> None:
            if confirmed:
                deleted = _storage.delete_runs()
                self._reload_table()
                self.app.notify(f"Удалено прогонов: {deleted}", severity="information")

        self.app.push_screen(
            ConfirmModal(f"Удалить все {len(runs)} прогонов из истории?"),
            handle,
        )


# ─────────────────────────────────────────────────────────────
#  Main screen
# ─────────────────────────────────────────────────────────────

class MainScreen(Screen):
    BINDINGS = [Binding("q", "quit", "Выйти")]

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(LOGO, id="logo"),
            Horizontal(
                Vertical(
                    Static(self._summary(), id="config-summary"),
                    id="summary-card",
                ),
                Vertical(
                    Button("▶   Запустить тесты", variant="success", id="btn-run"),
                    Button("⚙   Настройки",        variant="primary",  id="btn-settings"),
                    Button("    История",           variant="default",  id="btn-history"),
                    Button("✕   Выйти",             variant="error",    id="btn-quit"),
                    id="menu",
                ),
                id="main-body",
            ),
            id="main-wrap",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#summary-card").border_title = " Конфигурация "
        self.query_one("#menu").border_title = " Действия "

    def _summary(self) -> str:
        c = self.config
        flags = []
        if c.fail_fast: flags.append("[yellow]⚡ fail-fast[/yellow]")
        if c.headed:    flags.append("[cyan]👁  headed[/cyan]")
        lines = [
            f"[dim]Тесты   [/dim] {c.tests_path}",
            f"[dim]URL     [/dim] {c.base_url or '[red]не задан[/red]'}",
            f"[dim]Потоки  [/dim] {c.workers}   [dim]Retry[/dim]  {c.retry}",
            f"[dim]Таймаут [/dim] {c.timeout} мс",
        ] + flags
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#config-summary", Static).update(self._summary())

    @on(Button.Pressed, "#btn-run")
    def btn_run(self) -> None:
        if not self.config.base_url:
            def handle(confirmed: bool | None) -> None:
                if confirmed:
                    self.app.push_screen(ResultsScreen(self.config))
            self.app.push_screen(WarningModal(), handle)
        else:
            self.app.push_screen(ResultsScreen(self.config))

    @on(Button.Pressed, "#btn-settings")
    async def btn_settings(self) -> None:
        await self.app.push_screen(SettingsScreen(self.config))
        self._refresh()

    @on(Button.Pressed, "#btn-history")
    def btn_history(self) -> None:
        self.app.push_screen(HistoryScreen())

    @on(Button.Pressed, "#btn-quit")
    def btn_quit(self) -> None:
        self.app.exit()


# ─────────────────────────────────────────────────────────────
#  App
# ─────────────────────────────────────────────────────────────

class E2EApp(App):
    CSS = """
    /* ── Global ── */
    Screen { background: $background; }

    /* ── Main ── */
    #main-wrap {
        align: center middle;
        height: 100%;
    }

    #logo {
        text-align: center;
        color: lime;
        text-style: bold;
        margin-bottom: 1;
    }

    #main-body {
        width: auto;
        height: auto;
        align: center top;
    }

    #summary-card {
        border: round $primary;
        padding: 1 2;
        width: 42;
        height: auto;
        margin-right: 3;
        background: $surface;
    }

    #config-summary { color: $text; }

    #menu {
        border: round $primary-darken-1;
        padding: 1 1;
        width: 28;
        height: auto;
        background: $surface;
        align: center top;
    }

    #menu Button {
        width: 100%;
        margin-bottom: 1;
    }

    /* ── Settings ── */
    #settings-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        padding: 1 0;
        margin-bottom: 1;
    }

    #settings-error {
        text-align: center;
        min-height: 1;
        margin-bottom: 1;
    }

    #settings-form {
        padding: 1 4;
        align: center top;
    }

    .field-label {
        color: $text-muted;
        margin-top: 1;
    }

    .field-hint {
        color: $text-disabled;
        text-style: italic;
        margin-bottom: 0;
        padding-left: 1;
    }

    .fields-row {
        height: auto;
        margin-top: 0;
    }

    .fields-row Vertical {
        width: 1fr;
        margin-right: 1;
    }

    .switches-row {
        height: auto;
        margin-top: 1;
    }

    .switch-card {
        border: round $primary-darken-2;
        padding: 0 2;
        height: 7;
        width: 1fr;
        margin-right: 1;
        align: center middle;
        background: $surface;
    }

    .switch-label {
        text-align: center;
        margin-bottom: 1;
    }

    .switch-hint {
        color: $text-disabled;
        text-style: italic;
        text-align: center;
        margin-top: 1;
    }

    .form-btns {
        margin-top: 2;
        height: 3;
    }

    .form-btns Button { margin-right: 1; }

    /* ── Results / Detail ── */
    #results-container, #detail-container {
        padding: 1 2;
        height: 100%;
    }

    #run-status, #detail-header {
        text-style: bold;
        text-align: center;
        padding: 0 2;
        height: 3;
        content-align: center middle;
        border: round $primary-darken-2;
        margin-bottom: 1;
    }

    #progress { margin-bottom: 1; }

    #stats-row {
        height: 7;
        margin-bottom: 1;
    }

    .stat-card {
        border: round $primary-darken-2;
        align: center middle;
        width: 1fr;
        margin-right: 1;
        background: $surface;
    }

    .stat-label {
        text-align: center;
        color: $text-muted;
        text-style: bold;
    }

    .stat-pass Digits { color: $success; }
    .stat-fail Digits { color: $error; }
    .stat-err  Digits { color: $warning; }
    .stat-total Digits { color: $accent; }

    /* ── Detail hint & export button ── */
    #detail-hint {
        color: $text-disabled;
        padding: 0 0;
        height: 1;
    }

    .detail-btns {
        height: 3;
        margin-top: 1;
        align: left middle;
    }

    /* ── History ── */
    #history-title {
        text-style: bold;
        color: $accent;
        padding: 1 2;
    }

    #history-container {
        padding: 1 2;
        height: 100%;
    }

    /* ── Warning modal ── */
    WarningModal {
        align: center middle;
    }

    #modal-box {
        border: round $warning;
        background: $surface;
        padding: 2 4;
        width: 50;
        height: auto;
    }

    #modal-title {
        text-style: bold;
        color: $warning;
        text-align: center;
        margin-bottom: 1;
    }

    #modal-body {
        text-align: center;
        margin-bottom: 2;
    }

    .modal-btns {
        align: center middle;
        height: 3;
    }

    .modal-btns Button { margin-right: 1; }

    /* ── File browser modal ── */
    FileBrowserModal {
        align: center middle;
    }

    #fb-box {
        border: round $primary;
        background: $surface;
        padding: 1 2;
        width: 70;
        height: 30;
    }

    #fb-title {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }

    #fb-current {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
        padding: 0 1;
        height: 1;
        overflow: hidden;
    }

    #fb-tree {
        height: 1fr;
        border: round $primary-darken-2;
        margin-bottom: 1;
    }

    /* ── Path row with browse button ── */
    .path-row {
        height: auto;
    }

    .path-row Input {
        width: 1fr;
    }

    .browse-btn {
        width: 5;
        min-width: 5;
        margin-left: 1;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


def launch() -> None:
    E2EApp().run()
