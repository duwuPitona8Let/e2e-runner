from pathlib import Path
from urllib.parse import urlparse

import click
from rich.table import Table
from rich.text import Text

from .config import (
    CONFIG_FILENAME,
    CONFIG_TEMPLATE,
    ConfigError,
    find_config,
    load_config,
)
from .discovery import DiscoveryError, discover_tests
from .models import Project, TestResult, TestRun
from .recorder import RecordError
from .recorder import record as record_session
from .reporter import (
    console,
    generate_html_report,
    generate_json_report,
    make_progress,
    print_result_line,
    print_summary,
)
from .runner import run_suite
from .storage import Storage

_storage: Storage | None = None


def _get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage


def _validate_url(url: str, param_name: str = "URL") -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        console.print(f"[red]Invalid {param_name}: '{url}'. Must start with http:// or https://[/red]")
        raise SystemExit(1)


def _validate_name(name: str) -> None:
    if not name.strip():
        console.print("[red]Project name cannot be empty.[/red]")
        raise SystemExit(1)
    if len(name) > 64:
        console.print("[red]Project name is too long (max 64 characters).[/red]")
        raise SystemExit(1)


def _validate_timeout(timeout: int) -> None:
    if timeout < 1000 or timeout > 300000:
        console.print("[red]Timeout must be between 1000 and 300000 ms.[/red]")
        raise SystemExit(1)


def _validate_retry(retry: int) -> None:
    if retry < 0 or retry > 10:
        console.print("[red]Retry count must be between 0 and 10.[/red]")
        raise SystemExit(1)


MAX_WORKERS = 32


def _validate_workers(workers: int) -> None:
    if workers < 1 or workers > MAX_WORKERS:
        console.print(f"[red]Workers must be between 1 and {MAX_WORKERS}.[/red]")
        raise SystemExit(1)


def _print_discovery_errors(errors: list[DiscoveryError]) -> None:
    for err in errors:
        console.print(f"[red]Import error:[/red] {err}")


@click.group(epilog=(
    "Examples:\n\n\b\n"
    "  e2e init                              # create e2e.yaml config\n"
    "  e2e run                               # run using e2e.yaml\n"
    "  e2e run tests/ -u http://localhost:8080\n"
    "  e2e run tests/ -u URL -n 4 --retry 2 --fail-fast --html report.html\n"
    "  e2e record http://localhost:8080 -o tests/test_login.py\n"
    "  e2e export RUN_ID [--format html|json|all] [--open]\n"
    "  e2e clean [--keep N] [-p PROJECT] [-y]\n"
    "  e2e history [-p PROJECT] [-n LIMIT]\n"
    "  e2e report RUN_ID [--html PATH] [--json PATH]\n"
    "  e2e projects add NAME URL [-d DESCRIPTION]\n"
))
@click.version_option("1.0.0", prog_name="e2e")
def main() -> None:
    """E2E test runner for web applications."""


