"""Typer CLI wrapper for the janskie agent.

Lightweight wrapper that the ``hip-cargo generate-cabs`` pre-commit
hook scans to produce ``src/africalim/cabs/janskie.yml``. Heavy
dependencies are imported lazily inside
:func:`africalim.core.janskie.janskie`; this module only depends on
``typer`` + ``hip_cargo`` so ``africalim --help`` stays fast.
"""

from __future__ import annotations

from typing import Annotated

import typer
from hip_cargo import stimela_cab


@stimela_cab(
    name="janskie",
    info="Ask janskie a question about radio interferometry tooling.",
)
def janskie(
    question: Annotated[
        str,
        typer.Option(..., help="Question to ask janskie"),
    ],
    provider: Annotated[
        str | None,
        typer.Option(help="LLM provider override (e.g. 'anthropic', 'openai')."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Model name override within the provider."),
    ] = None,
    no_log: Annotated[
        bool,
        typer.Option(help="Skip logging this interaction."),
    ] = False,
) -> None:
    """Ask janskie a question about radio interferometry tooling."""
    from africalim.core.janskie import janskie as janskie_core

    janskie_core(question=question, provider=provider, model=model, no_log=no_log)
