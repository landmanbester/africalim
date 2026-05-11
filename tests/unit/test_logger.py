"""Unit tests for ``africalim.utils.logger``.

Sync tests; no asyncio. Each test uses ``tmp_path`` for an isolated SQLite
file so cases never interfere with one another.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from africalim.utils.logger import (
    MIGRATIONS,
    InteractionLogger,
    InteractionRecord,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_record(
    *,
    timestamp: datetime | None = None,
    agent_name: str = "janskie",
    agent_version: str = "0.1.0",
    harness_version: str = "0.1.0",
    model_provider: str = "anthropic",
    model_name: str = "claude-sonnet-4-6",
    user_input: str = "what does pfb-imaging do?",
    final_output: dict[str, Any] | None = None,
    tool_traces: list[dict[str, Any]] | None = None,
    corpus_versions: dict[str, str] | None = None,
    consent_status: str = "opt_in",
    upload_status: str = "pending",
    cost_usd_estimate: float | None = 0.0123,
    duration_ms: int = 4567,
    error: dict[str, Any] | None = None,
) -> InteractionRecord:
    return InteractionRecord(
        timestamp=timestamp if timestamp is not None else datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc),
        agent_name=agent_name,
        agent_version=agent_version,
        harness_version=harness_version,
        model_provider=model_provider,
        model_name=model_name,
        user_input=user_input,
        final_output=final_output if final_output is not None else {"answer": "ok", "sources": []},
        tool_traces=tool_traces if tool_traces is not None else [{"tool": "search_codebase", "args": {"q": "x"}}],
        corpus_versions=corpus_versions if corpus_versions is not None else {"pfb-imaging": "deadbeef"},
        consent_status=consent_status,  # type: ignore[arg-type]
        upload_status=upload_status,  # type: ignore[arg-type]
        cost_usd_estimate=cost_usd_estimate,
        duration_ms=duration_ms,
        error=error,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_init_creates_parent_directory(tmp_path: Path) -> None:
    """The logger mkdirs the parent path so the caller doesn't have to."""
    db_path = tmp_path / "nested" / "subdir" / "interactions.db"
    assert not db_path.parent.exists()
    logger = InteractionLogger(db_path)
    try:
        assert db_path.parent.is_dir()
        assert db_path.is_file()
    finally:
        logger.close()


def test_round_trip_via_get_interaction(tmp_path: Path) -> None:
    """Inserting a record and fetching by id returns an equal record."""
    db_path = tmp_path / "interactions.db"
    record = _make_record()
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        assert isinstance(row_id, int) and row_id > 0
        fetched = logger.get_interaction(row_id)

    assert fetched is not None
    assert fetched.id == row_id
    # Compare modulo the auto-assigned id.
    expected = record.model_copy(update={"id": row_id})
    assert fetched == expected


def test_get_interaction_missing_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path) as logger:
        assert logger.get_interaction(9999) is None


def test_migration_runs_once_user_version_set(tmp_path: Path) -> None:
    """Reopening the DB does not re-run migrations and user_version stays at 1."""
    db_path = tmp_path / "interactions.db"
    expected_version = max(target for target, _ in MIGRATIONS)

    logger = InteractionLogger(db_path)
    logger.close()
    # Reopen — must not raise even though tables already exist.
    logger = InteractionLogger(db_path)
    try:
        # Inspect via a fresh connection to avoid relying on internals.
        with sqlite3.connect(db_path) as raw:
            (version,) = raw.execute("PRAGMA user_version").fetchone()
        assert version == expected_version == 1
    finally:
        logger.close()


def test_indexes_exist(tmp_path: Path) -> None:
    """The two indexes from the schema spec are present after migration."""
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path):
        with sqlite3.connect(db_path) as raw:
            rows = raw.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'interactions'"
            ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_interactions_consent" in names
    assert "idx_interactions_agent" in names


def test_list_interactions_orders_newest_first(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    base = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    with InteractionLogger(db_path) as logger:
        ids = [
            logger.log_interaction(_make_record(timestamp=base + timedelta(hours=i), user_input=f"q{i}"))
            for i in range(3)
        ]
        listed = logger.list_interactions()
    assert [r.user_input for r in listed] == ["q2", "q1", "q0"]
    assert [r.id for r in listed] == [ids[2], ids[1], ids[0]]


def test_list_interactions_filters_by_agent_and_consent(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path) as logger:
        logger.log_interaction(_make_record(agent_name="janskie", consent_status="opt_in"))
        logger.log_interaction(_make_record(agent_name="janskie", consent_status="opt_out"))
        logger.log_interaction(_make_record(agent_name="other", consent_status="opt_in"))

        only_janskie = logger.list_interactions(agent="janskie")
        assert len(only_janskie) == 2
        assert all(r.agent_name == "janskie" for r in only_janskie)

        only_opt_in = logger.list_interactions(consent_status="opt_in")
        assert len(only_opt_in) == 2
        assert all(r.consent_status == "opt_in" for r in only_opt_in)

        narrow = logger.list_interactions(agent="janskie", consent_status="opt_in")
        assert len(narrow) == 1
        assert narrow[0].agent_name == "janskie"
        assert narrow[0].consent_status == "opt_in"


def test_list_interactions_honours_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    base = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    with InteractionLogger(db_path) as logger:
        for i in range(5):
            logger.log_interaction(_make_record(timestamp=base + timedelta(minutes=i)))
        listed = logger.list_interactions(limit=2)
    assert len(listed) == 2


def test_mark_uploaded_updates_only_targeted_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path) as logger:
        ids = [logger.log_interaction(_make_record()) for _ in range(3)]
        target = [ids[0], ids[2]]

        logger.mark_uploaded(target)

        for row_id in target:
            rec = logger.get_interaction(row_id)
            assert rec is not None
            assert rec.upload_status == "uploaded"

        untouched = logger.get_interaction(ids[1])
        assert untouched is not None
        assert untouched.upload_status == "pending"

        # Idempotent: running it again leaves the rows in the same state.
        logger.mark_uploaded(target)
        for row_id in target:
            rec = logger.get_interaction(row_id)
            assert rec is not None
            assert rec.upload_status == "uploaded"


