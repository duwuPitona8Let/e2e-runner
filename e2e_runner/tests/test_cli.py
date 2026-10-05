import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from e2e_runner.cli import main
from e2e_runner.config import CONFIG_FILENAME

PASSING = "def test_ok():\n    assert True\n"
FAILING = "def test_bad():\n    assert False, 'nope'\n"


@pytest.fixture(autouse=True)
def in_tmp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def invoke(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


# ── run ──────────────────────────────────────────────────────


def test_run_all_passed_exits_0_and_saves_run(fake_playwright, cli_storage, write_test_file) -> None:
    write_test_file("test_a.py", PASSING)

    result = invoke("run", "suite", "-u", "http://app", "-p", "shop")

    assert result.exit_code == 0, result.output
    (run,) = cli_storage.list_runs()
    assert (run["project_name"], run["passed"]) == ("shop", 1)


def test_run_with_failure_exits_1(fake_playwright, cli_storage, write_test_file) -> None:
    write_test_file("test_a.py", PASSING + FAILING)
    assert invoke("run", "suite").exit_code == 1


def test_run_no_save_and_json_report(fake_playwright, cli_storage, write_test_file, tmp_path) -> None:
    write_test_file("test_a.py", PASSING)

    result = invoke("run", "suite", "--no-save", "--json", "out.json")

    assert result.exit_code == 0, result.output
    assert cli_storage.list_runs() == []
    assert json.loads((tmp_path / "out.json").read_text())["passed"] == 1


def test_run_empty_suite_exits_1(fake_playwright, cli_storage, tmp_path) -> None:
    (tmp_path / "empty").mkdir()

    result = invoke("run", "empty")

    assert result.exit_code == 1
    assert "No tests found" in result.output


def test_run_import_error_exits_1_even_if_other_tests_pass(fake_playwright, cli_storage, write_test_file) -> None:
    write_test_file("test_ok.py", PASSING)
    write_test_file("test_broken.py", "def test_x(:\n")

    result = invoke("run", "suite")

    assert result.exit_code == 1
    assert "Import error" in result.output
    assert "could not be imported" in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-n", "500"], "Workers must be between 1 and 32"),
        (["-n", "0"], "Workers must be between 1 and 32"),
        (["--timeout", "10"], "Timeout must be between"),
        (["--retry", "11"], "Retry count must be between"),
        (["-u", "ftp://app"], "Invalid base-url"),
    ],
)
def test_run_rejects_invalid_options(fake_playwright, cli_storage, write_test_file, args, message) -> None:
    write_test_file("test_a.py", PASSING)

    result = invoke("run", "suite", *args)

    assert result.exit_code == 1
    assert message in result.output
    assert fake_playwright.browsers_launched == 0


def test_run_reports_bad_config(fake_playwright, cli_storage, write_test_file, tmp_path) -> None:
    write_test_file("test_a.py", PASSING)
    (tmp_path / CONFIG_FILENAME).write_text("workers: abc\n")

    result = invoke("run", "suite")

    assert result.exit_code == 1
    assert "Config error" in result.output


def test_cli_flags_override_config(fake_playwright, cli_storage, write_test_file, tmp_path) -> None:
    write_test_file("test_a.py", FAILING)
    (tmp_path / CONFIG_FILENAME).write_text("tests: suite\nretry: 2\nproject: from-yaml\n")

    invoke("run")  # retry from yaml: 1 attempt + 2 retries
    assert len(fake_playwright.contexts) == 3

    fake_playwright.contexts.clear()
    invoke("run", "--retry", "0", "-p", "from-cli")  # CLI wins over yaml
    assert len(fake_playwright.contexts) == 1
    assert {r["project_name"] for r in cli_storage.list_runs()} == {"from-yaml", "from-cli"}


# ── init / discover ──────────────────────────────────────────


def test_init_creates_config_and_refuses_to_overwrite(tmp_path) -> None:
    assert invoke("init").exit_code == 0
    assert (tmp_path / CONFIG_FILENAME).is_file()

    assert invoke("init").exit_code == 1
    assert invoke("init", "--force").exit_code == 0


def test_discover_lists_tests_and_fails_only_without_valid_tests(write_test_file, tmp_path) -> None:
    write_test_file("test_a.py", PASSING)
    ok = invoke("discover", "suite")
    assert ok.exit_code == 0
    assert "test_ok" in ok.output

    broken_dir = tmp_path / "only_broken"
    broken_dir.mkdir()
    (broken_dir / "test_b.py").write_text("def test_x(:\n")
    result = invoke("discover", "only_broken")
    assert result.exit_code == 1
    assert "Import error" in result.output


# ── projects / history / clean ───────────────────────────────


def test_projects_lifecycle(cli_storage) -> None:
    assert invoke("projects", "add", "shop", "http://shop.local", "-d", "demo").exit_code == 0
    assert invoke("projects", "add", "shop", "http://shop.local").exit_code == 1  # duplicate
    assert invoke("projects", "add", "bad", "not-a-url").exit_code == 1

    assert "shop" in invoke("projects", "list").output
    assert invoke("projects", "edit", "shop", "-u", "http://new.local").exit_code == 0
    assert cli_storage.get_project("shop").base_url == "http://new.local"

    assert invoke("projects", "remove", "shop").exit_code == 0
    assert invoke("projects", "remove", "shop").exit_code == 1


def test_project_base_url_used_when_flag_missing(fake_playwright, cli_storage, write_test_file) -> None:
    write_test_file("test_a.py", PASSING)
    invoke("projects", "add", "shop", "http://shop.local")

    invoke("run", "suite", "-p", "shop")

    assert fake_playwright.contexts[0].base_url == "http://shop.local"


def test_history_and_clean(fake_playwright, cli_storage, write_test_file) -> None:
    write_test_file("test_a.py", PASSING)
    for _ in range(3):
        invoke("run", "suite", "-p", "shop")

    assert "shop" in invoke("history").output

    result = invoke("clean", "--keep", "1", "-y")

    assert result.exit_code == 0
    assert len(cli_storage.list_runs()) == 1
