"""Unit tests for :mod:`africalim.core.export`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from africalim.core.export import (
    default_db_path,
    export_interactions,
)
from africalim.utils.logger import InteractionLogger, InteractionRecord


def _record(
    *,
    agent: str = "janskie",
    consent: str = "opt_in",
    timestamp: datetime | None = None,
    user_input: str = "hello?",
) -> InteractionRecord:
    return InteractionRecord(
        timestamp=timestamp or datetime.now(timezone.utc),
        agent_name=agent,
        agent_version="0.1.0-test",
        harness_version="0.1.0-test",
        model_provider="anthropic",
        model_name="claude-sonnet-4-6",
        user_input=user_input,
        final_output={"answer": "hi"},
        tool_traces=[],
        corpus_versions={},
        consent_status=consent,  # type: ignore[arg-type]
        upload_status="pending" if consent == "opt_in" else "skipped",
        cost_usd_estimate=None,
        duration_ms=1,
        error=None,
    )


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """Create a SQLite DB seeded with one record per consent status."""
    db = tmp_path / "interactions.db"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with InteractionLogger(db) as logger:
        logger.log_interaction(_record(consent="opt_in", timestamp=base))
        logger.log_interaction(_record(consent="opt_out", timestamp=base + timedelta(hours=1)))
        logger.log_interaction(_record(consent="unset", timestamp=base + timedelta(hours=2)))
    return db


def test_export_default_consent_filter_is_opt_in(
    seeded_db: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.jsonl"
    written = export_interactions(seeded_db, out)
    assert written == 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["consent_status"] == "opt_in"


def test_export_consent_all_dumps_everything(
    seeded_db: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.jsonl"
    written = export_interactions(seeded_db, out, consent="all")
    assert written == 3


def test_export_writes_to_stdout_when_output_omitted(
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written = export_interactions(seeded_db, output=None, consent="all")
    captured = capsys.readouterr()
    assert written == 3
    assert len(captured.out.strip().splitlines()) == 3


def test_export_filters_by_agent(seeded_db: Path, tmp_path: Path) -> None:
    # Add an extra record for a different agent.
    with InteractionLogger(seeded_db) as logger:
        logger.log_interaction(_record(agent="other", consent="opt_in"))

    out = tmp_path / "out.jsonl"
    written = export_interactions(seeded_db, out, consent="all", agent="other")
    assert written == 1
    payload = json.loads(out.read_text(encoding="utf-8").strip())
    assert payload["agent_name"] == "other"


def test_export_filters_by_since(seeded_db: Path, tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)  # between hour 1 and 2
    out = tmp_path / "out.jsonl"
    written = export_interactions(
        seeded_db,
        out,
        consent="all",
        since=cutoff,
    )
    # Only the 'unset' record at hour 2 lies after cutoff.
    assert written == 1
    payload = json.loads(out.read_text(encoding="utf-8").strip())
    assert payload["consent_status"] == "unset"


def test_export_filters_by_until(seeded_db: Path, tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    out = tmp_path / "out.jsonl"
    written = export_interactions(
        seeded_db,
        out,
        consent="all",
        until=cutoff,
    )
    # Only the 'opt_in' record at hour 0 is <= cutoff.
    assert written == 1
    payload = json.loads(out.read_text(encoding="utf-8").strip())
    assert payload["consent_status"] == "opt_in"


def test_export_creates_parent_dirs(seeded_db: Path, tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "out.jsonl"
    written = export_interactions(seeded_db, nested, consent="all")
    assert written == 3
    assert nested.is_file()


def test_default_db_path_under_user_data() -> None:
    p = default_db_path()
    assert p.name == "interactions.db"
    assert "africalim" in str(p)


def test_export_empty_db_writes_zero_records(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    with InteractionLogger(db):
        pass  # Just initialise the schema.
    out = tmp_path / "out.jsonl"
    written = export_interactions(db, out, consent="all")
    assert written == 0
    assert out.read_text(encoding="utf-8") == ""
