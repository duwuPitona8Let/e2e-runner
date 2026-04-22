# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Бакалаврский диплом. Тема: система автоматизации E2E тестирования веб-приложений.

Two components:
- **`e2e_runner/`** — the CLI tool itself (installable Python package)
- **`demo_app/`** — Flask web app used to demonstrate the runner

## Setup & run

```bash
# Install e2e_runner (run once, from e2e_runner/)
cd e2e_runner && pip install -e .
playwright install chromium

# Start demo app (port 8080)
cd demo_app && python3 app.py

# Run demo tests (demo_app must be running)
e2e run demo_app/tests -u http://localhost:8080

# TUI interface
e2e ui
```

## e2e_runner architecture

Entry point: `e2e_runner/cli.py` (Click groups). Five independent modules composed only in `cli.py`:

| Module | Role |
|---|---|
| `discovery.py` | Finds `test_*.py` files, imports them, collects `test_*` functions → `list[TestCase]` |
| `runner.py` | Playwright browser execution, screenshot on failure, retry logic → `TestRun` |
| `reporter.py` | Rich live output during run; `generate_html_report()` / `generate_json_report()` |
| `storage.py` | SQLite persistence at `~/.e2e_runner/storage.db` (tables: `projects`, `runs`, `test_results`) |
| `tui.py` | Textual TUI — screens: `MainScreen`, `SettingsScreen`, `ResultsScreen`, `HistoryScreen`, `HistoryDetailScreen` |

**Test format**: plain `test_*.py` files with `test_*` functions. Functions optionally accept `page: Page` and/or `base_url: str` — injected via `inspect.signature`. No imports from this package required.

**Parallel execution**: `workers=1` → sequential single context; `workers>1` → `ThreadPoolExecutor`, one `sync_playwright` context per thread, fresh `BrowserContext` per test.

**Exit codes**: 0 if all passed; 1 if any `failed > 0` or `errored > 0`. `AssertionError` → `FAILED`; any other exception → `ERROR`.

## demo_app

Flask app, port 8080. Credentials: `admin/password123`, `user/qwerty`.

`demo_app/tests/test_demo_app.py` has 22 tests: **19 pass, 3 intentionally fail** (to demonstrate retry and fail-fast features):
- `test_nonexistent_item` — checks for text that doesn't exist
- `test_wrong_title` — asserts Amazon in title
- `test_login_as_unknown_user` — asserts redirect that never happens
