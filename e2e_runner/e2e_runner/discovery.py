import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Callable

from .models import TestCase


def discover_tests(path: Path, filter_pattern: str = "") -> list[TestCase]:
    """Recursively find all test_* functions in test_*.py files."""
    test_files = sorted(path.rglob("test_*.py")) if path.is_dir() else [path]
    tests: list[TestCase] = []
    for file in test_files:
        tests.extend(_collect_from_file(file, filter_pattern))
    return tests


def _collect_from_file(file: Path, filter_pattern: str) -> list[TestCase]:
    module = _load_module(file)
    if module is None:
        return []

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


def _load_module(file: Path):
    module_name = f"_e2e_discovered.{file.stem}_{abs(hash(str(file)))}"
    spec = importlib.util.spec_from_file_location(module_name, file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        from rich.console import Console
        Console(stderr=True).print(f"[yellow]Warning:[/yellow] could not import {file}: {exc}")
        return None
    return module


def get_callable(test_case: TestCase) -> Callable | None:
    module_name = next(
        (k for k in sys.modules if k.endswith(f".{test_case.file_path.replace('/', '_')}")),
        None,
    )
    if module_name is None:
        module = _load_module(Path(test_case.file_path))
    else:
        module = sys.modules[module_name]
    if module is None:
        return None
    return getattr(module, test_case.function_name, None)
