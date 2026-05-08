"""Smoke tests for the top-level Typer app."""

from __future__ import annotations

from typer.testing import CliRunner

from africalim.cli import app


def test_help_lists_all_v0_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("onboard", "janskie", "config", "export"):
        assert command in result.stdout, result.stdout


def test_config_help_lists_subcommands() -> None:
    result = CliRunner().invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    for sub in ("show", "set", "path"):
        assert sub in result.stdout, result.stdout


def test_export_help_documents_consent_default() -> None:
    result = CliRunner().invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "opt_in" in result.stdout
