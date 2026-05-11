"""Integration tests for the janskie agent against ``TestModel``.

These tests build a real :class:`HarnessDeps` (real ``InteractionLogger``,
real ``ConsentManager``, real ``CorpusConfig`` pointing at the
``mini_corpus`` fixture) and run :func:`run_agent_sync` end-to-end. The
language model is faked via ``pydantic_ai.models.test.TestModel`` so the
suite never reaches the network.

``TestModel`` defaults to ``call_tools='all'``, which would call our tools
with synthetic args (e.g. ``repo='a'``). That can't satisfy our corpus
look-up, so all of these end-to-end tests use ``TestModel(call_tools=[])``
to keep the model focused on producing structured output. Tool wiring is
verified separately via direct introspection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from africalim.core.janskie import (
    _EMPTY_CORPUS_SUMMARY,
    JANSKIE_AGENT_NAME,
    JANSKIE_AGENT_VERSION,
    JanskieOutput,
    SourceCitation,
    _load_corpus_with_warnings,
    _render_corpus_summary,
    build_agent,
)
from africalim.utils.consent import ConsentManager
from africalim.utils.deps import CorpusConfig, CorpusRepo, HarnessDeps
from africalim.utils.logger import InteractionLogger


@pytest.fixture
def deps_with_corpus(
    tmp_path: Path,
    mini_corpus_path: Path,
) -> HarnessDeps:
    """Build a HarnessDeps wired to the mini_corpus fixture."""
    consent = ConsentManager(tmp_path / "config.toml")
    consent.set_status("opt_in")
    logger = InteractionLogger(tmp_path / "interactions.db")
    corpus = CorpusConfig(
        repos=[
            CorpusRepo(
                name="synthcal",
                path=mini_corpus_path,
                ref="main",
            ),
        ],
    )
    return HarnessDeps(
        corpus=corpus,
        logger=logger,
        consent=consent,
        harness_version="0.1.0-test",
    )


def test_janskie_returns_structured_output_and_logs(deps_with_corpus: HarnessDeps) -> None:
    """End-to-end: TestModel produces a JanskieOutput; row is persisted."""
    from africalim.utils.runner import run_agent_sync

    agent = build_agent(deps_with_corpus, model="anthropic:claude-sonnet-4-6")
    with agent.override(model=TestModel(call_tools=[])):
        result = run_agent_sync(
            agent,
            "what does synthcal do?",
            deps_with_corpus,
            agent_name=JANSKIE_AGENT_NAME,
            agent_version=JANSKIE_AGENT_VERSION,
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            corpus_versions={"synthcal": "24470c8"},
        )

    assert isinstance(result.output, JanskieOutput)
    assert result.output.confidence in {"high", "medium", "low"}
    assert all(isinstance(s, SourceCitation) for s in result.output.sources)

    rows = deps_with_corpus.logger.list_interactions()
    assert len(rows) == 1
    row = rows[0]
    assert row.agent_name == JANSKIE_AGENT_NAME
    assert row.agent_version == JANSKIE_AGENT_VERSION
    assert row.model_provider == "anthropic"
    assert row.model_name == "claude-sonnet-4-6"
    assert row.user_input == "what does synthcal do?"
    assert row.upload_status == "pending"  # consent was opt_in
    assert row.consent_status == "opt_in"
    assert row.error is None
    assert row.duration_ms >= 0
    assert row.corpus_versions == {"synthcal": "24470c8"}


def test_janskie_consent_drives_upload_status(
    tmp_path: Path,
) -> None:
    """opt_out → row.upload_status == 'skipped'."""
    from africalim.utils.runner import run_agent_sync

    consent = ConsentManager(tmp_path / "config.toml")
    consent.set_status("opt_out")
    logger = InteractionLogger(tmp_path / "interactions.db")
    deps = HarnessDeps(
        corpus=CorpusConfig(repos=[]),
        logger=logger,
        consent=consent,
        harness_version="0.1.0-test",
    )

    agent = build_agent(deps, model="anthropic:claude-sonnet-4-6")
    with agent.override(model=TestModel(call_tools=[])):
        run_agent_sync(
            agent,
            "hello?",
            deps,
            agent_name=JANSKIE_AGENT_NAME,
            agent_version=JANSKIE_AGENT_VERSION,
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
        )

    [row] = deps.logger.list_interactions()
    assert row.consent_status == "opt_out"
    assert row.upload_status == "skipped"


def test_janskie_no_log_skips_persistence(deps_with_corpus: HarnessDeps) -> None:
    from africalim.utils.runner import run_agent_sync

    agent = build_agent(deps_with_corpus, model="anthropic:claude-sonnet-4-6")
    with agent.override(model=TestModel(call_tools=[])):
        run_agent_sync(
            agent,
            "hello?",
            deps_with_corpus,
            agent_name=JANSKIE_AGENT_NAME,
            agent_version=JANSKIE_AGENT_VERSION,
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            no_log=True,
        )
    assert deps_with_corpus.logger.list_interactions() == []


# --------------------------------------------------------------------------- #
# Direct unit tests against build_agent's helpers — no LLM round trip.
# --------------------------------------------------------------------------- #


def test_render_corpus_summary_lists_repos(mini_corpus_path: Path) -> None:
    corpus = CorpusConfig(
        repos=[
            CorpusRepo(name="synthcal", path=mini_corpus_path, ref="main"),
            CorpusRepo(name="other", path=mini_corpus_path, ref="dev"),
        ],
    )
    rendered = _render_corpus_summary(corpus)
    assert "synthcal" in rendered
    assert "other" in rendered
    assert "ref: main" in rendered
    assert "ref: dev" in rendered
    # URLs intentionally omitted from the rendered summary.
    assert "http" not in rendered.lower()


def test_render_corpus_summary_empty_uses_sentinel() -> None:
    rendered = _render_corpus_summary(CorpusConfig(repos=[]))
    assert rendered == _EMPTY_CORPUS_SUMMARY


def test_build_agent_registers_three_tools(deps_with_corpus: HarnessDeps) -> None:
    """Smoke-check that the agent has the three janskie tools attached."""
    agent = build_agent(deps_with_corpus, model="anthropic:claude-sonnet-4-6")
    # `agent._function_toolset.tools` is the dict of `@agent.tool`-registered
    # tools in pydantic-ai 1.x. Reaching into the underscore attribute is
    # acceptable for a smoke test and is asserted in unit-test scope only.
    tool_names = set(agent._function_toolset.tools.keys())
    assert {"search_codebase", "read_file", "list_repo_structure"} <= tool_names, tool_names


def _write_corpus_toml(path: Path, entries: list[dict[str, str]]) -> None:
    """Tiny helper: write a corpus.toml with the given [[repo]] entries."""
    lines: list[str] = []
    for entry in entries:
        lines.append("[[repo]]")
        for key, value in entry.items():
            lines.append(f'{key} = "{value}"')
        lines.append("")
    path.write_text("\n".join(lines))


def test_load_corpus_with_warnings_filters_missing_paths(
    tmp_path: Path,
    mini_corpus_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing on-disk paths are dropped; one warning per drop hits stderr."""
    corpus_toml = tmp_path / "corpus.toml"
    bogus_path = tmp_path / "nope" / "missing-repo"
    _write_corpus_toml(
        corpus_toml,
        [
            {"name": "good", "path": str(mini_corpus_path), "ref": "main"},
            {"name": "ghost", "path": str(bogus_path), "ref": "main"},
        ],
    )
    monkeypatch.setattr(
        "africalim.utils.corpus_config.default_corpus_path",
        lambda: corpus_toml,
    )

    corpus = _load_corpus_with_warnings()

    assert [r.name for r in corpus.repos] == ["good"]
    captured = capsys.readouterr()
    assert "ghost" in captured.err
    assert str(bogus_path) in captured.err
    assert "good" not in captured.err


def test_load_corpus_with_warnings_missing_file_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing corpus.toml yields an empty config and no warnings."""
    monkeypatch.setattr(
        "africalim.utils.corpus_config.default_corpus_path",
        lambda: tmp_path / "does-not-exist.toml",
    )

    corpus = _load_corpus_with_warnings()

    assert corpus.repos == []
    assert capsys.readouterr().err == ""
