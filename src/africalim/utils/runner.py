"""Harness layer — agent run wrapper.

This module owns the single entry point through which the CLI invokes a
``pydantic_ai.Agent``. :func:`run_agent` (and its sync wrapper
:func:`run_agent_sync`) capture the full interaction trace, persist a
:class:`~africalim.utils.logger.InteractionRecord` row, and surface the
:class:`pydantic_ai.agent.AgentRunResult` to the caller.

Architectural invariant (see ``CLAUDE.md`` and
``plans/initialise_africalim.md`` §1): interaction logging happens here,
never in agents themselves. Agents stay focused on their domain logic;
the harness handles persistence, cost estimation, error capture, and
trace flattening.

Tool-trace flattening pairs ``ToolCallPart`` with the matching
``ToolReturnPart`` by ``tool_call_id``. Pydantic-ai 1.92.0 emits a
deterministic ``tool_call_id`` for both halves of a tool exchange, so
the pairing is unambiguous. Stray parts (a return without a call, or
vice-versa) are still recorded as best-effort entries so a debugging
operator can see what the model did. The synthetic ``final_result``
tool — pydantic-ai's internal mechanism for delivering the structured
output — is filtered out because it duplicates :attr:`AgentRunResult.output`.

On failure, the wrapped agent's exception is logged with a serialised
traceback, then re-raised inside :class:`AgentRunFailure` so callers can
still reach the row id of the persisted error record. Setting
``no_log=True`` suppresses the SQLite write on both paths but still
runs the agent and (on failure) still raises the wrapper exception.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from africalim.utils.deps import HarnessDeps
from africalim.utils.logger import InteractionRecord
from africalim.utils.pricing import estimate_cost_usd

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pydantic_ai import Agent
    from pydantic_ai.agent import AgentRunResult


# Pydantic-ai routes structured output through an internal "final_result"
# tool call. The result is already exposed via ``result.output``, so we
# strip it from the persisted tool trace to avoid double-recording.
_FINAL_RESULT_TOOL_NAME = "final_result"


class AgentRunFailure(Exception):  # noqa: N818 - name fixed by harness public API
    """Raised when an agent run fails *after* the failure has been logged.

    The original exception is available as :attr:`original`; the SQLite
    row id of the error record is :attr:`row_id` (``None`` when
    ``no_log=True``).
    """

    def __init__(
        self,
        message: str,
        *,
        row_id: int | None,
        original: BaseException,
    ) -> None:
        super().__init__(message)
        self.row_id = row_id
        self.original = original


def _normalise_output(output: Any) -> dict[str, Any]:
    """Coerce an agent's ``result.output`` into a JSON-friendly dict.

    Pydantic models are serialised via :meth:`BaseModel.model_dump`;
    mappings are passed through ``dict(...)``; anything else is wrapped
    as ``{"value": str(output)}`` so the logger always sees a dict and
    never crashes on an exotic output type.
    """
    if isinstance(output, BaseModel):
        return output.model_dump()
    if isinstance(output, Mapping):
        return dict(output)
    return {"value": str(output)}


def _normalise_tool_content(content: Any) -> Any:
    """Coerce a ``ToolReturnPart.content`` into a JSON-friendly value.

    Pydantic models become dicts; mappings/sequences are passed through
    so the logger's ``json.dumps(default=str)`` can serialise them.
    Strings are returned unchanged.
    """
    if isinstance(content, BaseModel):
        return content.model_dump()
    if isinstance(content, Mapping):
        return dict(content)
    return content


def _extract_tool_traces(messages: list[Any]) -> list[dict[str, Any]]:
    """Flatten pydantic-ai message parts into ``[{tool, args, result, tool_call_id}]``.

    Walks every ``ToolCallPart`` / ``ToolReturnPart`` across all messages
    and pairs them by ``tool_call_id``. The internal ``final_result``
    tool — pydantic-ai's structured-output delivery mechanism — is
    filtered out because the same data lives on
    :attr:`AgentRunResult.output`.

    Stray entries (a call without a matching return, or vice-versa) are
    preserved with the missing half left as ``None`` so a human reviewer
    can still see what the model did.
    """
    # Lazy import: pydantic-ai is heavy and we want module import to stay
    # cheap for tests that don't actually run an agent.
    from pydantic_ai.messages import ToolCallPart, ToolReturnPart

    calls: dict[str, ToolCallPart] = {}
    returns: dict[str, ToolReturnPart] = {}
    # Track first-seen order of tool_call_ids so the resulting trace
    # mirrors the order the model emitted calls in.
    order: list[str] = []

    for msg in messages:
        for part in getattr(msg, "parts", []) or []:
            if isinstance(part, ToolCallPart):
                if part.tool_name == _FINAL_RESULT_TOOL_NAME:
                    continue
                if part.tool_call_id not in calls and part.tool_call_id not in returns:
                    order.append(part.tool_call_id)
                calls[part.tool_call_id] = part
            elif isinstance(part, ToolReturnPart):
                if part.tool_name == _FINAL_RESULT_TOOL_NAME:
                    continue
                if part.tool_call_id not in calls and part.tool_call_id not in returns:
                    order.append(part.tool_call_id)
                returns[part.tool_call_id] = part

    traces: list[dict[str, Any]] = []
    for tool_call_id in order:
        call = calls.get(tool_call_id)
        ret = returns.get(tool_call_id)
        tool_name = (call.tool_name if call is not None else ret.tool_name) if (call or ret) else ""
        args = call.args if call is not None else None
        result = _normalise_tool_content(ret.content) if ret is not None else None
        traces.append(
            {
                "tool": tool_name,
                "args": args,
                "result": result,
                "tool_call_id": tool_call_id,
            }
        )
    return traces


def _safe_usage_tokens(result: Any) -> tuple[int | None, int | None]:
    """Return ``(input_tokens, output_tokens)`` from ``result.usage()``.

    Returns ``(None, None)`` when ``result.usage()`` raises or returns
    ``None``. Pricing is honest: a missing token count must not be
    treated as zero.
    """
    try:
        usage = result.usage()
    except Exception:
        return (None, None)
    if usage is None:
        return (None, None)
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )


def _upload_status_for(consent_status: str) -> str:
    """Map a consent status to the initial upload status of a new row."""
    return "pending" if consent_status == "opt_in" else "skipped"


async def run_agent(
    agent: Agent[HarnessDeps, Any],
    user_input: str,
    deps: HarnessDeps,
    *,
    agent_name: str,
    agent_version: str,
    model_provider: str,
    model_name: str,
    corpus_versions: Mapping[str, str] | None = None,
    output_post_process: Callable[[Any], None] | None = None,
    no_log: bool = False,
) -> AgentRunResult[Any]:
    """Run ``agent`` against ``user_input`` and persist an interaction record.

    On success, build an :class:`InteractionRecord` from ``result``,
    write it via ``deps.logger`` (unless ``no_log=True``), and return
    ``result``. On failure, build an error record covering the partial
    information we have, persist it (unless ``no_log=True``), and raise
    :class:`AgentRunFailure` whose ``row_id`` references the persisted
    row (or ``None`` when ``no_log=True``).

    Args:
        agent: The pydantic-ai agent to execute.
        user_input: The user prompt forwarded to the agent.
        deps: Shared harness deps. Threaded into ``agent.run`` so tools
            can resolve corpora, logger, consent, etc.
        agent_name: Identifier persisted with the row (e.g. ``"janskie"``).
        agent_version: Version string for ``agent_name``.
        model_provider: Provider identifier (e.g. ``"anthropic"``).
            Used both for logging and for cost estimation.
        model_name: Model name within the provider.
        corpus_versions: Optional name → commit-hash map captured for
            this run. Stored verbatim on the row.
        output_post_process: Optional callback invoked with
            ``result.output`` after a successful run, before the
            interaction is logged and returned. Intended for agent-level
            post-processing such as backfilling values the model could
            not produce itself. Exceptions raised by the callback are
            swallowed so a backfill bug cannot kill a successful run.
        no_log: When ``True``, the agent runs but no row is written.

    Returns:
        The :class:`AgentRunResult` produced by ``agent.run``.

    Raises:
        AgentRunFailure: When the wrapped agent run raises. The
            original exception is available as :attr:`AgentRunFailure.original`
            and is also chained via ``raise ... from e``.
    """
    start_perf = time.perf_counter()
    start_ts = datetime.now(timezone.utc)

    consent_status = deps.consent.get_status()
    upload_status = _upload_status_for(consent_status)
    versions = dict(corpus_versions or {})

    try:
        result = await agent.run(user_input, deps=deps)
    except BaseException as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        error_payload: dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        record = InteractionRecord(
            timestamp=start_ts,
            agent_name=agent_name,
            agent_version=agent_version,
            harness_version=deps.harness_version,
            model_provider=model_provider,
            model_name=model_name,
            user_input=user_input,
            final_output={},
            tool_traces=[],
            corpus_versions=versions,
            consent_status=consent_status,
            upload_status=upload_status,
            cost_usd_estimate=None,
            duration_ms=duration_ms,
            error=error_payload,
        )
        row_id: int | None = None
        if not no_log:
            row_id = deps.logger.log_interaction(record)
        # Surfaces the original exception via ``__cause__`` and via
        # :attr:`AgentRunFailure.original` so callers (the CLI) can
        # decide whether to re-raise, transform, or just print.
        raise AgentRunFailure(str(exc), row_id=row_id, original=exc) from exc

    if output_post_process is not None:
        try:
            output_post_process(result.output)
        except Exception:
            # Silent fallback: a backfill bug must not kill an
            # otherwise-successful run. The logged row keeps whatever
            # the model originally produced.
            pass

    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    input_tokens, output_tokens = _safe_usage_tokens(result)
    cost = estimate_cost_usd(model_provider, model_name, input_tokens, output_tokens)

    record = InteractionRecord(
        timestamp=start_ts,
        agent_name=agent_name,
        agent_version=agent_version,
        harness_version=deps.harness_version,
        model_provider=model_provider,
        model_name=model_name,
        user_input=user_input,
        final_output=_normalise_output(result.output),
        tool_traces=_extract_tool_traces(result.all_messages()),
        corpus_versions=versions,
        consent_status=consent_status,
        upload_status=upload_status,
        cost_usd_estimate=cost,
        duration_ms=duration_ms,
        error=None,
    )
    if not no_log:
        deps.logger.log_interaction(record)
    return result


def run_agent_sync(
    agent: Agent[HarnessDeps, Any],
    user_input: str,
    deps: HarnessDeps,
    *,
    agent_name: str,
    agent_version: str,
    model_provider: str,
    model_name: str,
    corpus_versions: Mapping[str, str] | None = None,
    output_post_process: Callable[[Any], None] | None = None,
    no_log: bool = False,
) -> AgentRunResult[Any]:
    """Sync wrapper around :func:`run_agent` for Typer commands.

    Typer command callbacks are sync; this wrapper is the only place the
    harness mixes ``asyncio.run`` with the rest of the runtime. Tests
    can drive either entry point — ``run_agent`` directly with
    ``pytest-asyncio`` or ``run_agent_sync`` from a sync test.
    """
    return asyncio.run(
        run_agent(
            agent,
            user_input,
            deps,
            agent_name=agent_name,
            agent_version=agent_version,
            model_provider=model_provider,
            model_name=model_name,
            corpus_versions=corpus_versions,
            output_post_process=output_post_process,
            no_log=no_log,
        )
    )
