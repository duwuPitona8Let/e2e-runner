from pathlib import Path

import pytest

from e2e_runner.config import (
    CONFIG_TEMPLATE,
    DEFAULTS,
    ConfigError,
    find_config,
    load_config,
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "e2e.yaml"
    path.write_text(text)
    return path


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, "")) == DEFAULTS


def test_values_override_defaults(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "workers: 4\nheaded: true\nbase_url: http://x\n"))
    assert cfg["workers"] == 4
    assert cfg["headed"] is True
    assert cfg["base_url"] == "http://x"
    assert cfg["timeout"] == DEFAULTS["timeout"]


def test_init_template_is_valid_config(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, CONFIG_TEMPLATE)) == DEFAULTS


def test_numeric_string_is_coerced(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, 'retry: "2"\n'))["retry"] == 2


def test_null_value_falls_back_to_default(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, "timeout:\n"))["timeout"] == DEFAULTS["timeout"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("workers: abc\n", "'workers' must be an integer"),
        ("workers: true\n", "'workers' must be an integer"),
        ("headed: maybe\n", "'headed' must be true or false"),
        ("- a\n- b\n", "expected a mapping"),
        ("workerz: 2\n", "unknown key(s): workerz"),
        ("workers: [1\n", "invalid YAML"),
    ],
)
def test_invalid_config_raises(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert message in str(exc_info.value)


def test_find_config_walks_up_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write(tmp_path, "")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert find_config() == cfg


def test_find_config_ignores_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    found = find_config()
    # Only a stray e2e.yaml above the temp dir could be found, never one inside it.
    assert found is None or tmp_path not in found.parents
