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

1. **`cli/X.py` ↔ `core/X.py` ↔ `cabs/X.yml` are 1:1.** Identical filenames; one `@stimela_cab` function per `cli/X.py`; flat `core/`.
2. **`cli/X.py` round-trips through `cabs/X.yml`.** `tests/test_roundtrip.py` enforces byte-identity. The CLI wrapper body is the canonical container-fallback boilerplate; all custom logic lives in `core/X.py`.
3. **Shared infrastructure lives in `utils/`**, not in `core/`. The harness layer (consent, deps, logger, models, pricing, retrieval, runner, user_config, corpus_config) is in `utils/`; `core/` is reserved for one-file-per-CLI-command implementations.
4. **Path-typed CLI params use `File`/`Directory`/`MS`/`URI` `NewType`s + `parser=parse_upath`**, never bare `Path | None`.
5. **Help/info string spacing.** `info=`/`help=` literals must not match `\.[^\s\n]` (period-followed-by-non-space). Avoid `e.g.`, `i.e.`, dotted-key examples in info strings.
6. **Shared infrastructure is injected via `HarnessDeps`**. Agents never `from africalim.utils...` directly — they receive what they need.
7. **Interaction logging happens once, in `utils/runner.py`'s `run_agent` wrapper.** Agents do not log directly.

If your change touches any of these invariants, link to the issue where the deviation was approved.

## Adding a new command (or agent)

1. **Write `src/africalim/cli/<name>.py`** matching the canonical shape. Easiest path: copy any existing `cli/X.py`, rename the function, adapt the parameter list, and update the `core.<name>.<name>` lazy-import target. Keep the `--backend` / `--always-pull-images` skip-marked params and the full `preflight_remote_must_exist → core delegate → run_in_container` body untouched.
2. **Write `src/africalim/core/<name>.py`** with the actual implementation. Plain Python; raise exceptions on bad input (Typer's `CliRunner` maps `SystemExit(1)` to `exit_code == 1`). For agents specifically, `core/<name>.py` collects the schemas, system prompt, `build_agent`, and the entry-point function in one flat file — no `core/<name>/` subpackage.
3. **Wire it into `src/africalim/cli/__init__.py`** with `app.command(name="<name>")(...)` (or under a Typer subgroup if you want subcommand grouping like `africalim config show`).
4. **Run `uv run hip-cargo generate-cabs --module 'src/africalim/cli/*.py' --output-dir src/africalim/cabs`** (the pre-commit hook also does this on every commit). Inspect `cabs/<name>.yml` for sanity.
5. **Run `uv run pytest tests/test_roundtrip.py`.** New `cli/X.py` files are auto-discovered and round-tripped; the test must pass byte-identical.
6. **Add tests** under `tests/unit/test_<name>.py`. Agents use `pydantic_ai.models.test.TestModel` (no real API calls in CI).

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
