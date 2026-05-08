"""Harness layer — interaction logger.

This module provides the SQLite-backed interaction log used by
``core/runner.py``'s ``run_agent`` wrapper. Every agent invocation writes a
single :class:`InteractionRecord` row covering input, output, tool traces,
model identity, agent identity, harness version, corpus versions, consent
status, cost estimate, duration, and any error.

The schema is versioned via ``PRAGMA user_version`` and migrations are
inlined as ``(target_version, sql)`` tuples in :data:`MIGRATIONS`. The list
is **append-only** — never edit a published entry, only append new ones.

JSON-typed columns (``final_output_json``, ``tool_traces_json``,
``corpus_versions_json``, ``error_json``) are serialised at write time with
``json.dumps(..., default=str)`` so values such as ``datetime`` objects in
tool-trace payloads do not crash the logger.

The :class:`InteractionLogger` is intentionally thread-unsafe per
``sqlite3``'s default check-same-thread setting; callers run the logger on
the same thread that owns the connection. WAL mode is enabled so concurrent
readers (e.g. ``africalim export`` while an agent is mid-run) do not block
the writer.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ConsentStatus = Literal["opt_in", "opt_out", "unset"]
UploadStatus = Literal["pending", "uploaded", "skipped"]


class InteractionRecord(BaseModel):
    """One row of the ``interactions`` table.

    Field types reflect the in-memory shape callers work with; JSON columns
    are serialised at write time and parsed back on read so callers never
    deal with raw JSON strings.
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    timestamp: datetime
    agent_name: str
    agent_version: str
    harness_version: str
    model_provider: str
    model_name: str
    user_input: str
    final_output: dict[str, Any]
    tool_traces: list[dict[str, Any]]
    corpus_versions: dict[str, str]
    consent_status: ConsentStatus
    upload_status: UploadStatus
    cost_usd_estimate: float | None = None
    duration_ms: int
    error: dict[str, Any] | None = None


# Inlined migration list. Append-only: never edit a published entry.
# Each tuple is ``(target_user_version, sql)``. The runner applies any entry
# whose target is greater than the current ``PRAGMA user_version``.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            agent_version TEXT NOT NULL,
            harness_version TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            user_input TEXT NOT NULL,
            final_output_json TEXT NOT NULL,
            tool_traces_json TEXT NOT NULL,
            corpus_versions_json TEXT NOT NULL,
            consent_status TEXT NOT NULL,
            upload_status TEXT NOT NULL,
            cost_usd_estimate REAL,
            duration_ms INTEGER NOT NULL,
            error_json TEXT
        );
        CREATE INDEX idx_interactions_consent
            ON interactions(consent_status, upload_status);
        CREATE INDEX idx_interactions_agent
            ON interactions(agent_name, timestamp);
        """,
    ),
]


def _json_dumps(value: Any) -> str:
    """Serialise ``value`` with a permissive default for unusual types.

    ``default=str`` lets a stray ``datetime`` or ``Path`` survive a round
    trip without raising — the logger should never crash a live agent run
    because of an exotic value buried in a tool trace.
    """
    return json.dumps(value, default=str)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply any migrations whose target exceeds ``PRAGMA user_version``.

    Each pending migration is wrapped in a ``BEGIN ... COMMIT`` block embedded
    in the SQL itself; ``executescript`` issues an implicit ``COMMIT`` before
    running, which means we cannot start a Python-side transaction here without
    confusing it. The ``user_version`` bump is part of the same script so the
    schema and version flag move together. The list is sorted by target version
    to make the order obvious; published entries are append-only.
    """
    cur = conn.execute("PRAGMA user_version")
    current = int(cur.fetchone()[0])
    for target, sql in sorted(MIGRATIONS, key=lambda m: m[0]):
        if target <= current:
            continue
        # ``PRAGMA user_version = ?`` does not accept parameter binding; the
        # value is an int we control, so f-string substitution is safe.
        script = f"BEGIN;\n{sql}\nPRAGMA user_version = {int(target)};\nCOMMIT;"
        try:
            conn.executescript(script)
        except Exception:
            # ``executescript`` rolls back automatically on error in modern
            # sqlite3, but be explicit in case the script left a transaction
            # open. ``ROLLBACK`` is a no-op when no transaction is active.
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        current = target


