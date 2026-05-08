# Contributing to africalim

Thanks for your interest. africalim is intentionally narrow in scope while it finds its footing — please read this before opening a PR.

## Project scope

africalim is an open-source agentic harness for radio-interferometry tooling. The first release (`v0.1.0`) ships exactly **one agent** (`janskie`, a general-purpose Q&A bot) plus the shared infrastructure (logger, consent manager, model factory, retrieval primitives) that future agents will reuse.

The authoritative scope document is `plans/africalim_technical_spec.md`. The active execution plan is `plans/initialise_africalim.md`. **Any deviation from those documents needs to be discussed in an issue first.**

### Out of scope for v0.1.0

- Any agent other than `janskie`.
- The remote interaction-aggregator endpoint (server-side).
- Upload retry / batching / network-failure handling.
- `africalim corpus sync` (manual cloning is fine for v0.1.0).
- Embedding-based retrieval.
- Non-CLI frontends (e.g. web UIs beyond the deferred Streamlit review app).

### What's not in scope without prior approval

- Adding new dependencies.
- Adding new agents (saved for v0.2.0+).
- Changing the SQLite schema after Milestone 2 lands — use migrations instead.

## Architectural invariants

Reviewers check every PR against these:

1. Agents register via the plugin pattern; the CLI's `__init__.py` calls `register(app)` for each agent module.
2. Shared infrastructure is **injected via `HarnessDeps`**. Agents never `from africalim.core...` — they receive what they need.
3. Interaction logging happens once, in `core/runner.py`'s `run_agent` wrapper. Agents do not log directly.

If your change touches any of these invariants, link to the issue where the deviation was approved.

## Adding an agent (for v0.2.0+)

1. Open an issue proposing the agent (name following the Afrikaans-diminutive / radio-pioneer convention).
2. Once approved, create `src/africalim/agents/<name>/` with at minimum:
   - `agent.py` exposing `build_agent(deps: HarnessDeps) -> Agent`.
   - `cli.py` exposing `register(app: typer.Typer) -> None`.
   - `schemas.py` with the agent's pydantic output type.
   - `prompts/system.md` for the system prompt.
3. Add a thin `src/africalim/cli/<name>.py` wrapper carrying the `@stimela_cab` decorator so cab generation picks the agent up.
4. Register the new agent in `src/africalim/cli/__init__.py`.
5. Tests under `tests/agents/test_<name>.py` using `pydantic_ai.models.test.TestModel` (no real API calls in CI).

## Development setup

```bash
uv sync --group dev --group test
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

Then iterate with:

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```

## Commit messages

Pre-commit enforces [conventional commits](https://www.conventionalcommits.org/) from this allowlist:

`feat`, `fix`, `refactor`, `perf`, `docs`, `deps`, `chore`, `ci`, `style`, `test`, `build`

Use a scope when it helps: `feat(janskie): add caveat truncation`.

## Pull requests

- Keep PRs small and milestone-scoped (see `plans/initialise_africalim.md`).
- Update `plans/progress.md` when you complete a milestone task.
- Verify CI green before requesting review.
- New tests for any new behaviour. We aim for ≥85% coverage on `core/`.
