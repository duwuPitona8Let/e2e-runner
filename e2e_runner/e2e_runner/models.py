from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class Project:
    name: str
    base_url: str
    description: str = ""
    id: int | None = None
    created_at: datetime | None = None


@dataclass
class TestCase:
    name: str
    file_path: str
    function_name: str
    module_name: str = ""


@dataclass
class TestResult:
    test_case: TestCase
    status: TestStatus
    duration: float
    error_message: str | None = None
    screenshot_path: str | None = None
    trace_path: str | None = None


@dataclass
class TestRun:
    project_name: str
    started_at: datetime
    results: list[TestResult] = field(default_factory=list)
    finished_at: datetime | None = None
    id: int | None = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.ERROR)

    @property
    def duration(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
