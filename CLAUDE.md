# Project conventions for AI-assisted development

This project follows the [`hip-cargo`](https://github.com/landmanbester/hip-cargo) package template. Familiarize yourself with that structure before making changes.

## Source documents

- **`plans/africalim_technical_spec.md`** — original technical spec. Source of intent.
- **`plans/initialise_africalim.md`** — current execution plan for v0.1.0. Where this and the spec disagree, the plan wins.
- **`plans/progress.md`** — running task tracker; update as work lands.

## Architectural invariants (non-negotiable for v0.1.0)

1. Agents register via the plugin pattern; the CLI's `__init__.py` calls `register(app)` for each.
2. Shared infrastructure is **injected via `HarnessDeps`**, never imported directly by agents.
3. Interaction logging happens in `core/runner.py`'s `run_agent` wrapper, not in agents.

A concrete naming clarification: the "harness layer" referred to in the spec is implemented inside `src/africalim/core/`. The directory name follows hip-cargo conventions; module docstrings call out the harness role.

## Code style

- Functional style by default; classes only when state or interface complexity warrants them.
- Lazy imports of heavy dependencies in CLI modules (hip-cargo convention).
- All public functions have type hints and docstrings.
- Pydantic models for any structured data crossing module boundaries.
- No mutable default arguments.
- Path handling via `pathlib.Path`, never string concatenation.

## Testing

- Every module in `core/` has unit tests with ≥85% coverage (≥90% for `retrieval.py` per the plan).
- Agent tests use `pydantic_ai.models.test.TestModel`; never hit real APIs in CI.
- Fixtures for retrieval tests live in `tests/fixtures/mini_corpus/` (a small synthetic git repo).
- `pytest-asyncio` is in `Mode.STRICT` — async tests must be marked with `@pytest.mark.asyncio`.
- Run `uv run pytest` before declaring a milestone complete.

## What's in scope

See §8 of `plans/africalim_technical_spec.md` for what is *not* in scope for v0.1.0. Specifically out-of-scope items:

- Any agent other than `janskie`.
- The remote interaction-aggregator endpoint (server-side).
- Upload retry/batching/network failure handling.
- The `africalim review` Streamlit app (deferred to v0.2.0 per the plan).
- The `africalim corpus sync` command (manual cloning is fine for v0.1.0).
- Embedding-based retrieval; BM25/ripgrep is sufficient until a concrete failure case demands more.

## What's not in scope without explicit approval

- Adding new dependencies.
- Adding new agents (only `janskie` for v0.1.0).
- Adding non-CLI frontends.
- Changing the SQLite schema after Milestone 2 lands (use migrations instead).
- Adding embedding-based retrieval.

## Conventional commits

The pre-commit hook enforces conventional-commits prefixes from this allowlist: `feat`, `fix`, `refactor`, `perf`, `docs`, `deps`, `chore`, `ci`, `style`, `test`, `build`. Stick to them.
