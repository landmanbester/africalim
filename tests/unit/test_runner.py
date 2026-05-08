"""Unit tests for ``africalim.utils.runner``.

These tests use ``pydantic_ai.models.test.TestModel`` exclusively so the
suite never reaches a real LLM. The runner is async at its core, so all
tests except the sync-wrapper smoke test are marked
``@pytest.mark.asyncio``; the harness CLAUDE.md guarantees pytest-asyncio
runs in ``Mode.STRICT`` so a missing marker would surface as a clear
warning rather than a silent skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from africalim.utils.consent import ConsentManager
from africalim.utils.deps import CorpusConfig, HarnessDeps
from africalim.utils.logger import InteractionLogger
from africalim.utils.runner import AgentRunFailure, run_agent, run_agent_sync

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class Out(BaseModel):
    """Tiny pydantic output for the ``TestModel``-driven agent runs."""

    answer: str


@pytest.fixture
def deps(tmp_path: Path) -> HarnessDeps:
    """Build a real :class:`HarnessDeps` over a temp SQLite + config file.

    Returns a fully-functional dependency container so the tests can
    exercise the genuine ``InteractionLogger`` rather than a stub —
    that's the whole point of the runner test, after all.
    """
    db_path = tmp_path / "interactions.sqlite3"
    config_path = tmp_path / "config.toml"
    logger = InteractionLogger(db_path)
    consent = ConsentManager(config_path)
    return HarnessDeps(
        corpus=CorpusConfig(),
        logger=logger,
        consent=consent,
        harness_version="0.1.0-test",
    )


def _build_simple_agent() -> Agent[HarnessDeps, Out]:
    """Agent with no tools; ``TestModel`` delivers a structured ``Out``."""
    return Agent(TestModel(), output_type=Out, deps_type=HarnessDeps)


def _build_tool_agent() -> Agent[HarnessDeps, Out]:
    """Agent with a single ``my_tool`` tool that ``TestModel`` is asked to call."""
    agent: Agent[HarnessDeps, Out] = Agent(
        TestModel(call_tools=["my_tool"]),
        output_type=Out,
        deps_type=HarnessDeps,
    )

    @agent.tool
    def my_tool(ctx: RunContext[HarnessDeps], x: str) -> str:
        # The body is irrelevant — TestModel synthesises the args.
        return f"tool said {x}"

    return agent


# --------------------------------------------------------------------------- #
# 1. Success path — no tools
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_success_writes_row_and_returns_result(deps: HarnessDeps) -> None:
    agent = _build_simple_agent()

    result = await run_agent(
        agent,
        "hello",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    rows = deps.logger.list_interactions()
    assert len(rows) == 1
    row = rows[0]
    assert row.agent_name == "janskie"
    assert row.agent_version == "0.1.0"
    assert row.harness_version == "0.1.0-test"
    assert row.model_provider == "test"
    assert row.model_name == "test-model"
    assert row.user_input == "hello"
    assert row.final_output == result.output.model_dump()
    # The internal "final_result" tool MUST be filtered out — without
    # custom tools, the trace is empty.
    assert row.tool_traces == []
    assert row.error is None
    assert row.duration_ms >= 0
    # ``test``/``test-model`` is not in the price table, so cost is None.
    assert row.cost_usd_estimate is None
    # Default consent is "unset", which maps to "skipped".
    assert row.consent_status == "unset"
    assert row.upload_status == "skipped"


@pytest.mark.asyncio
async def test_success_records_corpus_versions(deps: HarnessDeps) -> None:
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hello",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
        corpus_versions={"stimela2": "abc123", "pfb-imaging": "def456"},
    )

    [row] = deps.logger.list_interactions()
    assert row.corpus_versions == {"stimela2": "abc123", "pfb-imaging": "def456"}


# --------------------------------------------------------------------------- #
# 2. Tool calls captured in the trace
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tool_call_captured_in_trace(deps: HarnessDeps) -> None:
    agent = _build_tool_agent()

    await run_agent(
        agent,
        "please use the tool",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    [row] = deps.logger.list_interactions()
    # The synthetic ``final_result`` exchange MUST be filtered out, leaving
    # exactly the user-defined tool call.
    assert len(row.tool_traces) == 1
    trace = row.tool_traces[0]
    assert trace["tool"] == "my_tool"
    assert trace["result"] is not None
    assert trace["tool_call_id"]
    assert isinstance(trace["args"], dict)


# --------------------------------------------------------------------------- #
# 3. Failure path
# --------------------------------------------------------------------------- #


class _BoomError(RuntimeError):
    """Marker exception used to assert ``AgentRunFailure.original``."""


@pytest.mark.asyncio
async def test_failure_logs_row_and_raises_wrapper(deps: HarnessDeps, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _build_simple_agent()

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise _BoomError("kaboom")

    monkeypatch.setattr(agent, "run", boom)

    with pytest.raises(AgentRunFailure) as exc_info:
        await run_agent(
            agent,
            "hello",
            deps,
            agent_name="janskie",
            agent_version="0.1.0",
            model_provider="test",
            model_name="test-model",
        )

    # The original exception is preserved both on the wrapper and via
    # exception chaining.
    assert isinstance(exc_info.value.original, _BoomError)
    assert exc_info.value.__cause__ is exc_info.value.original
    assert exc_info.value.row_id is not None

    [row] = deps.logger.list_interactions()
    assert row.error is not None
    assert row.error["type"] == "_BoomError"
    assert row.error["message"] == "kaboom"
    assert "Traceback" in row.error["traceback"]
    assert row.final_output == {}
    assert row.tool_traces == []
    assert row.duration_ms >= 0


# --------------------------------------------------------------------------- #
# 4. ``no_log=True`` path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_log_skips_write_on_success(deps: HarnessDeps) -> None:
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hello",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
        no_log=True,
    )

    assert deps.logger.list_interactions() == []


@pytest.mark.asyncio
async def test_no_log_still_raises_on_failure(deps: HarnessDeps, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _build_simple_agent()

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise _BoomError("kaboom")

    monkeypatch.setattr(agent, "run", boom)

    with pytest.raises(AgentRunFailure) as exc_info:
        await run_agent(
            agent,
            "hello",
            deps,
            agent_name="janskie",
            agent_version="0.1.0",
            model_provider="test",
            model_name="test-model",
            no_log=True,
        )

    # No row written, but the wrapper still surfaces the original
    # exception with ``row_id=None``.
    assert exc_info.value.row_id is None
    assert isinstance(exc_info.value.original, _BoomError)
    assert deps.logger.list_interactions() == []


# --------------------------------------------------------------------------- #
# 5. Consent-driven upload status
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upload_status_pending_when_opt_in(deps: HarnessDeps) -> None:
    deps.consent.set_status("opt_in")
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hi",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    [row] = deps.logger.list_interactions()
    assert row.consent_status == "opt_in"
    assert row.upload_status == "pending"


@pytest.mark.asyncio
async def test_upload_status_skipped_when_opt_out(deps: HarnessDeps) -> None:
    deps.consent.set_status("opt_out")
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hi",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    [row] = deps.logger.list_interactions()
    assert row.consent_status == "opt_out"
    assert row.upload_status == "skipped"


@pytest.mark.asyncio
async def test_upload_status_skipped_when_unset(deps: HarnessDeps) -> None:
    # Default ConsentManager state is "unset"; do not call set_status.
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hi",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    [row] = deps.logger.list_interactions()
    assert row.consent_status == "unset"
    assert row.upload_status == "skipped"


# --------------------------------------------------------------------------- #
# 6. Sync wrapper smoke test
# --------------------------------------------------------------------------- #


def test_run_agent_sync_returns_same_result_shape(deps: HarnessDeps) -> None:
    agent = _build_simple_agent()

    result = run_agent_sync(
        agent,
        "hello",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="test",
        model_name="test-model",
    )

    assert isinstance(result.output, Out)
    [row] = deps.logger.list_interactions()
    assert row.final_output == result.output.model_dump()


# --------------------------------------------------------------------------- #
# 7. Cost estimation when the model IS in the price table
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cost_populated_for_known_model(deps: HarnessDeps) -> None:
    """A known ``(provider, model)`` should populate ``cost_usd_estimate``."""
    agent = _build_simple_agent()

    await run_agent(
        agent,
        "hi",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="anthropic",
        model_name="claude-sonnet-4-6",
    )

    [row] = deps.logger.list_interactions()
    # TestModel reports non-zero token usage, and Sonnet 4.6 is in the
    # price table — so we expect a positive float, not None.
    assert isinstance(row.cost_usd_estimate, float)
    assert row.cost_usd_estimate > 0


# --------------------------------------------------------------------------- #
# 8. Robustness: usage() raising must not crash the runner
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_usage_failure_yields_none_cost(deps: HarnessDeps, monkeypatch: pytest.MonkeyPatch) -> None:
    """If ``result.usage()`` blows up, the runner logs ``cost=None`` rather than crashing."""
    agent = _build_simple_agent()

    real_run = agent.run

    async def wrapped(*args: object, **kwargs: object) -> object:
        result = await real_run(*args, **kwargs)

        def _broken_usage() -> None:
            raise RuntimeError("no usage available")

        # ``result.usage`` is a method; replace it on the instance so
        # the runner's ``_safe_usage_tokens`` falls into its except-arm.
        result.usage = _broken_usage  # type: ignore[method-assign]
        return result

    monkeypatch.setattr(agent, "run", wrapped)

    await run_agent(
        agent,
        "hi",
        deps,
        agent_name="janskie",
        agent_version="0.1.0",
        model_provider="anthropic",
        model_name="claude-sonnet-4-6",
    )

    [row] = deps.logger.list_interactions()
    assert row.cost_usd_estimate is None
