import sys

from e2e_runner.discovery import DiscoveryError, discover_tests, get_callable


def test_finds_only_test_functions_in_test_files(write_test_file, tmp_path) -> None:
    write_test_file(
        "test_sample.py",
        """
        def test_one(): pass
        def test_two(page): pass
        def helper(): pass
        """,
    )
    write_test_file("helpers.py", "def test_ignored(): pass\n")

    tests = discover_tests(tmp_path / "suite")

    assert [t.function_name for t in tests] == ["test_one", "test_two"]
    assert tests[0].name == "test_sample::test_one"


def test_filter_is_case_insensitive_substring(write_test_file, tmp_path) -> None:
    write_test_file("test_auth.py", "def test_Login(): pass\ndef test_logout(): pass\ndef test_cart(): pass\n")

    names = [t.function_name for t in discover_tests(tmp_path / "suite", "LOG")]

    assert names == ["test_Login", "test_logout"]


def test_accepts_single_file_path(write_test_file) -> None:
    path = write_test_file("test_single.py", "def test_a(): pass\n")
    assert [t.function_name for t in discover_tests(path)] == ["test_a"]


def test_same_file_names_in_different_dirs_do_not_collide(write_test_file, tmp_path) -> None:
    write_test_file("a/test_same.py", "def test_x(): return 'a'\n")
    write_test_file("b/test_same.py", "def test_x(): return 'b'\n")

    tests = discover_tests(tmp_path / "suite")

    assert sorted(get_callable(t)() for t in tests) == ["a", "b"]


def test_import_error_is_collected_not_raised(write_test_file, tmp_path) -> None:
    write_test_file("test_ok.py", "def test_ok(): pass\n")
    write_test_file("test_broken.py", "def test_x(:\n    pass\n")
    errors: list[DiscoveryError] = []

    tests = discover_tests(tmp_path / "suite", errors=errors)

    assert [t.function_name for t in tests] == ["test_ok"]
    assert len(errors) == 1
    assert errors[0].file.name == "test_broken.py"
    assert isinstance(errors[0].cause, SyntaxError)


def test_broken_module_is_removed_from_sys_modules(write_test_file, tmp_path) -> None:
    write_test_file("test_boom.py", "raise RuntimeError('boom')\n")
    discover_tests(tmp_path / "suite", errors=[])
    assert not [name for name in sys.modules if "test_boom" in name]


def test_get_callable_reloads_missing_module(write_test_file, tmp_path) -> None:
    write_test_file("test_reload.py", "def test_r(): return 42\n")
    (test,) = discover_tests(tmp_path / "suite")
    del sys.modules[test.module_name]

    assert get_callable(test)() == 42
