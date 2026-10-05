
import inspect
import logging
import queue
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .discovery import get_callable
from .models import TestCase, TestResult, TestRun, TestStatus

SCREENSHOT_DIR = Path.home() / ".e2e_runner" / "screenshots"
TRACE_DIR = Path.home() / ".e2e_runner" / "traces"

logger = logging.getLogger(__name__)


def run_suite(
    tests: list[TestCase],
    project_name: str,
    base_url: str = "",
    headless: bool = True,
    timeout: int = 30000,
    workers: int = 1,
    retries: int = 0,
    fail_fast: bool = False,
    trace: bool = False,
    on_result: Callable[[TestResult], None] | None = None,
) -> TestRun:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if trace:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
    run = TestRun(project_name=project_name, started_at=datetime.now())

    if workers > 1:
        results = _run_parallel(tests, base_url, headless, timeout, retries, trace, workers, on_result)
    else:
        results = list(_run_sequential(tests, base_url, headless, timeout, retries, trace, fail_fast, on_result))

    run.results = results
    run.finished_at = datetime.now()
    return run


def _run_sequential(
    tests: list[TestCase],
    base_url: str,
    headless: bool,
    timeout: int,
    retries: int,
    trace: bool,
    fail_fast: bool,
    on_result: Callable | None,
) -> Iterator[TestResult]:
    def _emit(results: Iterator[TestResult]) -> Iterator[TestResult]:
        for result in results:
            if on_result:
                on_result(result)
            yield result
            if fail_fast and result.status in (TestStatus.FAILED, TestStatus.ERROR):
                return

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:
            # Browser could not start: report every test as ERROR instead of crashing the run.
            message = f"Browser failed to start: {type(exc).__name__}: {exc}"
            yield from _emit(_error_result(test, message) for test in tests)
            return
        try:
            yield from _emit(
                _safe_execute(test, browser, base_url, timeout, retries, trace) for test in tests
            )
        finally:
            browser.close()


def _run_parallel(
    tests: list[TestCase],
    base_url: str,
    headless: bool,
    timeout: int,
    retries: int,
    trace: bool,
    workers: int,
    on_result: Callable | None,
) -> list[TestResult]:
    """Each worker thread owns one sync_playwright + browser and pulls tests from a shared queue."""
    results: list[TestResult] = [None] * len(tests)  # type: ignore[list-item]
    pending: queue.Queue[tuple[int, TestCase]] = queue.Queue()
    for item in enumerate(tests):
        pending.put(item)
    done: queue.Queue[tuple[int, TestResult]] = queue.Queue()

    def _drain(execute: Callable[[TestCase], TestResult]) -> None:
        while True:
            try:
                index, test = pending.get_nowait()
            except queue.Empty:
                return
            done.put((index, execute(test)))

    def _worker() -> None:
        # Any failure outside a test (Playwright/browser startup) must still produce a result
        # for every remaining test, otherwise the consumer loop below would wait forever.
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                try:
                    _drain(lambda t: _safe_execute(t, browser, base_url, timeout, retries, trace))
                finally:
                    browser.close()
        except Exception as exc:
            message = f"Browser failed to start: {type(exc).__name__}: {exc}"
            _drain(lambda t: _error_result(t, message))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in range(min(workers, len(tests))):
            pool.submit(_worker)
        # Results are consumed on the calling thread, so on_result never runs in a worker.
        for _ in range(len(tests)):
            index, result = done.get()
            results[index] = result
            if on_result:
                on_result(result)

    return results


def _error_result(test: TestCase, message: str) -> TestResult:
    return TestResult(test_case=test, status=TestStatus.ERROR, duration=0.0, error_message=message)


def _safe_execute(
    test: TestCase,
    browser: Browser,
    base_url: str,
    timeout: int,
    retries: int,
    trace: bool,
) -> TestResult:
    """Never raises: an unexpected runner error becomes an ERROR result for this test only."""
    try:
        return _execute_with_retry(test, browser, base_url, timeout, retries, trace)
    except Exception as exc:
        return _error_result(test, f"Runner error: {type(exc).__name__}: {exc}")


def _execute_with_retry(
    test: TestCase,
    browser: Browser,
    base_url: str,
    timeout: int,
    retries: int,
    trace: bool = False,
) -> TestResult:
    result = _execute_test(test, browser, base_url, timeout, trace)
    attempt = 1
    while result.status in (TestStatus.FAILED, TestStatus.ERROR) and attempt <= retries:
        result = _execute_test(test, browser, base_url, timeout, trace, attempt=attempt)
        attempt += 1
    return result


def _execute_test(
    test: TestCase,
    browser: Browser,
    base_url: str,
    timeout: int,
    trace: bool = False,
    attempt: int = 0,
) -> TestResult:
    func = get_callable(test)
    if func is None:
        return _error_result(test, "Could not load test function")

    context: BrowserContext = browser.new_context(base_url=base_url or None)
    context.set_default_timeout(timeout)
    if trace:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page: Page = context.new_page()
    screenshot_path: str | None = None
    trace_path: str | None = None
    start = time.perf_counter()

    try:
        _call_test(func, page, base_url)
        status = TestStatus.PASSED
        error_message = None
    except AssertionError as exc:
        status = TestStatus.FAILED
        error_message = str(exc) or "Assertion failed"
        screenshot_path = _take_screenshot(page, test, attempt)
    except Exception as exc:
        status = TestStatus.ERROR
        error_message = f"{type(exc).__name__}: {exc}"
        screenshot_path = _take_screenshot(page, test, attempt)
    finally:
        duration = time.perf_counter() - start
        if trace:
            trace_path = _stop_trace(context, test, attempt, keep=status != TestStatus.PASSED)
        try:
            context.close()
        except Exception:
            logger.warning("Failed to close browser context for %s", test.name, exc_info=True)

    return TestResult(
        test_case=test,
        status=status,
        duration=duration,
        error_message=error_message,
        screenshot_path=screenshot_path,
        trace_path=trace_path,
    )


def _call_test(func: Callable, page: Page, base_url: str) -> None:
    sig = inspect.signature(func)
    kwargs: dict = {}
    if "page" in sig.parameters:
        kwargs["page"] = page
    if "base_url" in sig.parameters:
        kwargs["base_url"] = base_url
    func(**kwargs)


def _artifact_name(test: TestCase, attempt: int) -> str:
    safe_name = test.name.replace("::", "__").replace("/", "_")
    suffix = f"_retry{attempt}" if attempt > 0 else ""
    return f"{safe_name}{suffix}_{int(time.time())}"


def _take_screenshot(page: Page, test: TestCase, attempt: int = 0) -> str | None:
    try:
        path = SCREENSHOT_DIR / f"{_artifact_name(test, attempt)}.png"
        page.screenshot(path=str(path))
        return str(path)
    except Exception:
        logger.warning("Failed to take screenshot for %s", test.name, exc_info=True)
        return None


def _stop_trace(context: BrowserContext, test: TestCase, attempt: int, keep: bool) -> str | None:
    """Save the trace only for failed tests; passing-test traces are discarded."""
    try:
        if not keep:
            context.tracing.stop()
            return None
        path = TRACE_DIR / f"{_artifact_name(test, attempt)}.zip"
        context.tracing.stop(path=str(path))
        return str(path)
    except Exception:
        logger.warning("Failed to save trace for %s", test.name, exc_info=True)
        return None
