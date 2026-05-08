"""CLI tests for ``africalim config``.

The CLI commands resolve their config-file path via
:func:`africalim.utils.user_config.default_user_config_path`, which calls
:func:`platformdirs.user_config_path`. Tests monkeypatch
``platformdirs.user_config_path`` to redirect the user-config dir into
``tmp_path`` so each test runs against a private file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from africalim.cli import app


@pytest.fixture
def isolated_config_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect platform-wide user-config lookups into ``tmp_path``."""

    def _user_config_path(*_args: object, **_kwargs: object) -> Path:
        return tmp_path

    # ``africalim.utils.consent.default_config_path`` calls
    # ``platformdirs.user_config_path("africalim")`` at lookup time, so
    # patching the attribute on the imported module is enough.
    import africalim.utils.consent as consent_module

    monkeypatch.setattr(
        consent_module.platformdirs,
        "user_config_path",
        _user_config_path,
    )
    return tmp_path


def test_config_path_prints_resolved_file(isolated_config_dir: Path) -> None:
    result = CliRunner().invoke(app, ["config", "path"])
    assert result.exit_code == 0, result.stdout
    expected = str(isolated_config_dir / "config.toml")
    assert expected in result.stdout


def test_config_show_prints_defaults(isolated_config_dir: Path) -> None:
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.stdout
    assert "claude-sonnet-4-6" in result.stdout
    assert "[consent]" in result.stdout


def test_config_set_persists_and_show_reflects(isolated_config_dir: Path) -> None:
    runner = CliRunner()
    set_result = runner.invoke(
        app,
        ["config", "set", "--key", "consent.status", "--value", "opt_in"],
    )
    assert set_result.exit_code == 0, set_result.stdout

    show_result = runner.invoke(app, ["config", "show"])
    assert show_result.exit_code == 0, show_result.stdout
    assert 'status = "opt_in"' in show_result.stdout


def test_config_set_rejects_invalid_value(isolated_config_dir: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["config", "set", "--key", "consent.status", "--value", "garbage"],
    )
    assert result.exit_code == 1


def test_config_set_rejects_unknown_section(isolated_config_dir: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["config", "set", "--key", "nope.field", "--value", "x"],
    )
    assert result.exit_code == 1
