from pathlib import Path
from urllib.parse import urlparse

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .discovery import discover_tests
from .models import Project, TestRun
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

_storage = Storage()


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


@click.group()
@click.version_option("1.0.0", prog_name="e2e")
def main() -> None:
    """E2E test runner for web applications."""


# ──────────────────────────────────────────────
#  run
# ──────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("-p", "--project", default="default", show_default=True, help="Project name")
@click.option("-u", "--base-url", default="", help="Base URL injected into tests")
@click.option("-k", "--filter", "filter_pattern", default="", help="Filter tests by name substring")
@click.option("--headed", is_flag=True, help="Run browser in headed (visible) mode")
@click.option("-n", "--workers", default=1, show_default=True, help="Parallel workers")
@click.option("--timeout", default=30000, show_default=True, help="Browser action timeout (ms)")
@click.option("--html", "html_report", type=click.Path(path_type=Path), default=None, help="Save HTML report to file")
@click.option("--json", "json_report", type=click.Path(path_type=Path), default=None, help="Save JSON report to file")
@click.option("--retry", default=0, show_default=True, help="Retry failed tests N times")
@click.option("--fail-fast", is_flag=True, help="Stop on first failure")
@click.option("--save/--no-save", default=True, show_default=True, help="Save run to history")
def run(
    path: Path,
    project: str,
    base_url: str,
    filter_pattern: str,
    headed: bool,
    workers: int,
    timeout: int,
    html_report: Path | None,
    json_report: Path | None,
    retry: int,
    fail_fast: bool,
    save: bool,
) -> None:
    """Discover and run E2E tests in PATH."""
    _validate_timeout(timeout)
    _validate_retry(retry)
    if base_url:
        _validate_url(base_url, "base-url")
    project_obj = _storage.get_project(project)
    effective_url = base_url or (project_obj.base_url if project_obj else "")

    tests = discover_tests(path, filter_pattern)
    if not tests:
        console.print("[yellow]No tests found.[/yellow]")
        raise SystemExit(0)

    console.print(f"\n[bold]Found {len(tests)} test(s)[/bold] in [cyan]{path}[/cyan]\n")

    progress = make_progress(len(tests))
    task_id = progress.add_task("Running…", total=len(tests))

    completed_results = []

    def on_result(result):
        completed_results.append(result)
        print_result_line(result)
        progress.advance(task_id)

    with progress:
        test_run = run_suite(
            tests=tests,
            project_name=project,
            base_url=effective_url,
            headless=not headed,
            timeout=timeout,
            workers=workers,
            retries=retry,
            fail_fast=fail_fast,
            on_result=on_result,
        )

    print_summary(test_run)

    if save:
        _storage.save_run(test_run)
        console.print(f"[dim]Run saved (id={test_run.id})[/dim]")

    if html_report:
        generate_html_report(test_run, html_report)
        console.print(f"[dim]HTML report → {html_report}[/dim]")

    if json_report:
        generate_json_report(test_run, json_report)
        console.print(f"[dim]JSON report → {json_report}[/dim]")

    raise SystemExit(0 if test_run.failed == 0 and test_run.errored == 0 else 1)


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
    tests = discover_tests(path, filter_pattern)
    if not tests:
        console.print("[yellow]No tests found.[/yellow]")
        return

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
    if _storage.get_project(name):
        console.print(f"[red]Project '{name}' already exists.[/red]")
        raise SystemExit(1)
    project = _storage.add_project(Project(name=name, base_url=base_url, description=description))
    console.print(f"[green]Project added:[/green] {project.name} → {project.base_url}")


@projects.command("list")
def projects_list() -> None:
    """Show all registered projects."""
    items = _storage.list_projects()
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
    if not _storage.remove_project(name):
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
    if not _storage.update_project(name, base_url, description):
        console.print(f"[red]Project '{name}' not found or nothing to update.[/red]")
        raise SystemExit(1)
    console.print(f"[green]Updated:[/green] {name}")


@projects.command("stats")
@click.argument("name")
def projects_stats(name: str) -> None:
    """Show run statistics for a project."""
    stats = _storage.project_stats(name)
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
    runs = _storage.list_runs(project_name=project, limit=limit)
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
    run_data = _storage.get_run(run_id)
    if not run_data:
        console.print(f"[red]Run #{run_id} not found.[/red]")
        raise SystemExit(1)

    results = _storage.get_run_results(run_id)

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