class InteractionLogger:
    """SQLite-backed append-mostly log of agent interactions.

    The connection is opened with ``isolation_level=None`` so we manage
    transactions explicitly; WAL mode is enabled so readers (e.g. an export
    command running concurrently with a live agent) don't block writers.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(
            self._db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        _apply_migrations(self._conn)

    # -- internal helpers --------------------------------------------------- #

    @property
    def _c(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("InteractionLogger has been closed")
        return self._conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> InteractionRecord:
        """Convert a ``sqlite3.Row`` into an :class:`InteractionRecord`."""
        error_json = row["error_json"]
        return InteractionRecord(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            agent_name=row["agent_name"],
            agent_version=row["agent_version"],
            harness_version=row["harness_version"],
            model_provider=row["model_provider"],
            model_name=row["model_name"],
            user_input=row["user_input"],
            final_output=json.loads(row["final_output_json"]),
            tool_traces=json.loads(row["tool_traces_json"]),
            corpus_versions=json.loads(row["corpus_versions_json"]),
            consent_status=row["consent_status"],
            upload_status=row["upload_status"],
            cost_usd_estimate=row["cost_usd_estimate"],
            duration_ms=row["duration_ms"],
            error=json.loads(error_json) if error_json is not None else None,
        )

    # -- public API --------------------------------------------------------- #

    def log_interaction(self, record: InteractionRecord) -> int:
        """Insert ``record`` and return the new row's ``id``.

        The ``id`` field on the input record is ignored; SQLite assigns it.
        """
        cursor = self._c.execute(
            """
            INSERT INTO interactions (
                timestamp,
                agent_name,
                agent_version,
                harness_version,
                model_provider,
                model_name,
                user_input,
                final_output_json,
                tool_traces_json,
                corpus_versions_json,
                consent_status,
                upload_status,
                cost_usd_estimate,
                duration_ms,
                error_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.timestamp.isoformat(),
                record.agent_name,
                record.agent_version,
                record.harness_version,
                record.model_provider,
                record.model_name,
                record.user_input,
                _json_dumps(record.final_output),
                _json_dumps(record.tool_traces),
                _json_dumps(record.corpus_versions),
                record.consent_status,
                record.upload_status,
                record.cost_usd_estimate,
                record.duration_ms,
                _json_dumps(record.error) if record.error is not None else None,
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:  # pragma: no cover - sqlite3 always sets this on INSERT
            raise RuntimeError("sqlite3 did not return a lastrowid for INSERT")
        return int(row_id)

    def get_interaction(self, row_id: int) -> InteractionRecord | None:
        """Return the row with ``id == row_id``, or ``None`` if absent."""
        row = self._c.execute(
            "SELECT * FROM interactions WHERE id = ?",
            (row_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_interactions(
        self,
        agent: str | None = None,
        consent_status: ConsentStatus | None = None,
        limit: int = 100,
    ) -> list[InteractionRecord]:
        """Return up to ``limit`` interactions, newest first.

        ``agent`` and ``consent_status`` are optional equality filters.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if agent is not None:
            clauses.append("agent_name = ?")
            params.append(agent)
        if consent_status is not None:
            clauses.append("consent_status = ?")
            params.append(consent_status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        rows = self._c.execute(
            f"SELECT * FROM interactions {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def mark_uploaded(self, row_ids: list[int]) -> None:
        """Set ``upload_status='uploaded'`` for each id in ``row_ids``.

        A no-op when ``row_ids`` is empty. Idempotent: running it twice
        leaves the rows in the same state.
        """
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        self._c.execute(
            f"UPDATE interactions SET upload_status = 'uploaded' WHERE id IN ({placeholders})",
            list(row_ids),
        )

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- context-manager plumbing ------------------------------------------ #

    def __enter__(self) -> InteractionLogger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
