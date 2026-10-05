import json
from datetime import datetime, timedelta
from pathlib import Path

from e2e_runner.models import TestCase as Case
from e2e_runner.models import TestResult as Result
from e2e_runner.models import TestRun as Run
from e2e_runner.models import TestStatus as Status
from e2e_runner.reporter import generate_html_report, generate_json_report


def _run(tmp_path: Path) -> Run:
    started = datetime(2026, 1, 1, 12, 0)
    return Run(
        project_name="shop <demo>",
        started_at=started,
        finished_at=started + timedelta(seconds=2),
        results=[
            Result(Case("t::test_ok", "t.py", "test_ok"), Status.PASSED, 0.5),
            Result(
                Case("t::test_bad", "t.py", "test_bad"),
                Status.FAILED,
                1.5,
                error_message="<script>alert(1)</script>",
                screenshot_path=str(tmp_path / "shot.png"),
                trace_path=str(tmp_path / "trace.zip"),
            ),
        ],
    )


def test_json_report_contents(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    generate_json_report(_run(tmp_path), out)

    data = json.loads(out.read_text(encoding="utf-8"))

    assert (data["total"], data["passed"], data["failed"], data["verdict"]) == (2, 1, 1, "failed")
    assert data["duration"] == 2.0
    bad = data["results"][1]
    assert bad["status"] == "failed"
    assert bad["trace"].endswith("trace.zip")


def test_html_report_escapes_user_content_and_links_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "r.html"
    generate_html_report(_run(tmp_path), out)

    html = out.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "shop &lt;demo&gt;" in html
    assert (tmp_path / "shot.png").resolve().as_uri() in html
    assert (tmp_path / "trace.zip").resolve().as_uri() in html
