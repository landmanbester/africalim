"""Harness layer — rough USD cost estimation per ``(provider, model)``.

The interaction logger writes a nullable ``cost_usd_estimate`` column for
every agent run. To populate it we need a price table; to keep that
table honest, this module only contains entries for the small set of
models africalim's v0.1.0 default flow can plausibly produce. Anything
else returns :data:`None` from :func:`estimate_cost_usd`, and the logger
simply records ``NULL`` rather than guessing.

Prices below are **rough estimates current as of the Claude knowledge
cutoff** and are listed in USD per million tokens. Update via PR — do
not silently edit a published row, append a comment with the date the
new figure was sourced.

Numbers are taken from Anthropic's published pricing pages and are
intended to give an order-of-magnitude sense of cost in the interaction
log; the column is explicitly documented as an *estimate*.
"""

from __future__ import annotations

# (provider, model_name) -> (input_usd_per_million_tokens, output_usd_per_million_tokens).
#
# Rough estimates current as of the Claude knowledge cutoff; update via PR.
PROVIDER_PRICES: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-opus-4-7"): (15.00, 75.00),
    ("anthropic", "claude-haiku-4-5"): (1.00, 5.00),
}


def estimate_cost_usd(
    provider: str,
    model_name: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Estimate the USD cost of a single agent run.

    Args:
        provider: pydantic-ai provider id (e.g. ``"anthropic"``).
        model_name: Model name within that provider.
        input_tokens: Tokens consumed by the request, or ``None`` if the
            usage report did not include input tokens.
        output_tokens: Tokens produced by the response, or ``None`` if
            the usage report did not include output tokens.

    Returns:
        USD cost as a float, or ``None`` when the cost cannot be
        estimated. ``None`` is returned when:

        * ``(provider, model_name)`` has no entry in
          :data:`PROVIDER_PRICES`; or
        * either ``input_tokens`` or ``output_tokens`` is ``None``.
    """
    if input_tokens is None or output_tokens is None:
        return None
    prices = PROVIDER_PRICES.get((provider, model_name))
    if prices is None:
        return None
    input_price_per_m, output_price_per_m = prices
    return (input_tokens / 1_000_000) * input_price_per_m + (output_tokens / 1_000_000) * output_price_per_m