def test_mark_uploaded_with_empty_list_is_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(_make_record())
        logger.mark_uploaded([])
        rec = logger.get_interaction(row_id)
    assert rec is not None
    assert rec.upload_status == "pending"


def test_json_fields_round_trip_with_datetime_in_tool_traces(tmp_path: Path) -> None:
    """A ``datetime`` buried in tool traces must not crash the writer.

    JSON columns are dumped with ``default=str``, so the value comes back as
    a string on read — this is acceptable; the contract is "no crashes".
    """
    db_path = tmp_path / "interactions.db"
    started = datetime(2026, 5, 8, 12, 30, 45, tzinfo=timezone.utc)
    record = _make_record(
        tool_traces=[
            {
                "tool": "search_codebase",
                "args": {"q": "deconvolve"},
                "started_at": started,
                "result": {"hits": 3},
            }
        ],
    )
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        fetched = logger.get_interaction(row_id)

    assert fetched is not None
    assert len(fetched.tool_traces) == 1
    trace = fetched.tool_traces[0]
    assert trace["tool"] == "search_codebase"
    # ``default=str`` stringifies the datetime; verify it survives unchanged.
    assert trace["started_at"] == str(started)
    assert trace["result"] == {"hits": 3}


def test_error_field_populated_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    err = {"type": "ToolError", "message": "boom", "trace": ["a", "b"]}
    record = _make_record(error=err)
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        fetched = logger.get_interaction(row_id)
    assert fetched is not None
    assert fetched.error == err


def test_error_field_none_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    record = _make_record(error=None)
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        fetched = logger.get_interaction(row_id)
        # Confirm via the raw column too; we want NULL on disk, not "null".
        with sqlite3.connect(db_path) as raw:
            (raw_error,) = raw.execute("SELECT error_json FROM interactions WHERE id = ?", (row_id,)).fetchone()
    assert fetched is not None
    assert fetched.error is None
    assert raw_error is None


def test_cost_usd_estimate_nullable_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    record = _make_record(cost_usd_estimate=None)
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        fetched = logger.get_interaction(row_id)
    assert fetched is not None
    assert fetched.cost_usd_estimate is None


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    """After ``__exit__`` the logger must not accept new operations."""
    db_path = tmp_path / "interactions.db"
    with InteractionLogger(db_path) as logger:
        logger.log_interaction(_make_record())
    with pytest.raises(RuntimeError, match="closed"):
        logger.log_interaction(_make_record())


def test_close_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "interactions.db"
    logger = InteractionLogger(db_path)
    logger.close()
    logger.close()  # Must not raise.


def test_durability_across_separate_logger_instances(tmp_path: Path) -> None:
    """Records survive close/reopen on the same DB file."""
    db_path = tmp_path / "interactions.db"

    record_a = _make_record(user_input="first")
    with InteractionLogger(db_path) as logger:
        id_a = logger.log_interaction(record_a)

    record_b = _make_record(user_input="second")
    with InteractionLogger(db_path) as logger:
        id_b = logger.log_interaction(record_b)
        all_recs = logger.list_interactions()

    assert id_a != id_b
    user_inputs = {r.user_input for r in all_recs}
    assert user_inputs == {"first", "second"}


def test_timestamp_stored_as_iso_8601(tmp_path: Path) -> None:
    """Spec §4.1.2: timestamp column is ISO 8601 text."""
    db_path = tmp_path / "interactions.db"
    ts = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
    record = _make_record(timestamp=ts)
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        with sqlite3.connect(db_path) as raw:
            (raw_ts,) = raw.execute("SELECT timestamp FROM interactions WHERE id = ?", (row_id,)).fetchone()
    assert raw_ts == ts.isoformat()
    # And the parsed-back value equals the original.
    with InteractionLogger(db_path) as logger:
        fetched = logger.get_interaction(row_id)
    assert fetched is not None
    assert fetched.timestamp == ts


def test_migration_failure_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad migration SQL must surface the sqlite error rather than silently succeed."""
    from africalim.utils import logger as logger_mod

    bad: list[tuple[int, str]] = [(99, "CREATE TABLE __bogus__ (NOT VALID SQL);")]
    monkeypatch.setattr(logger_mod, "MIGRATIONS", bad)

    db_path = tmp_path / "interactions.db"
    with pytest.raises(sqlite3.DatabaseError):
        InteractionLogger(db_path)


def test_json_columns_serialised_at_write_time(tmp_path: Path) -> None:
    """Smoke-check the on-disk shape of the JSON columns."""
    db_path = tmp_path / "interactions.db"
    record = _make_record(
        final_output={"answer": "yes", "sources": [{"repo": "x"}]},
        corpus_versions={"pfb-imaging": "abc123", "QuartiCal": "def456"},
    )
    with InteractionLogger(db_path) as logger:
        row_id = logger.log_interaction(record)
        with sqlite3.connect(db_path) as raw:
            row = raw.execute(
                "SELECT final_output_json, tool_traces_json, corpus_versions_json FROM interactions WHERE id = ?",
                (row_id,),
            ).fetchone()
    final_output_json, tool_traces_json, corpus_versions_json = row
    assert json.loads(final_output_json) == record.final_output
    assert json.loads(tool_traces_json) == record.tool_traces
    assert json.loads(corpus_versions_json) == record.corpus_versions
