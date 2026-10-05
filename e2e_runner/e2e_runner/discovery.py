import importlib.util
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from .models import TestCase

CONFTEST = "conftest.py"


class DiscoveryError(Exception):
    """A test file or conftest.py could not be imported (SyntaxError, ImportError, ...)."""

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

    conftest.py files between ``path`` and each test file are imported too, and
    recorded on the TestCase (nearest first) so fixtures can be looked up there.
    Files that fail to import are skipped; pass ``errors`` to collect them.
    """
    root = path if path.is_dir() else path.parent
    test_files = sorted(path.rglob("test_*.py")) if path.is_dir() else [path]
    tests: list[TestCase] = []
    conftests: dict[Path, bool] = {}  # conftest path -> imported OK

    def _report(exc: DiscoveryError) -> None:
        if errors is not None:
            errors.append(exc)

    for file in test_files:
        chain = []
        for conftest in _conftest_chain(file, root):
            if conftest not in conftests:
                try:
                    conftests[conftest] = _load_module(conftest) is not None
                except DiscoveryError as exc:
                    conftests[conftest] = False
                    _report(exc)
            if conftests[conftest]:
                chain.append(str(conftest))
        try:
            module = _load_module(file)
        except DiscoveryError as exc:
            _report(exc)
            continue
        if module is not None:
            tests.extend(_collect_from_module(module, file, filter_pattern, tuple(chain)))
    return tests


def _conftest_chain(file: Path, root: Path) -> list[Path]:
    """conftest.py files from the test file's directory up to ``root`` (inclusive), nearest first."""
    chain = []
    directory = file.parent.resolve()
    root = root.resolve()
    while True:
        candidate = directory / CONFTEST
        if candidate.is_file():
            chain.append(candidate)
        if directory == root or root not in directory.parents:
            break
        directory = directory.parent
    return chain


def _collect_from_module(
    module: ModuleType, file: Path, filter_pattern: str, conftest_paths: tuple[str, ...]
) -> list[TestCase]:
    tests: list[TestCase] = []
    for name, _ in inspect.getmembers(module, inspect.isfunction):
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
                conftest_paths=conftest_paths,
            )
        )
    return tests


def _module_name(file: Path) -> str:
    return f"_e2e_discovered.{file.stem}_{abs(hash(str(file)))}"


def _load_module(file: Path) -> ModuleType | None:
    """Import a test file under a synthetic module name. Raises DiscoveryError on failure."""
    module_name = _module_name(file)
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


def get_module(test_case: TestCase) -> ModuleType | None:
    """The test's module, re-imported if it is no longer in sys.modules."""
    module = sys.modules.get(test_case.module_name)
    if module is not None:
        return module
    try:
        return _load_module(Path(test_case.file_path))
    except DiscoveryError:
        return None


def get_conftests(test_case: TestCase) -> list[ModuleType]:
    """The test's conftest.py modules, nearest first."""
    modules = []
    for path_str in test_case.conftest_paths:
        path = Path(path_str)
        module = sys.modules.get(_module_name(path))
        if module is None:
            try:
                module = _load_module(path)
            except DiscoveryError:
                module = None
        if module is not None:
            modules.append(module)
    return modules


def get_callable(test_case: TestCase) -> Callable | None:
    module = get_module(test_case)
    if module is None:
        return None
    return getattr(module, test_case.function_name, None)
