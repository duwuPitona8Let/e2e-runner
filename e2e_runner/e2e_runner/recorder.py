"""`e2e record`: record a browser session with `playwright codegen` and save it as an e2e_runner test.

codegen (target ``python-pytest``) produces a ``def test_example(page: Page)`` function with absolute
URLs. We take that function's body, rename it, and make ``page.goto()`` URLs on the recorded origin
relative, so the test runs against whatever ``--base-url`` is passed to ``e2e run``.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import textwrap
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


class RecordError(Exception):
    """Recording could not be completed or converted."""


def record(url: str, output: Path, name: str | None = None) -> tuple[str, Path]:
    """Open codegen on ``url``; when the browser is closed, write the test. Returns (test name, path)."""
    source = _run_codegen(url)
    body = relativize_urls(extract_test_body(source), _origin(url))
    test_name = name or _unique_name(output, default_test_name(output))
    write_test(output, test_name, body, recorded_from=url)
    return test_name, output


def _run_codegen(url: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "recorded.py"
        cmd = [sys.executable, "-m", "playwright", "codegen", "--target", "python-pytest", "-o", str(out), url]
        try:
            # Output is captured so codegen's messages don't draw over the TUI.
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        except OSError as exc:
            raise RecordError(f"could not start playwright codegen: {exc}") from exc
        if not out.exists():
            details = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
            raise RecordError(
                f"playwright codegen exited with code {proc.returncode} without saving a recording "
                "(is Chromium installed? run: playwright install chromium)" + (f"\n{details}" if details else "")
            )
        return out.read_text(encoding="utf-8")


def extract_test_body(source: str) -> str:
    """Return the dedented body of the first test_* function in codegen output."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RecordError(f"codegen output is not valid Python: {exc}") from exc

    func = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")),
        None,
    )
    if func is None:
        raise RecordError("codegen output contains no test function")

    lines = source.splitlines()
    body = "\n".join(lines[func.body[0].lineno - 1 : func.end_lineno])
    body = textwrap.dedent(body).strip("\n")
    if not body or body == "pass":
        raise RecordError("nothing was recorded")
    return body


def relativize_urls(body: str, origin: str) -> str:
    """page.goto("http://host:port/path") -> page.goto("/path") for URLs on the recorded origin."""
    if not origin:
        return body
    pattern = re.compile(r'(\.goto\(\s*)(["\'])' + re.escape(origin) + r'(/[^"\']*)?\2')
    return pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or '/'}{m.group(2)}", body)


def default_test_name(output: Path) -> str:
    stem = re.sub(r"\W", "_", output.stem)
    return stem if stem.startswith("test_") else f"test_{stem}"


def _unique_name(output: Path, base: str) -> str:
    existing = _defined_functions(output.read_text(encoding="utf-8")) if output.exists() else set()
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def write_test(output: Path, name: str, body: str, recorded_from: str) -> None:
    """Create ``output`` or append the test to it, adding only the imports the body needs."""
    if not name.isidentifier() or not name.startswith("test_"):
        raise RecordError(f"invalid test name {name!r}: must be a Python identifier starting with 'test_'")

    function = f"def {name}(page: Page) -> None:\n" + textwrap.indent(body, "    ") + "\n"
    uses_re = re.search(r"\bre\.", body) is not None
    pw_names = ["Page", "expect"] if re.search(r"\bexpect\(", body) else ["Page"]

    if output.exists():
        source = output.read_text(encoding="utf-8")
        if name in _defined_functions(source):
            raise RecordError(f"{output} already defines {name}()")
        source = _add_missing_imports(source, uses_re, pw_names)
        output.write_text(source.rstrip("\n") + "\n\n\n" + function, encoding="utf-8")
        return

    imports = ("import re\n\n" if uses_re else "") + f"from playwright.sync_api import {', '.join(pw_names)}\n"
    header = (
        f'"""Recorded with `e2e record` from {recorded_from} on {date.today().isoformat()}.\n\n'
        f"Run: e2e run {output} -u {_origin(recorded_from) or recorded_from}\n"
        '"""\n'
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + imports + "\n\n" + function, encoding="utf-8")


def _add_missing_imports(source: str, uses_re: bool, pw_names: list[str]) -> str:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(alias.asname or alias.name for alias in node.names)

    missing = []
    if uses_re and "re" not in imported:
        missing.append("import re")
    missing_pw = [n for n in pw_names if n not in imported]
    if missing_pw:
        missing.append(f"from playwright.sync_api import {', '.join(missing_pw)}")
    if not missing:
        return source

    # Insert right after the module docstring (if any), before the first statement.
    first = tree.body[0] if tree.body else None
    is_docstring = (
        isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    )
    lines = source.splitlines()
    at = first.end_lineno if is_docstring and first is not None else 0
    return "\n".join([*lines[:at], *missing, *lines[at:]]) + "\n"


def _defined_functions(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RecordError(f"existing file is not valid Python: {exc}") from exc
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