# ──────────────────────────────────────────────
#  run
# ──────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("-p", "--project", default=None, help="Project name")
@click.option("-u", "--base-url", default=None, help="Base URL injected into tests")
@click.option("-k", "--filter", "filter_pattern", default="", help="Filter tests by name substring")
@click.option("--headed/--no-headed", default=None, help="Run browser in headed (visible) mode")
@click.option("-n", "--workers", default=None, type=int, help="Parallel workers")
@click.option("--timeout", default=None, type=int, help="Browser action timeout (ms)")
@click.option("--html", "html_report", type=click.Path(path_type=Path), default=None, help="Save HTML report to file")
@click.option("--json", "json_report", type=click.Path(path_type=Path), default=None, help="Save JSON report to file")
@click.option("--retry", default=None, type=int, help="Retry failed tests N times")
@click.option("--fail-fast/--no-fail-fast", default=None, help="Stop on first failure")
@click.option("--trace/--no-trace", default=None, help="Save Playwright trace (.zip) for failed tests")
@click.option("--save/--no-save", default=True, show_default=True, help="Save run to history")
def run(
    path: Path | None,
    project: str | None,
    base_url: str | None,
    filter_pattern: str,
    headed: bool | None,
    workers: int | None,
    timeout: int | None,
    html_report: Path | None,
    json_report: Path | None,
    retry: int | None,
    fail_fast: bool | None,
    trace: bool | None,
    save: bool,
) -> None:
    """Discover and run E2E tests in PATH."""
    cfg: dict = {}
    cfg_path = find_config()
    if cfg_path:
        try:
            cfg = load_config(cfg_path)
        except ConfigError as exc:
            console.print(f"[red]Config error:[/red] {exc}")
            raise SystemExit(1) from None
        console.print(f"[dim]Config: {cfg_path}[/dim]")

    effective_project  = project   or cfg.get("project",   "default")
    effective_base_url = base_url  or cfg.get("base_url",  "")
    effective_workers  = workers   if workers  is not None else cfg.get("workers",  1)
    effective_timeout  = timeout   if timeout  is not None else cfg.get("timeout",  30000)
    effective_retry    = retry     if retry    is not None else cfg.get("retry",    0)
    effective_headed   = headed    if headed   is not None else cfg.get("headed",   False)
    effective_failfast = fail_fast if fail_fast is not None else cfg.get("fail_fast", False)
    effective_trace    = trace     if trace    is not None else cfg.get("trace",    False)
    effective_html     = html_report or (Path(cfg["html_report"]) if cfg.get("html_report") else None)
    effective_json     = json_report or (Path(cfg["json_report"]) if cfg.get("json_report") else None)
    effective_path     = path or Path(cfg.get("tests", "."))

    _validate_timeout(effective_timeout)
    _validate_retry(effective_retry)
    _validate_workers(effective_workers)
    if effective_base_url:
        _validate_url(effective_base_url, "base-url")
    project_obj = _get_storage().get_project(effective_project)
    effective_url = effective_base_url or (project_obj.base_url if project_obj else "")

    import_errors: list[DiscoveryError] = []
    tests = discover_tests(effective_path, filter_pattern, errors=import_errors)
    _print_discovery_errors(import_errors)
    if not tests:
        # An empty suite is a failure: in CI a broken or mistyped path must not look green.
        console.print("[yellow]No tests found.[/yellow]")
        raise SystemExit(1)

    console.print(f"\n[bold]Found {len(tests)} test(s)[/bold] in [cyan]{effective_path}[/cyan]\n")

    progress = make_progress(len(tests))
    task_id = progress.add_task("Running…", total=len(tests))

    def on_result(result: TestResult) -> None:
        print_result_line(result)
        progress.advance(task_id)

    with progress:
        test_run = run_suite(
            tests=tests,
            project_name=effective_project,
            base_url=effective_url,
            headless=not effective_headed,
            timeout=effective_timeout,
            workers=effective_workers,
            retries=effective_retry,
            fail_fast=effective_failfast,
            trace=effective_trace,
            on_result=on_result,
        )

    print_summary(test_run)
    if import_errors:
        console.print(f"[red]{len(import_errors)} test file(s) could not be imported — see errors above.[/red]")

    if save:
        _get_storage().save_run(test_run)
        console.print(f"[dim]Run saved (id={test_run.id})[/dim]")

    if effective_html:
        generate_html_report(test_run, effective_html)
        console.print(f"[dim]HTML report → {effective_html}[/dim]")

    if effective_json:
        generate_json_report(test_run, effective_json)
        console.print(f"[dim]JSON report → {effective_json}[/dim]")

    ok = test_run.failed == 0 and test_run.errored == 0 and not import_errors
    raise SystemExit(0 if ok else 1)


# ──────────────────────────────────────────────
#  init
# ──────────────────────────────────────────────

