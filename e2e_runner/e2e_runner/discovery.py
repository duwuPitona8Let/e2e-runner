import importlib.util
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from .models import TestCase


class DiscoveryError(Exception):
    """A test file could not be imported (SyntaxError, ImportError, ...)."""

    def __init__(self, file: Path, cause: BaseException) -> None:
        super().__init__(f"{file}: {type(cause).__name__}: {cause}")
        self.file = file
        self.cause = cause


def discover_tests(
    path: Path,
    filter_pattern: str = "",
    errors: list[DiscoveryError] | None = None,
) -> list[TestCase]:
    """Recursively find all test_* functions in test_*.py files.

    Files that fail to import are skipped; pass ``errors`` to collect them.
    """
    test_files = sorted(path.rglob("test_*.py")) if path.is_dir() else [path]
    tests: list[TestCase] = []
    for file in test_files:
        try:
            module = _load_module(file)
        except DiscoveryError as exc:
            if errors is not None:
                errors.append(exc)
            continue
        if module is not None:
            tests.extend(_collect_from_module(module, file, filter_pattern))
    return tests


def _collect_from_module(module: ModuleType, file: Path, filter_pattern: str) -> list[TestCase]:

    tests: list[TestCase] = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        if filter_pattern and filter_pattern.lower() not in name.lower():
            continue
        tests.append(
            TestCase(
                name=f"{file.stem}::{name}",
                file_path=str(file),
                function_name=name,
                module_name=module.__name__,
            )
        )
    return tests


def _load_module(file: Path) -> ModuleType | None:
    """Import a test file under a synthetic module name. Raises DiscoveryError on failure."""
    module_name = f"_e2e_discovered.{file.stem}_{abs(hash(str(file)))}"
    spec = importlib.util.spec_from_file_location(module_name, file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        # Do not leave a half-initialised module behind for get_callable() to pick up.
        sys.modules.pop(module_name, None)
        raise DiscoveryError(file, exc) from exc
    return module


def get_callable(test_case: TestCase) -> Callable | None:
    module = sys.modules.get(test_case.module_name)
    if module is None:
        try:
            module = _load_module(Path(test_case.file_path))
        except DiscoveryError:
            return None
    if module is None:
        return None
    return getattr(module, test_case.function_name, None)
