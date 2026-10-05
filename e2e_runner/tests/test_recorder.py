import ast
from pathlib import Path

import pytest
from click.testing import CliRunner

from e2e_runner import recorder
from e2e_runner.cli import main
from e2e_runner.discovery import discover_tests
from e2e_runner.recorder import (
    RecordError,
    default_test_name,
    extract_test_body,
    relativize_urls,
    write_test,
)

# What `playwright codegen --target python-pytest` writes for a login on demo_app.
CODEGEN_LOGIN = '''import re
from playwright.sync_api import Page, expect


def test_example(page: Page) -> None:
    page.goto("http://localhost:8080/")
    page.goto("http://localhost:8080/login")
    page.locator("#username").fill("admin")
    page.locator("#password").fill("password123")
    page.get_by_role("button", name="Войти").click()
    expect(page.locator("h1")).to_contain_text("Личный кабинет")
    expect(page).to_have_url(re.compile(r".*/dashboard"))
'''

CODEGEN_CLICK_ONLY = '''from playwright.sync_api import Page


def test_example(page: Page) -> None:
    page.goto("http://localhost:8080/")
    page.get_by_role("link", name="Товары").first.click()
'''


def test_extract_body_drops_signature_and_dedents() -> None:
    body = extract_test_body(CODEGEN_LOGIN)
    assert body.splitlines()[0] == 'page.goto("http://localhost:8080/")'
    assert "def " not in body
    assert body.splitlines()[-1].startswith("expect(page).to_have_url")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("x = 1\n", "no test function"),
        ("def test_example(page):\n    pass\n", "nothing was recorded"),
        ("def test_example(:\n", "not valid Python"),
    ],
)
def test_extract_body_errors(source: str, message: str) -> None:
    with pytest.raises(RecordError, match=message):
        extract_test_body(source)


def test_relativize_only_same_origin_goto() -> None:
    body = (
        'page.goto("http://localhost:8080")\n'
        'page.goto("http://localhost:8080/login?next=/cart")\n'
        "page1.goto('http://localhost:8080/items/1')\n"
        'page.goto("https://example.com/other")\n'
        'expect(page).to_have_url("http://localhost:8080/dashboard")\n'
    )

    result = relativize_urls(body, "http://localhost:8080").splitlines()

    assert result == [
        'page.goto("/")',
        'page.goto("/login?next=/cart")',
        "page1.goto('/items/1')",
        'page.goto("https://example.com/other")',
        'expect(page).to_have_url("http://localhost:8080/dashboard")',
    ]


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [("test_login.py", "test_login"), ("checkout-flow.py", "test_checkout_flow")],
)
def test_default_test_name(file_name: str, expected: str) -> None:
    assert default_test_name(Path(file_name)) == expected


def test_write_new_file_is_valid_and_discoverable(tmp_path: Path) -> None:
    out = tmp_path / "tests" / "test_login.py"
    body = relativize_urls(extract_test_body(CODEGEN_LOGIN), "http://localhost:8080")

    write_test(out, "test_login", body, recorded_from="http://localhost:8080/")

    source = out.read_text(encoding="utf-8")
    ast.parse(source)
    assert "import re\n" in source
    assert "from playwright.sync_api import Page, expect\n" in source
    assert 'def test_login(page: Page) -> None:\n    page.goto("/")' in source
    assert "e2e run" in source  # usage hint in the docstring
    assert [t.function_name for t in discover_tests(out)] == ["test_login"]


def test_write_minimal_imports(tmp_path: Path) -> None:
    out = tmp_path / "test_nav.py"
    write_test(out, "test_nav", extract_test_body(CODEGEN_CLICK_ONLY), "http://localhost:8080")

    source = out.read_text(encoding="utf-8")
    assert "import re" not in source
    assert "from playwright.sync_api import Page\n" in source


def test_append_adds_function_and_missing_imports(tmp_path: Path) -> None:
    out = tmp_path / "test_flows.py"
    write_test(out, "test_nav", extract_test_body(CODEGEN_CLICK_ONLY), "http://localhost:8080")

    write_test(out, "test_login", extract_test_body(CODEGEN_LOGIN), "http://localhost:8080")

    source = out.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)] == ["test_nav", "test_login"]
    assert "import re" in source
    assert "expect" in source.split("def test_nav")[0]  # import added above the functions
    assert isinstance(tree.body[0], ast.Expr)  # module docstring stays first


def test_append_refuses_duplicate_name(tmp_path: Path) -> None:
    out = tmp_path / "test_x.py"
    write_test(out, "test_x", "page.goto('/')", "http://a")
    with pytest.raises(RecordError, match="already defines"):
        write_test(out, "test_x", "page.goto('/')", "http://a")


@pytest.mark.parametrize("name", ["login", "test-login", "test login"])
def test_invalid_names_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(RecordError, match="invalid test name"):
        write_test(tmp_path / "test_x.py", name, "page.goto('/')", "http://a")


# ── CLI ──────────────────────────────────────────────────────


@pytest.fixture
def fake_codegen(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the interactive codegen with canned output; records the URLs it was opened on."""
    calls: list[str] = []

    def _fake(url: str) -> str:
        calls.append(url)
        return CODEGEN_LOGIN

    monkeypatch.setattr(recorder, "_run_codegen", _fake)
    return calls


def test_cli_record_creates_then_appends_with_unique_names(fake_codegen, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    first = runner.invoke(main, ["record", "http://localhost:8080", "-o", "tests/test_login.py"])
    second = runner.invoke(main, ["record", "http://localhost:8080", "-o", "tests/test_login.py"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    names = [t.function_name for t in discover_tests(tmp_path / "tests")]
    assert names == ["test_login", "test_login_2"]
    assert fake_codegen == ["http://localhost:8080", "http://localhost:8080"]


def test_cli_record_uses_config_url_and_tests_dir(fake_codegen, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "e2e.yaml").write_text("base_url: http://localhost:8080\ntests: e2e_tests\n")

    result = CliRunner().invoke(main, ["record"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "e2e_tests" / "test_recorded.py").is_file()
    assert fake_codegen == ["http://localhost:8080"]


def test_cli_record_without_url_fails(fake_codegen, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["record"])

    assert result.exit_code == 1
    assert "No URL" in result.output
    assert fake_codegen == []


def test_cli_record_reports_codegen_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def _fail(url: str) -> str:
        raise RecordError("playwright codegen exited with code 1 without saving a recording")

    monkeypatch.setattr(recorder, "_run_codegen", _fail)

    result = CliRunner().invoke(main, ["record", "http://localhost:8080"])

    assert result.exit_code == 1
    assert "Recording failed" in result.output
    assert not (tmp_path / "tests").exists()