@main.command()
@click.option("-f", "--force", is_flag=True, help="Overwrite existing e2e.yaml")
def init(force: bool) -> None:
    """Create e2e.yaml config file in the current directory."""
    dest = Path.cwd() / CONFIG_FILENAME
    if dest.exists() and not force:
        console.print(f"[yellow]{CONFIG_FILENAME} already exists.[/yellow] Use --force to overwrite.")
        raise SystemExit(1)
    dest.write_text(CONFIG_TEMPLATE)
    console.print(f"[green]Created:[/green] {dest}")
    console.print("[dim]Edit the file, then run [bold]e2e run[/bold] — flags in e2e.yaml are picked up automatically.[/dim]")


# ──────────────────────────────────────────────
#  record
# ──────────────────────────────────────────────

@main.command()
@click.argument("url", required=False)
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Test file to create or append to (default: <tests>/test_recorded.py)")
@click.option("-n", "--name", default=None, help="Test function name (default: from file name)")
@click.option("-p", "--project", default=None, help="Take URL from this project if URL is omitted")
def record(url: str | None, output: Path | None, name: str | None, project: str | None) -> None:
    """Record a test by clicking through URL in a browser (playwright codegen).

    Close the browser window to finish; the recorded steps are saved as a
    test_* function. URLs are made relative, so run it with `e2e run -u URL`.
    """
    cfg: dict = {}
    cfg_path = find_config()
    if cfg_path:
        try:
            cfg = load_config(cfg_path)
        except ConfigError as exc:
            console.print(f"[red]Config error:[/red] {exc}")
            raise SystemExit(1) from None

    if not url and project:
        project_obj = _get_storage().get_project(project)
        url = project_obj.base_url if project_obj else None
    url = url or cfg.get("base_url") or None
    if not url:
        console.print("[red]No URL: pass it as an argument, set base_url in e2e.yaml, or use -p PROJECT.[/red]")
        raise SystemExit(1)
    _validate_url(url)

    if output is None:
        tests_dir = Path(cfg.get("tests", "tests"))
        output = (tests_dir if tests_dir.suffix != ".py" else tests_dir.parent) / "test_recorded.py"

    console.print(f"[bold]Recording[/bold] {url} → [cyan]{output}[/cyan]")
    console.print("[dim]Click through the scenario in the browser, then close the browser window to save.[/dim]")
    try:
        test_name, path = record_session(url, output, name)
    except RecordError as exc:
        console.print(f"[red]Recording failed:[/red] {exc}")
        raise SystemExit(1) from None

    console.print(f"[green]Saved[/green] {test_name}() → {path}")
    console.print(f"[dim]Run it: e2e run {path} -u {url} -k {test_name}[/dim]")


# ──────────────────────────────────────────────
#  discover
# ──────────────────────────────────────────────

@main.command()
def ui() -> None:
    """Launch interactive TUI."""
    from .tui import launch
    launch()


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("-k", "--filter", "filter_pattern", default="", help="Filter by name substring")
def discover(path: Path, filter_pattern: str) -> None:
    """List all tests found in PATH without running them."""
    import_errors: list[DiscoveryError] = []
    tests = discover_tests(path, filter_pattern, errors=import_errors)
    _print_discovery_errors(import_errors)
    if not tests:
        console.print("[yellow]No tests found.[/yellow]")
        raise SystemExit(1 if import_errors else 0)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", justify="right")
    table.add_column("Test name")
    table.add_column("File", style="dim")

    for i, t in enumerate(tests, 1):
        table.add_row(str(i), t.function_name, t.file_path)

    console.print(f"\n[bold]{len(tests)} test(s) found[/bold]\n")
    console.print(table)


# ──────────────────────────────────────────────
#  projects
# ──────────────────────────────────────────────

@main.group()
def projects() -> None:
    """Manage web projects."""


