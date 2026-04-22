import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Project, TestCase, TestResult, TestRun, TestStatus

DEFAULT_DB_PATH = Path.home() / ".e2e_runner" / "storage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    base_url    TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    total        INTEGER NOT NULL DEFAULT 0,
    passed       INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    errored      INTEGER NOT NULL DEFAULT 0,
    duration     REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS test_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    test_name       TEXT    NOT NULL,
    file_path       TEXT    NOT NULL,
    function_name   TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    duration        REAL    NOT NULL,
    error_message   TEXT,
    screenshot_path TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
"""


class Storage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def add_project(self, project: Project) -> Project:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, base_url, description, created_at) VALUES (?, ?, ?, ?)",
                (project.name, project.base_url, project.description, datetime.now().isoformat()),
            )
            project.id = cur.lastrowid
        return project

    def get_project(self, name: str) -> Optional[Project]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            base_url=row["base_url"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_projects(self) -> list[Project]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [
            Project(
                id=r["id"],
                name=r["name"],
                base_url=r["base_url"],
                description=r["description"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def remove_project(self, name: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        return cur.rowcount > 0

    def update_project(self, name: str, base_url: Optional[str], description: Optional[str]) -> bool:
        fields, values = [], []
        if base_url is not None:
            fields.append("base_url = ?")
            values.append(base_url)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if not fields:
            return False
        values.append(name)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE name = ?", values)
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Runs & results
    # ------------------------------------------------------------------

    def save_run(self, run: TestRun) -> TestRun:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO runs (project_name, started_at, finished_at, total, passed, failed, errored, duration)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.project_name,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.total,
                    run.passed,
                    run.failed,
                    run.errored,
                    run.duration,
                ),
            )
            run_id = cur.lastrowid
            for result in run.results:
                conn.execute(
                    """INSERT INTO test_results
                       (run_id, test_name, file_path, function_name, status, duration, error_message, screenshot_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        result.test_case.name,
                        result.test_case.file_path,
                        result.test_case.function_name,
                        result.status.value,
                        result.duration,
                        result.error_message,
                        result.screenshot_path,
                    ),
                )
            run.id = run_id
        return run

    def list_runs(self, project_name: Optional[str] = None, limit: int = 20) -> list[dict]:
        query = "SELECT * FROM runs"
        params: list = []
        if project_name:
            query += " WHERE project_name = ?"
            params.append(project_name)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_run_results(self, run_id: int) -> list[TestResult]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM test_results WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        results = []
        for r in rows:
            tc = TestCase(
                name=r["test_name"],
                file_path=r["file_path"],
                function_name=r["function_name"],
            )
            results.append(
                TestResult(
                    test_case=tc,
                    status=TestStatus(r["status"]),
                    duration=r["duration"],
                    error_message=r["error_message"],
                    screenshot_path=r["screenshot_path"],
                )
            )
        return results

    def get_run(self, run_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def project_stats(self, project_name: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as total_runs,
                          SUM(passed) as total_passed,
                          SUM(failed) as total_failed,
                          AVG(duration) as avg_duration
                   FROM runs WHERE project_name = ?""",
                (project_name,),
            ).fetchone()
        return dict(row) if row else {}
