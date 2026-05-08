"""Harness layer — implementation backing ``africalim export``.

Pure function; no Typer. The CLI wrapper in
:mod:`africalim.cli.export` lazy-imports :func:`export_interactions`
and threads CLI flags through. Tests exercise this module directly.

Export semantics:

- **Default consent filter is ``opt_in``** per the spec — what the
  user has explicitly marked as shareable. Pass ``consent="all"`` to
  drop the filter and dump everything.
- ``agent``/``since``/``until`` filters are applied in Python after
  the SQL query. ``InteractionLogger.list_interactions`` already
  supports ``agent`` and ``consent_status``; adding time-window
  filtering at this layer means we don't have to evolve the logger's
  public API for an export-only feature.
- Output is JSONL — one
  :meth:`InteractionRecord.model_dump_json` per line — so the file
  streams cleanly through ``jq`` and friends.

The cab-target shim :func:`export` sits at the bottom of this module
because hip-cargo's cab-generator rewrites ``cli/export.py`` to
``africalim.core.export.export``. Direct Stimela cab invocations land
on the shim; the runtime CLI goes through :mod:`africalim.cli.export`.
Both paths funnel through :func:`export_interactions`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import IO, Iterable, Literal

import platformdirs

from africalim.utils.logger import (
    ConsentStatus,
    InteractionLogger,
    InteractionRecord,
)

ConsentFilter = Literal["opt_in", "opt_out", "unset", "all"]


def default_db_path() -> Path:
    """Return the platform-default interaction-log SQLite path."""
    return platformdirs.user_data_path("africalim") / "interactions.db"


def _filter_by_time_and_agent(
    records: Iterable[InteractionRecord],
    *,
    agent: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Iterable[InteractionRecord]:
    """Apply Python-side filters that aren't handled by the SQL query."""
    for record in records:
        if agent is not None and record.agent_name != agent:
            continue
        if since is not None and record.timestamp < since:
            continue
        if until is not None and record.timestamp > until:
            continue
        yield record


def export_interactions(
    db_path: Path,
    output: Path | None = None,
    *,
    consent: ConsentFilter = "opt_in",
    agent: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 10_000,
) -> int:
    """Stream matching interactions as JSONL.

    Args:
        db_path: SQLite database file to read from.
        output: Path to write JSONL to. ``None`` writes to ``stdout``.
        consent: Consent filter. ``"all"`` drops the filter; anything
            else is applied as an equality match on ``consent_status``.
        agent: Optional ``agent_name`` equality filter.
        since: Optional inclusive lower bound on ``timestamp``.
        until: Optional inclusive upper bound on ``timestamp``.
        limit: Max records to consider before applying the
            Python-side ``agent``/``since``/``until`` filters.

    Returns:
        The number of records written.
    """
    consent_filter: ConsentStatus | None
    consent_filter = None if consent == "all" else consent

    with InteractionLogger(db_path) as logger:
        records = logger.list_interactions(
            agent=agent,
            consent_status=consent_filter,
            limit=limit,
        )

    filtered = _filter_by_time_and_agent(
        records,
        agent=agent,
        since=since,
        until=until,
    )

    if output is None:
        return _write_stream(filtered, sys.stdout)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        return _write_stream(filtered, fh)


def _write_stream(records: Iterable[InteractionRecord], fh: IO[str]) -> int:
    """Write ``records`` as JSONL to ``fh``; return how many were written."""
    written = 0
    for record in records:
        fh.write(record.model_dump_json())
        fh.write("\n")
        written += 1
    return written


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string; ``None`` passes through."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def export(
    output: Path | None = None,
    consent: str = "opt_in",
    agent: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 10_000,
    db_path: Path | None = None,
) -> int:
    """Stimela-cab entry point: export logged interactions as JSONL.

    Mirrors the CLI command's signature. ``since`` / ``until`` accept
    ISO 8601 strings; ``db_path`` defaults to the platform path so the
    cab can be invoked without arguments.
    """
    target_db = db_path if db_path is not None else default_db_path()
    return export_interactions(
        target_db,
        output=output,
        consent=consent,  # type: ignore[arg-type]
        agent=agent,
        since=_parse_iso(since),
        until=_parse_iso(until),
        limit=limit,
    )