@projects.command("add")
@click.argument("name")
@click.argument("base_url")
@click.option("-d", "--description", default="", help="Short project description")
def projects_add(name: str, base_url: str, description: str) -> None:
    """Register a new project."""
    _validate_name(name)
    _validate_url(base_url)
    if _get_storage().get_project(name):
        console.print(f"[red]Project '{name}' already exists.[/red]")
        raise SystemExit(1)
    project = _get_storage().add_project(Project(name=name, base_url=base_url, description=description))
    console.print(f"[green]Project added:[/green] {project.name} → {project.base_url}")


@projects.command("list")
def projects_list() -> None:
    """Show all registered projects."""
    items = _get_storage().list_projects()
    if not items:
        console.print("[dim]No projects registered. Use: e2e projects add NAME URL[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Name", style="cyan")
    table.add_column("Base URL")
    table.add_column("Description", style="dim")
    table.add_column("Created", style="dim")

    for p in items:
        created = p.created_at.strftime("%Y-%m-%d") if p.created_at else "—"
        table.add_row(p.name, p.base_url, p.description or "—", created)

    console.print(table)


@projects.command("remove")
@click.argument("name")
def projects_remove(name: str) -> None:
    """Delete a project by name."""
    if not _get_storage().remove_project(name):
        console.print(f"[red]Project '{name}' not found.[/red]")
        raise SystemExit(1)
    console.print(f"[green]Removed:[/green] {name}")


@projects.command("edit")
@click.argument("name")
@click.option("-u", "--base-url", default=None)
@click.option("-d", "--description", default=None)
def projects_edit(name: str, base_url: str | None, description: str | None) -> None:
    """Update project URL or description."""
    if base_url:
        _validate_url(base_url)
    if not _get_storage().update_project(name, base_url, description):
        console.print(f"[red]Project '{name}' not found or nothing to update.[/red]")
        raise SystemExit(1)
    console.print(f"[green]Updated:[/green] {name}")


@projects.command("stats")
@click.argument("name")
def projects_stats(name: str) -> None:
    """Show run statistics for a project."""
    stats = _get_storage().project_stats(name)
    if not stats or stats.get("total_runs") == 0:
        console.print(f"[dim]No runs recorded for project '{name}'.[/dim]")
        return

    console.print(f"\n[bold cyan]{name}[/bold cyan] statistics\n")
    console.print(f"  Total runs:    {stats['total_runs']}")
    console.print(f"  Total passed:  {stats['total_passed'] or 0}")
    console.print(f"  Total failed:  {stats['total_failed'] or 0}")
    avg = stats["avg_duration"] or 0
    console.print(f"  Avg duration:  {avg:.2f}s\n")


# ──────────────────────────────────────────────
#  history
# ──────────────────────────────────────────────

