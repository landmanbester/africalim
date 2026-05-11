"""Shared utilities for africalim.

Cross-cutting helpers that back multiple CLI commands (logging,
consent, retrieval, model resolution, deps wiring, runner) live here.
Per hip-cargo conventions, ``core/`` is reserved for one-file-per-CLI-
command implementations; everything that doesn't correspond directly
to a Typer command lives in this package.
"""
