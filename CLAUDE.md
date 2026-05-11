# Project conventions for AI-assisted development

This project follows the [`hip-cargo`](https://github.com/landmanbester/hip-cargo) package template. Familiarize yourself with that structure before making changes.

## Source documents

- **`plans/africalim_technical_spec.md`** — original technical spec. Source of intent.
- **`plans/initialise_africalim.md`** — execution plan for v0.1.0. Where this and the spec disagree, the plan wins.
- **`plans/hip_refactor.md`** — execution plan for the post-v0.1.0 hip-cargo round-trip refactor. Where this and earlier docs disagree, this wins.
- **`plans/progress.md`** + **`plans/hip_progress.md`** — running task trackers; update as work lands.

## Architectural invariants (non-negotiable)

1. **`cli/X.py` ↔ `core/X.py` ↔ `cabs/X.yml` are 1:1.** Filenames must match. Each `cli/X.py` carries exactly one `@stimela_cab`-decorated function whose name matches the file. The Typer subapp wiring in `cli/__init__.py` may rename the user-facing command (e.g. `africalim config show` is mounted from `cli/config_show.py::config_show`) but file names follow Python identifier rules (`config_show`, not `config-show`).
2. **`cli/X.py` round-trips through `cabs/X.yml`.** The CLI source is hand-edited but is also a deterministic output of `hip-cargo generate-function`. `tests/test_roundtrip.py` enforces byte-identity. Practical implication: the CLI wrapper body is the canonical container-fallback boilerplate (preflight → lazy-import `core.X.X as X_core` → delegate → `run_in_container` fallback). All custom logic — error handling, input parsing, success messages — lives in `core/X.py`.
3. **`core/` is flat.** No subpackages. One file per CLI command; nothing else.
4. **`utils/` hosts shared infrastructure.** Cross-cutting helpers (consent, deps, logger, models, pricing, retrieval, runner, user_config, corpus_config) — anything that doesn't correspond to a CLI command. Never put shared infra in `core/`.
5. **Path-typed CLI params use `File` / `Directory` / `MS` / `URI` `NewType`s with `parser=parse_upath`**, never bare `Path | None`. The reverse-derivation from `Optional[Path]` is `str | None` + `StimelaMeta(dtype=...)`, which doesn't auto-coerce strings to `Path` and breaks core code that calls `Path` methods.
6. **Help/info string spacing.** `info=`/`help=` literals must not contain `.<non-space>` (period followed by non-space-non-newline). Avoid `e.g.`, `i.e.`, and dotted-key examples in info fields. `tests/test_roundtrip.py::test_help_strings_have_proper_spacing` enforces this.
7. **Shared infrastructure is injected via `HarnessDeps`**, never imported directly by agents.
8. **Interaction logging happens in `utils/runner.py`'s `run_agent` wrapper**, not in agents themselves.

## Adding a new command

1. Write `src/africalim/cli/<name>.py` matching the canonical shape — see `plans/hip_refactor.md` §3 for the template, or copy any existing `cli/X.py` and adapt the parameter list and the `core.<name>.<name>` lazy-import target.
2. Write `src/africalim/core/<name>.py` with the actual implementation. Plain Python; raise exceptions on error (Typer's `CliRunner` maps `SystemExit(1)` to `exit_code == 1`).
3. Wire it in `src/africalim/cli/__init__.py` with `app.command(name="<name>")(...)` (or under a Typer subgroup if you want subcommand grouping).
4. Run `uv run hip-cargo generate-cabs --module 'src/africalim/cli/*.py' --output-dir src/africalim/cabs` (the pre-commit hook also does this). Confirm `cabs/<name>.yml` looks sensible.
5. Run `uv run pytest tests/test_roundtrip.py`. The new file is auto-discovered; round-trip should pass byte-identical.

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
