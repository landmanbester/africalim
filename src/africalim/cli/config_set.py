"""Typer wrapper for ``africalim config set``."""

from __future__ import annotations

from typing import Annotated

import typer
from hip_cargo import stimela_cab


@stimela_cab(
    name="config_set",
    info="Set a config value via dotted key (e.g. consent.status opt_in).",
)
def config_set(
    key: Annotated[
        str,
        typer.Option(..., help="Dotted key, e.g. 'consent.status'."),
    ],
    value: Annotated[
        str,
        typer.Option(..., help="Value to assign. Validated against the schema."),
    ],
) -> None:
    """Set a config value via dotted key (e.g. consent.status opt_in)."""
    from africalim.core.config_set import config_set as _impl
    from africalim.utils.user_config import (
        InvalidConfigValueError,
        UnknownConfigKeyError,
    )

    try:
        _impl(key, value)
    except UnknownConfigKeyError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidConfigValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Set {key} = {value}")
