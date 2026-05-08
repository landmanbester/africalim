"""Typer command for ``africalim export``.

Thin wrapper around :func:`africalim.core.export.export_interactions`.
ISO 8601 ``--since`` / ``--until`` strings are parsed here so the
runtime command produces actionable error messages on bad input;
:mod:`core.export` keeps datetime-typed parameters internally.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from hip_cargo import stimela_cab


def _parse_iso(value: str | None, flag: str) -> datetime | None:
    """Parse ``value`` as an ISO 8601 timestamp; raise typer.Exit on failure."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        typer.echo(
            f"Error: --{flag} value {value!r} is not a valid ISO 8601 timestamp.",
            err=True,
        )
        raise typer.Exit(code=1) from exc


@stimela_cab(name="export", info="Export logged interactions as JSONL.")
def export(
    output: Annotated[
        Path | None,
        typer.Option(help="JSONL output file (stdout if omitted)."),
    ] = None,
    consent: Annotated[
        str,
        typer.Option(help="Consent filter: opt_in (default), opt_out, unset, all."),
    ] = "opt_in",
    agent: Annotated[
        str | None,
        typer.Option(help="Filter by agent name."),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option(help="ISO 8601 inclusive lower bound on timestamp."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(help="ISO 8601 inclusive upper bound on timestamp."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(help="Max records to read from the log before filtering."),
    ] = 10_000,
) -> None:
    """Export logged interactions as JSONL."""
    from africalim.core.export import default_db_path, export_interactions

    if consent not in {"opt_in", "opt_out", "unset", "all"}:
        typer.echo(
            f"Error: --consent must be one of opt_in/opt_out/unset/all, got {consent!r}.",
            err=True,
        )
        raise typer.Exit(code=1)

    since_dt = _parse_iso(since, "since")
    until_dt = _parse_iso(until, "until")

    export_interactions(
        default_db_path(),
        output=output,
        consent=consent,  # type: ignore[arg-type]
        agent=agent,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )
