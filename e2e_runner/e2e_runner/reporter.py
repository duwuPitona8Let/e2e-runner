from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from .models import TestResult, TestRun, TestStatus

console = Console()

STATUS_STYLE: dict[TestStatus, tuple[str, str]] = {
    TestStatus.PASSED:  ("PASS",  "bold green"),
    TestStatus.FAILED:  ("FAIL",  "bold red"),
    TestStatus.ERROR:   ("ERROR", "bold yellow"),
    TestStatus.SKIPPED: ("SKIP",  "dim"),
}


def make_progress(total: int) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def print_result_line(result: TestResult) -> None:
    label, style = STATUS_STYLE[result.status]
    duration_str = f"{result.duration:.2f}s"
    text = Text()
    text.append(f"  [{label}] ", style=style)
    text.append(result.test_case.name)
    text.append(f"  {duration_str}", style="dim")
    if result.error_message:
        text.append(f"\n         {result.error_message[:120]}", style="red")
    console.print(text)


def print_summary(run: TestRun) -> None:
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Test", style="white")
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right", style="dim")

    for result in run.results:
        label, style = STATUS_STYLE[result.status]
        table.add_row(
            result.test_case.name,
            Text(label, style=style),
            f"{result.duration:.2f}s",
        )

    console.print()
    console.print(table)
    console.print()

    passed_style = "bold green" if run.passed == run.total else "green"
    failed_style = "bold red" if run.failed > 0 else "dim"
    error_style  = "bold yellow" if run.errored > 0 else "dim"

    summary_text = Text()
    summary_text.append(f"  Passed:  {run.passed}", style=passed_style)
    summary_text.append(f"   Failed: {run.failed}", style=failed_style)
    summary_text.append(f"   Errors: {run.errored}", style=error_style)
    summary_text.append(f"   Total:  {run.total}   ")
    summary_text.append(f"{run.duration:.2f}s", style="dim")

    verdict = "PASSED" if run.failed == 0 and run.errored == 0 else "FAILED"
    verdict_style = "bold green on dark_green" if verdict == "PASSED" else "bold red on dark_red"

    console.print(
        Panel(summary_text, title=f"[{verdict_style}]  {verdict}  ", expand=False)
    )


def generate_html_report(run: TestRun, output_path: Path) -> None:
    rows_parts: list[str] = []
    for r in run.results:
        label, _ = STATUS_STYLE[r.status]
        css = {"PASS": "pass", "FAIL": "fail", "ERROR": "error", "SKIP": "skip"}[label]
        error_html = f"<pre>{_esc(r.error_message)}</pre>" if r.error_message else ""
        links = [
            f'<a href="{_esc(_file_uri(path))}" target="_blank">{name}</a>'
            for name, path in (("screenshot", r.screenshot_path), ("trace", r.trace_path))
            if path
        ]
        screenshot_html = "<br>" + " · ".join(links) if links else ""
        rows_parts.append(f"""
        <tr class="{css}">
          <td>{_esc(r.test_case.name)}</td>
          <td class="badge {css}">{label}</td>
          <td>{r.duration:.2f}s</td>
          <td>{error_html}{screenshot_html}</td>
        </tr>""")
    rows = "".join(rows_parts)

    verdict = "PASSED" if run.failed == 0 and run.errored == 0 else "FAILED"
    verdict_css = "pass" if verdict == "PASSED" else "fail"
    ts = run.started_at.strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>E2E Report — {_esc(run.project_name)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; background: #0f0f0f; color: #e0e0e0; }}
  header {{ background: #1a1a2e; padding: 24px 40px; border-bottom: 1px solid #333; }}
  header h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  header p  {{ margin: 0; color: #888; font-size: .9rem; }}
  .stats {{ display: flex; gap: 24px; padding: 20px 40px; background: #111; }}
  .stat  {{ background: #1e1e1e; border-radius: 8px; padding: 16px 24px; min-width: 100px; text-align: center; }}
  .stat .val  {{ font-size: 2rem; font-weight: 700; }}
  .stat .lbl  {{ font-size: .75rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
  .pass .val {{ color: #4caf50; }}
  .fail .val {{ color: #f44336; }}
  .error .val {{ color: #ff9800; }}
  .neutral .val {{ color: #e0e0e0; }}
  main {{ padding: 24px 40px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e1e1e; border-radius: 8px; overflow: hidden; }}
  th {{ background: #252525; padding: 12px 16px; text-align: left; font-size: .8rem;
        text-transform: uppercase; letter-spacing: .5px; color: #aaa; }}
  td {{ padding: 12px 16px; border-top: 1px solid #2a2a2a; vertical-align: top; font-size: .9rem; }}
  pre {{ margin: 4px 0; font-size: .8rem; color: #f44336; white-space: pre-wrap; word-break: break-all; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 4px;
            font-size: .75rem; font-weight: 700; letter-spacing: .5px; }}
  tr.pass  .badge.pass  {{ background: #1b3d1e; color: #4caf50; }}
  tr.fail  .badge.fail  {{ background: #3d1b1b; color: #f44336; }}
  tr.error .badge.error {{ background: #3d2b1b; color: #ff9800; }}
  tr.skip  .badge.skip  {{ background: #2a2a2a; color: #888; }}
  .verdict {{ display: inline-block; padding: 4px 16px; border-radius: 6px;
              font-weight: 700; font-size: 1rem; }}
  .verdict.pass {{ background: #1b3d1e; color: #4caf50; }}
  .verdict.fail {{ background: #3d1b1b; color: #f44336; }}
</style>
</head>
<body>
<header>
  <h1>E2E Report — {_esc(run.project_name)}
    <span class="verdict {verdict_css}">{verdict}</span>
  </h1>
  <p>{ts} &nbsp;·&nbsp; {run.duration:.2f}s total</p>
</header>
<div class="stats">
  <div class="stat pass">  <div class="val">{run.passed}</div>  <div class="lbl">Passed</div>  </div>
  <div class="stat fail">  <div class="val">{run.failed}</div>  <div class="lbl">Failed</div>  </div>
  <div class="stat error"> <div class="val">{run.errored}</div> <div class="lbl">Errors</div>  </div>
  <div class="stat neutral"><div class="val">{run.total}</div>  <div class="lbl">Total</div>   </div>
</div>
<main>
<table>
  <thead><tr><th>Test</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
</main>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")


def generate_json_report(run: TestRun, output_path: Path) -> None:
    import json

    data = {
        "project": run.project_name,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration": run.duration,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "errored": run.errored,
        "verdict": "passed" if run.failed == 0 and run.errored == 0 else "failed",
        "results": [
            {
                "name": r.test_case.name,
                "file": r.test_case.file_path,
                "status": r.status.value,
                "duration": round(r.duration, 4),
                "error": r.error_message,
                "screenshot": r.screenshot_path,
                "trace": r.trace_path,
            }
            for r in run.results
        ],
    }
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_uri(path: str) -> str:
    """Absolute file:// URI so links work no matter where the report is saved."""
    return Path(path).resolve().as_uri()


def _esc(s: str | None) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
