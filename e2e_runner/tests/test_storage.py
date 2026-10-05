import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from e2e_runner.models import Project
from e2e_runner.models import TestCase as Case
from e2e_runner.models import TestResult as Result
from e2e_runner.models import TestRun as Run
from e2e_runner.models import TestStatus as Status
from e2e_runner.storage import Storage


def _run(project: str = "demo", offset_min: int = 0) -> Run:
    started = datetime(2026, 1, 1, 12, 0) + timedelta(minutes=offset_min)
    case = Case(name="test_a::test_x", file_path="/t/test_a.py", function_name="test_x")
    return Run(
        project_name=project,
        started_at=started,
        finished_at=started + timedelta(seconds=3),
        results=[
            Result(case, Status.PASSED, 1.0),
            Result(case, Status.FAILED, 2.0, "boom", "/s/shot.png", "/t/trace.zip"),
        ],
    )


def test_save_and_read_run_roundtrip(storage: Storage) -> None:
    saved = storage.save_run(_run())

    row = storage.get_run(saved.id)
    results = storage.get_run_results(saved.id)

    assert (row["total"], row["passed"], row["failed"], row["duration"]) == (2, 1, 1, 3.0)
    assert [r.status for r in results] == [Status.PASSED, Status.FAILED]
    assert results[1].error_message == "boom"
    assert results[1].screenshot_path == "/s/shot.png"
    assert results[1].trace_path == "/t/trace.zip"


def test_list_runs_newest_first_with_filter_and_limit(storage: Storage) -> None:
    for i, project in enumerate(["a", "b", "c"]):
        storage.save_run(_run(project, offset_min=i))

    assert [r["project_name"] for r in storage.list_runs()] == ["c", "b", "a"]
    assert [r["project_name"] for r in storage.list_runs(project_name="b")] == ["b"]
    assert len(storage.list_runs(limit=1)) == 1


def test_delete_runs_keep_last_and_cascade(storage: Storage) -> None:
    ids = [storage.save_run(_run(offset_min=i)).id for i in range(5)]

    deleted = storage.delete_runs(keep_last=2)

    assert deleted == 3
    assert [r["id"] for r in storage.list_runs()] == [ids[4], ids[3]]
    assert storage.get_run_results(ids[0]) == []  # removed by ON DELETE CASCADE


def test_delete_runs_only_for_project(storage: Storage) -> None:
    storage.save_run(_run("a"))
    storage.save_run(_run("b"))

    assert storage.delete_runs(project_name="a") == 1
    assert [r["project_name"] for r in storage.list_runs()] == ["b"]


def test_project_crud(storage: Storage) -> None:
    storage.add_project(Project(name="shop", base_url="http://a"))

    assert storage.update_project("shop", "http://b", None)
    assert storage.update_project("shop", None, "desc")
    project = storage.get_project("shop")
    assert (project.base_url, project.description) == ("http://b", "desc")

    assert not storage.update_project("shop", None, None)
    assert not storage.update_project("missing", "http://c", None)
    assert storage.remove_project("shop")
    assert storage.get_project("shop") is None


def test_project_stats(storage: Storage) -> None:
    storage.save_run(_run("demo"))
    storage.save_run(_run("demo", offset_min=1))

    stats = storage.project_stats("demo")

    assert (stats["total_runs"], stats["total_passed"], stats["total_failed"]) == (2, 2, 2)


def test_migrates_old_db_without_trace_path(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
            test_name TEXT NOT NULL, file_path TEXT NOT NULL, function_name TEXT NOT NULL,
            status TEXT NOT NULL, duration REAL NOT NULL, error_message TEXT, screenshot_path TEXT
        );
        """
    )
    conn.close()

    storage = Storage(db_path=db)
    Storage(db_path=db)  # a second init must not fail on the now-existing column

    with closing(sqlite3.connect(db)) as check:
        columns = [row[1] for row in check.execute("PRAGMA table_info(test_results)")]
    assert "trace_path" in columns
    assert storage.save_run(_run()).id is not None
