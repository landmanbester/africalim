"""Unit tests for :mod:`africalim.utils.user_config`."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils.user_config import (
    InvalidConfigValueError,
    UnknownConfigKeyError,
    UserConfig,
    default_user_config_path,
    load_user_config,
    save_user_config,
    set_dotted,
)


def _read_raw(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    config = load_user_config(tmp_path / "config.toml")
    assert isinstance(config, UserConfig)
    assert config.consent.status == "unset"
    assert config.consent.prompt_shown is False
    assert config.model.default_provider == "anthropic"
    assert config.model.default_model == "claude-sonnet-4-6"
    assert config.upload.batch_size == 50


def test_round_trip_preserves_known_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = UserConfig()
    config.consent.status = "opt_in"
    config.model.default_model = "claude-haiku-4-5"
    save_user_config(config, path)

    reloaded = load_user_config(path)
    assert reloaded.consent.status == "opt_in"
    assert reloaded.model.default_model == "claude-haiku-4-5"


def test_save_preserves_unknown_top_level_section(tmp_path: Path) -> None:
    """A foreign writer's [other] section survives a round-trip."""
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[other]\nfoo = "bar"\n', encoding="utf-8")

    config = load_user_config(path)
    config.consent.status = "opt_out"
    save_user_config(config, path)

    on_disk = _read_raw(path)
    assert on_disk["other"]["foo"] == "bar"
    assert on_disk["consent"]["status"] == "opt_out"


def test_default_user_config_path_matches_consent_module() -> None:
    from africalim.utils.consent import default_config_path

    assert default_user_config_path() == default_config_path()


def test_set_dotted_persists_consent_status(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = set_dotted(path, "consent.status", "opt_in")
    assert config.consent.status == "opt_in"

    reloaded = load_user_config(path)
    assert reloaded.consent.status == "opt_in"


def test_set_dotted_persists_model_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = set_dotted(path, "model.default_model", "claude-haiku-4-5")
    assert config.model.default_model == "claude-haiku-4-5"
    reloaded = load_user_config(path)
    assert reloaded.model.default_model == "claude-haiku-4-5"


def test_set_dotted_rejects_unknown_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    with pytest.raises(UnknownConfigKeyError):
        set_dotted(path, "bogus.value", "x")


def test_set_dotted_allows_pre_existing_unknown_section(tmp_path: Path) -> None:
    """If [other] is already on disk, set_dotted will write to it."""
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[other]\nfoo = "bar"\n', encoding="utf-8")

    set_dotted(path, "other.foo", "baz")
    on_disk = _read_raw(path)
    assert on_disk["other"]["foo"] == "baz"


def test_set_dotted_rejects_invalid_consent_status(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    with pytest.raises(InvalidConfigValueError):
        set_dotted(path, "consent.status", "garbage")


def test_set_dotted_rejects_malformed_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    with pytest.raises(InvalidConfigValueError):
        set_dotted(path, "nodot", "x")
    with pytest.raises(InvalidConfigValueError):
        set_dotted(path, "too.many.parts", "x")
    with pytest.raises(InvalidConfigValueError):
        set_dotted(path, "consent.", "x")
