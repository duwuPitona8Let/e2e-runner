
import inspect
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .models import TestCase, TestResult, TestRun, TestStatus

SCREENSHOT_DIR = Path.home() / ".e2e_runner" / "screenshots"


def run_suite(
    tests: list[TestCase],
    project_name: str,
    base_url: str = "",
    headless: bool = True,
    timeout: int = 30000,
    workers: int = 1,
    retries: int = 0,
    fail_fast: bool = False,
    on_result: Callable[[TestResult], None] | None = None,
) -> TestRun:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    run = TestRun(project_name=project_name, started_at=datetime.now())

    if workers > 1:
        results = _run_parallel(tests, base_url, headless, timeout, retries, workers, on_result)
    else:
        results = list(_run_sequential(tests, base_url, headless, timeout, retries, fail_fast, on_result))

    run.results = results
    run.finished_at = datetime.now()
    return run


def _run_sequential(
    tests: list[TestCase],
    base_url: str,
    headless: bool,
    timeout: int,
    retries: int,
    fail_fast: bool,
    on_result: Callable | None,
) -> Iterator[TestResult]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        for test in tests:
            result = _execute_with_retry(test, browser, base_url, timeout, retries)
            if on_result:
                on_result(result)
            yield result
            if fail_fast and result.status in (TestStatus.FAILED, TestStatus.ERROR):
                browser.close()
                return
        browser.close()


def _run_parallel(
    tests: list[TestCase],
    base_url: str,
    headless: bool,
    timeout: int,
    retries: int,
    workers: int,
    on_result: Callable | None,
) -> list[TestResult]:
    results: list[TestResult] = [None] * len(tests)  # type: ignore

    def _task(index: int, test: TestCase) -> tuple[int, TestResult]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            result = _execute_with_retry(test, browser, base_url, timeout, retries)
            browser.close()
        return index, result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_task, i, t): i for i, t in enumerate(tests)}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            if on_result:
                on_result(result)

    return results


def _execute_with_retry(
    test: TestCase,
    browser: Browser,
    base_url: str,
    timeout: int,
    retries: int,
) -> TestResult:
    result = _execute_test(test, browser, base_url, timeout)
    attempt = 1
    while result.status in (TestStatus.FAILED, TestStatus.ERROR) and attempt <= retries:
        result = _execute_test(test, browser, base_url, timeout, attempt=attempt)
        attempt += 1
    return result


def _execute_test(
    test: TestCase,
    browser: Browser,
    base_url: str,
    timeout: int,
    attempt: int = 0,
) -> TestResult:
    from .discovery import get_callable

    func = get_callable(test)
    if func is None:
        return TestResult(
            test_case=test,
            status=TestStatus.ERROR,
            duration=0.0,
            error_message="Could not load test function",
        )

    context: BrowserContext = browser.new_context(base_url=base_url or None)
    context.set_default_timeout(timeout)
    page: Page = context.new_page()
    screenshot_path: str | None = None
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
        try:
            context.close()
        except Exception:
            pass

    return TestResult(
        test_case=test,
        status=status,
        duration=duration,
        error_message=error_message,
        screenshot_path=screenshot_path,
    )


def _call_test(func: Callable, page: Page, base_url: str) -> None:
    sig = inspect.signature(func)
    kwargs: dict = {}
    if "page" in sig.parameters:
        kwargs["page"] = page
    if "base_url" in sig.parameters:
        kwargs["base_url"] = base_url
    func(**kwargs)


def _take_screenshot(page: Page, test: TestCase, attempt: int = 0) -> str | None:
    try:
        safe_name = test.name.replace("::", "__").replace("/", "_")
        suffix = f"_retry{attempt}" if attempt > 0 else ""
        path = SCREENSHOT_DIR / f"{safe_name}{suffix}_{int(time.time())}.png"
        page.screenshot(path=str(path))
        return str(path)
    except Exception:
        return None
