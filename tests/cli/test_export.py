"""CLI tests for ``africalim export``.

The CLI's ``export`` command resolves its DB path via
:func:`africalim.core.export.default_db_path`. Tests monkeypatch
``platformdirs.user_data_path`` so each invocation reads from a tmp DB
seeded with a known set of records.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from africalim.cli import app
from africalim.utils.logger import InteractionLogger, InteractionRecord


def _record(consent: str = "opt_in") -> InteractionRecord:
    return InteractionRecord(
        timestamp=datetime(2026, 5, 1, 12, tzinfo=timezone.utc),
        agent_name="janskie",
        agent_version="0.1.0-test",
        harness_version="0.1.0-test",
        model_provider="anthropic",
        model_name="claude-sonnet-4-6",
        user_input="hello?",
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
def seeded_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Place an interactions.db in tmp and patch platformdirs to find it."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = data_dir / "interactions.db"
    with InteractionLogger(db) as logger:
        logger.log_interaction(_record(consent="opt_in"))
        logger.log_interaction(_record(consent="opt_out"))

    import africalim.core.export as export_module

    monkeypatch.setattr(
        export_module.platformdirs,
        "user_data_path",
        lambda *_a, **_kw: data_dir,
    )
    return data_dir


def test_export_writes_jsonl_to_file(
    seeded_data_dir: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.jsonl"
    result = CliRunner().invoke(
        app,
        ["export", "--output", str(out), "--consent", "all"],
    )
    assert result.exit_code == 0, result.stdout
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    consent_values = {json.loads(line)["consent_status"] for line in lines}
    assert consent_values == {"opt_in", "opt_out"}


def test_export_default_consent_is_opt_in(
    seeded_data_dir: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.jsonl"
    result = CliRunner().invoke(app, ["export", "--output", str(out)])
    assert result.exit_code == 0, result.stdout
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["consent_status"] == "opt_in"


def test_export_rejects_invalid_consent(seeded_data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["export", "--consent", "wrong"])
    assert result.exit_code == 1


def test_export_rejects_invalid_since(seeded_data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["export", "--since", "not-a-date"])
    assert result.exit_code == 1


def test_export_filters_by_agent(seeded_data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    result = CliRunner().invoke(
        app,
        ["export", "--output", str(out), "--consent", "all", "--agent", "nobody"],
    )
    assert result.exit_code == 0, result.stdout
    assert out.read_text(encoding="utf-8") == ""
