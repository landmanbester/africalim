"""Typer wrapper for ``africalim config show``."""

from __future__ import annotations

from hip_cargo import stimela_cab


@stimela_cab(name="config_show", info="Print the current user config as TOML.")
def config_show() -> None:
    """Print the current user config as TOML."""
    from africalim.core.config_show import config_show as _impl

    _impl()