@main.command()
@click.option("-p", "--project", default=None, help="Filter by project name")
@click.option("-n", "--limit", default=20, show_default=True)
def history(project: str | None, limit: int) -> None:
    """Show recent test runs."""
    runs = _get_storage().list_runs(project_name=project, limit=limit)
    if not runs:
        console.print("[dim]No runs in history.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID",  style="dim", justify="right")
    table.add_column("Project", style="cyan")
    table.add_column("Date")
    table.add_column("Total", justify="right")
    table.add_column("Passed", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Duration", justify="right", style="dim")

    for r in runs:
        verdict_style = "green" if r["failed"] == 0 and r["errored"] == 0 else "red"
        table.add_row(
            str(r["id"]),
            r["project_name"],
            r["started_at"][:19],
            str(r["total"]),
            Text(str(r["passed"]), style="green"),
            Text(str(r["failed"]), style=verdict_style),
            f"{r['duration']:.1f}s",
        )

    console.print(table)


# ──────────────────────────────────────────────
#  report
# ──────────────────────────────────────────────

@main.command()
@click.argument("run_id", type=int)
@click.option("--html", "html_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "json_path", type=click.Path(path_type=Path), default=None)
def report(run_id: int, html_path: Path | None, json_path: Path | None) -> None:
    """Show or export details for a specific run."""
    run_data = _get_storage().get_run(run_id)
    if not run_data:
        console.print(f"[red]Run #{run_id} not found.[/red]")
        raise SystemExit(1)

    results = _get_storage().get_run_results(run_id)

    from datetime import datetime
    test_run = TestRun(
        id=run_id,
        project_name=run_data["project_name"],
        started_at=datetime.fromisoformat(run_data["started_at"]),
        finished_at=datetime.fromisoformat(run_data["finished_at"]) if run_data["finished_at"] else None,
        results=results,
    )

    print_summary(test_run)

    if html_path:
        generate_html_report(test_run, html_path)
        console.print(f"[dim]HTML report → {html_path}[/dim]")

    if json_path:
        generate_json_report(test_run, json_path)
        console.print(f"[dim]JSON report → {json_path}[/dim]")


# ──────────────────────────────────────────────
#  clean
# ──────────────────────────────────────────────

@main.command()
@click.option("-p", "--project", default=None, help="Delete only runs for this project")
@click.option("--keep", default=0, show_default=True, help="Keep the last N runs (0 = delete all)")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
def clean(project: str | None, keep: int, yes: bool) -> None:
    """Delete run history from the database.

    By default removes all runs. Use --keep N to retain the most recent N runs.
    """
    runs = _get_storage().list_runs(project_name=project, limit=10000)
    target = len(runs) - keep if keep > 0 else len(runs)
    if target <= 0:
        console.print("[dim]Нечего удалять.[/dim]")
        return

    scope = f"проекта '{project}'" if project else "всей истории"
    msg = (
        f"Будет удалено [bold]{target}[/bold] прогон(ов) из {scope}"
        + (f" (оставить последние {keep})" if keep else "")
        + "."
    )
    console.print(msg)

    if not yes and not click.confirm("Продолжить?", default=False):
        console.print("[dim]Отменено.[/dim]")
        return

    deleted = _get_storage().delete_runs(project_name=project, keep_last=keep)
    console.print(f"[green]Удалено прогонов:[/green] {deleted}")


# ──────────────────────────────────────────────
#  export
# ──────────────────────────────────────────────

@main.command()
@click.argument("run_id", type=int)
@click.option(
    "--format", "fmt",
    type=click.Choice(["html", "json", "all"]),
    default="all", show_default=True,
    help="Which format(s) to export",
)
@click.option("--html", "html_path", type=click.Path(path_type=Path), default=None, help="HTML output path (default: report_<id>.html)")
@click.option("--json", "json_path", type=click.Path(path_type=Path), default=None, help="JSON output path (default: report_<id>.json)")
@click.option("--open", "open_browser", is_flag=True, help="Open HTML report in browser after export")
def export(run_id: int, fmt: str, html_path: Path | None, json_path: Path | None, open_browser: bool) -> None:
    """Export a saved run to HTML and/or JSON files.

    Paths are auto-generated as report_<id>.html / report_<id>.json
    if not specified explicitly.
    """
    run_data = _get_storage().get_run(run_id)
    if not run_data:
        console.print(f"[red]Run #{run_id} not found.[/red]")
        raise SystemExit(1)

    results = _get_storage().get_run_results(run_id)

    from datetime import datetime
    test_run = TestRun(
        id=run_id,
        project_name=run_data["project_name"],
        started_at=datetime.fromisoformat(run_data["started_at"]),
        finished_at=datetime.fromisoformat(run_data["finished_at"]) if run_data["finished_at"] else None,
        results=results,
    )

    exported_html: Path | None = None

    if fmt in ("html", "all"):
        dest = html_path or Path(f"report_{run_id}.html")
        generate_html_report(test_run, dest)
        console.print(f"[green]HTML[/green] → {dest.resolve()}")
        exported_html = dest

    if fmt in ("json", "all"):
        dest = json_path or Path(f"report_{run_id}.json")
        generate_json_report(test_run, dest)
        console.print(f"[green]JSON[/green] → {dest.resolve()}")

    if open_browser and exported_html:
        import webbrowser
        webbrowser.open(exported_html.resolve().as_uri())
