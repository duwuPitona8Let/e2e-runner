# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium

# Run all tests in a directory
e2e run examples/tests --project example

# Discover tests without running
e2e discover examples/tests

# Run with filter, parallel workers, HTML report
e2e run examples/tests -k login -n 4 --html report.html

# Export reports
e2e run examples/tests --html report.html --json report.json
e2e report <run_id> --html report.html --json report.json

# Project management
e2e projects add myapp https://myapp.com -d "description"
e2e projects list
e2e projects edit myapp -u https://new-url.com -d "new description"
e2e projects remove myapp
e2e projects stats myapp

# History and reports
e2e history -p myapp
e2e report <run_id> --html report.html
```

## Architecture

The CLI entry point is `e2e_runner/cli.py` — Click groups wired to `e2e_runner/models.py`, `storage.py`, `discovery.py`, `runner.py`, and `reporter.py`. All five modules are independent; `cli.py` is the only place that composes them.

**Data flow for `e2e run`:**
1. `discovery.py` — recursively finds `test_*.py` files, dynamically imports them, collects `test_*` functions → `list[TestCase]`
2. `runner.py` — opens a Playwright browser, calls each function with `(page, base_url)` kwargs based on `inspect.signature`, captures screenshots on failure → `TestRun`
3. `reporter.py` — Rich live progress + per-result lines during the run; summary table + Panel at the end; `generate_html_report()` for HTML output
4. `storage.py` — persists the finished `TestRun` to SQLite at `~/.e2e_runner/storage.db`

**Storage schema** (`storage.py`): three tables — `projects`, `runs`, `test_results`. Foreign key `test_results.run_id → runs.id` with `ON DELETE CASCADE`. DB path defaults to `~/.e2e_runner/storage.db` but is injectable via `Storage(db_path=...)`.

**Test format** — users write plain Python files named `test_*.py` with functions named `test_*`. Functions may optionally accept `page: Page` and/or `base_url: str`; the runner injects these via signature inspection. No decorators or imports from this package are required.

**Input validation** (`cli.py`) — `_validate_url` requires `http://` or `https://` scheme; `_validate_name` rejects empty or >64-char project names; `_validate_timeout` enforces 1000–300000 ms range. Called in `run`, `projects add`, and `projects edit` before any storage access.

**JSON export** (`reporter.py`) — `generate_json_report()` writes a single JSON object with run metadata and a `results` array. Available via `--json PATH` in both `run` and `report` commands.

**Test status distinction** — `AssertionError` → `FAILED`; any other exception → `ERROR`. Exit code is 1 if `failed > 0` or `errored > 0`, otherwise 0. Failure screenshots are saved to `~/.e2e_runner/screenshots/`.

**Parallel execution** (`runner.py`) — `workers=1` uses a single `sync_playwright` context sequentially; `workers>1` spawns one `sync_playwright` context per thread via `ThreadPoolExecutor`. Each test always gets a fresh `BrowserContext`.

**Module loading** (`discovery.py`) — test files are loaded with `importlib.util.spec_from_file_location` into a synthetic module name to avoid collisions. `get_callable()` retrieves the function from `sys.modules` for execution.
