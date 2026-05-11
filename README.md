# africalim

> Open-source agentic harness for radio-interferometry tooling.

africalim is a small, focused CLI that runs LLM-powered agents over a configurable corpus of radio-interferometry repositories. The first release ships exactly one agent — **janskie** — a general-purpose Q&A bot that answers questions about radio-imaging tooling and cites the source files it pulled from.

You bring your own API key (Anthropic, OpenAI, Gemini, OpenRouter, Groq — any provider that pydantic-ai supports). africalim never reads keys from disk; only from environment variables.

## Quickstart

```bash
pip install africalim                                   # or uv add africalim
export ANTHROPIC_API_KEY=sk-ant-...                     # or any other supported provider's key
africalim janskie "what does the gridding step in pfb-imaging actually do?"
```

The first run will prompt you about consent (see *Privacy*, below). The default model is `claude-sonnet-4-6`.

### Supported providers

Set the env var matching the provider you want to use:

| Provider    | Env var               |
|-------------|-----------------------|
| Anthropic   | `ANTHROPIC_API_KEY`   |
| OpenAI      | `OPENAI_API_KEY`      |
| Gemini      | `GOOGLE_API_KEY`      |
| OpenRouter  | `OPENROUTER_API_KEY`  |
| Groq        | `GROQ_API_KEY`        |
| Mistral     | `MISTRAL_API_KEY`     |
| Cohere      | `COHERE_API_KEY`      |

Override the default per call:

```bash
africalim janskie --provider openai --model gpt-4o-mini "..."
```

Or persistently, in `~/.config/africalim/config.toml`:

```toml
[model]
default_provider = "anthropic"
default_model    = "claude-sonnet-4-6"
```

(Edit via `africalim config set model.default_model claude-haiku-4-5`.)

### Pointing at a corpus

For v0.1.0 you clone the repos you want janskie to read from and tell africalim where they live. Edit `~/.config/africalim/corpus.toml`:

```toml
[[repo]]
name = "pfb-imaging"
path = "~/.cache/africalim/corpus/pfb-imaging"
url  = "https://github.com/ratt-ru/pfb-imaging"
ref  = "main"

[[repo]]
name = "QuartiCal"
path = "~/.cache/africalim/corpus/QuartiCal"
url  = "https://github.com/ratt-ru/QuartiCal"
ref  = "main"
```

`africalim corpus sync` (auto-cloning) is on the v0.2.0 roadmap; for now, clone manually:

```bash
mkdir -p ~/.cache/africalim/corpus
git clone https://github.com/ratt-ru/pfb-imaging ~/.cache/africalim/corpus/pfb-imaging
git clone https://github.com/ratt-ru/QuartiCal   ~/.cache/africalim/corpus/QuartiCal
```

Verify by asking janskie a corpus-grounded question:

```bash
africalim janskie --question "How does pfb-imaging select a gridder backend?"
```

A working setup produces a `confidence: medium` or `high` answer with one or more entries under `Sources` pointing at concrete files. Three behaviours to know about:

- **No corpus configured.** Janskie refuses code-specific questions and returns `confidence: low` with a caveat telling you to run `africalim config` / edit `corpus.toml`. Same response when `corpus.toml` exists but has no `[[repo]]` entries.
- **Configured repo whose path is missing on disk.** Janskie prints a `warning: corpus repo 'X' at ... does not exist; skipping` line to stderr and continues with the repos that do exist. Use this to spot stale or typo'd paths quickly.
- **All configured repos missing.** Janskie behaves as if no corpus is configured.

## Inspecting and exporting your interactions

Every agent call is logged to a local SQLite database under your platform's user data directory (`~/.local/share/africalim/interactions.db` on Linux). API keys are **never** logged.

```bash
africalim export --consent all --output ~/africalim-dump.jsonl    # everything
africalim export --agent janskie --since 2026-01-01               # filtered
africalim export                                                  # default: only opt_in records
```

Filter values for `--consent`: `opt_in` (default), `opt_out`, `unset`, `all`.

## Privacy

africalim is privacy-by-default: the first run defaults to **opt out**. Opting in marks records as eligible for upload to a future project-run aggregator endpoint (the endpoint itself is not active in v0.1.0 — opting in is informative only). Full policy in [`PRIVACY.md`](./PRIVACY.md).

Change your mind at any time:

```bash
africalim config set consent.status opt_in
africalim config set consent.status opt_out
```

## CLI reference

```
africalim onboard                  # one-time setup hints (CI/CD, PyPI, branch protection)
africalim janskie "<question>"     # ask a question
africalim config show              # print the user config
africalim config set <key> <value> # update a config value (dotted key)
africalim config path              # print the path of the user config file
africalim export [...]             # dump logged interactions as JSONL
```

## What's in scope for v0.1.0

- janskie (Q&A agent with citations)
- BYO-API-key model resolution
- Local SQLite interaction log + opt-in upload flag
- TOML user config + corpus config
- JSONL export

## What's deferred

- Any agent other than janskie (e.g. a calibration specialist).
- The remote interaction-aggregator endpoint.
- Auto-cloning corpus repos (`africalim corpus sync`).
- The Streamlit review app (`africalim review`).
- Embedding-based retrieval (BM25/ripgrep is enough until a concrete failure case demands more).

See `plans/africalim_technical_spec.md` §8 for the full out-of-scope list and `CONTRIBUTING.md` for how to propose new work.

## Development

```bash
git clone https://github.com/landmanbester/africalim
cd africalim
uv sync --group dev --group test
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
uv run pytest
```

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full guide, including the architectural invariants every PR is checked against.

## License

MIT — see [`LICENSE`](./LICENSE).
