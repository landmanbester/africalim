"""Unit tests for ``africalim.utils.pricing``.

Sync tests (no asyncio). The pricing table is intentionally tiny and
documented as a rough estimate; these tests only assert the shape of
the API and the math, not specific dollar values.
"""

from __future__ import annotations

import pytest

from africalim.utils.pricing import PROVIDER_PRICES, estimate_cost_usd

# --------------------------------------------------------------------------- #
# Known-model happy path
# --------------------------------------------------------------------------- #


def test_known_model_returns_positive_float() -> None:
    """A known (provider, model) with positive token counts yields > 0."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 1000, 1000)

    assert isinstance(cost, float)
    assert cost > 0.0


@pytest.mark.parametrize(("provider", "model_name"), list(PROVIDER_PRICES.keys()))
def test_every_priced_model_yields_a_float(provider: str, model_name: str) -> None:
    """Every entry in PROVIDER_PRICES is callable end-to-end."""
    cost = estimate_cost_usd(provider, model_name, 100, 100)

    assert isinstance(cost, float)
    assert cost >= 0.0


# --------------------------------------------------------------------------- #
# None-on-unknown
# --------------------------------------------------------------------------- #


def test_unknown_provider_returns_none() -> None:
    """A provider missing from the table yields None, not a guess."""
    cost = estimate_cost_usd("not-a-provider", "claude-sonnet-4-6", 1000, 1000)

    assert cost is None


def test_unknown_model_under_known_provider_returns_none() -> None:
    """An unknown model under a known provider yields None."""
    cost = estimate_cost_usd("anthropic", "claude-not-a-model", 1000, 1000)

    assert cost is None


# --------------------------------------------------------------------------- #
# None-token guards
# --------------------------------------------------------------------------- #


def test_none_input_tokens_returns_none() -> None:
    """``input_tokens=None`` yields None even for a known model."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", None, 1000)

    assert cost is None


def test_none_output_tokens_returns_none() -> None:
    """``output_tokens=None`` yields None even for a known model."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 1000, None)

    assert cost is None


def test_both_none_returns_none() -> None:
    """If both token counts are None, the result is None."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", None, None)

    assert cost is None


# --------------------------------------------------------------------------- #
# Math sanity
# --------------------------------------------------------------------------- #


def test_math_sanity_one_million_tokens_each_way() -> None:
    """1M in + 1M out for sonnet-4-6 ≈ 3 + 15 = 18 USD."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)

    assert cost is not None
    assert cost == pytest.approx(18.0)


def test_math_scales_linearly() -> None:
    """Doubling token counts doubles cost."""
    base = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 500, 500)
    double = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 1000, 1000)

    assert base is not None
    assert double is not None
    assert double == pytest.approx(2 * base)


def test_zero_tokens_returns_zero_cost() -> None:
    """Zero tokens is a real value (not None) and costs 0."""
    cost = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 0, 0)

    assert cost == pytest.approx(0.0)


def test_input_and_output_priced_independently() -> None:
    """Output tokens cost more than input tokens for sonnet-4-6."""
    only_input = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 1_000_000, 0)
    only_output = estimate_cost_usd("anthropic", "claude-sonnet-4-6", 0, 1_000_000)

    assert only_input is not None
    assert only_output is not None
    assert only_output > only_input
