"""Typer wrapper for ``africalim config path``."""

from __future__ import annotations

from hip_cargo import stimela_cab


@stimela_cab(name="config_path", info="Print the path of the user-config file.")
def config_path() -> None:
    """Print the path of the user-config file."""
    from africalim.core.config_path import config_path as _impl

    _impl()
