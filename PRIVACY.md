# Privacy policy — africalim

This document describes what africalim records, where it goes, and how you control it. The wording here aligns with the first-run prompt defined in `src/africalim/core/consent_text.py`. If you change one, re-read the other.

## What africalim records on your machine

Every interaction with an africalim agent is written to a local SQLite database under your platform's user data directory (XDG-compliant; `~/.local/share/africalim/` on Linux, `~/Library/Application Support/africalim/` on macOS, `%LOCALAPPDATA%\africalim\` on Windows). Each record contains:

- The exact question you asked.
- The structured answer the agent returned, including any source citations.
- The full tool-call trace (which files were searched, which were read, what the search results were).
- The model provider and model name used.
- The agent name, agent version, and harness version.
- The corpus snapshot (commit hash of each repo in your configured corpus at the time of the call).
- A duration in milliseconds and, when known, an estimated cost in USD.
- The error trace, if the call failed.

## What stays local, always

- The SQLite database stays on your machine. africalim does not transmit it.
- Your API keys are read **only** from environment variables, never from any config file, and are **never** logged.

## What opting in means

On first run, africalim asks you to opt in or opt out. The default is **opt out** (privacy-by-default).

- **Opting in** marks each subsequent record as eligible for upload to a future project-run aggregator endpoint. **In v0.1.0 the endpoint is not yet active** — opting in only sets the `upload_status` field to `pending`; nothing is transmitted regardless of your choice.
- **Opting out** marks each record as `skipped`. The endpoint will refuse skipped records even after it goes live, and changing your mind only affects future records (you have to explicitly re-opt-in to re-classify subsequent calls).
- You can change your mind at any time:

  ```bash
  africalim config set consent.status opt_in
  africalim config set consent.status opt_out
  ```

## Inspect what's been logged

```bash
africalim export --consent all --output ~/africalim-dump.jsonl
```

`--consent` filters: `opt_in` (default, safest), `opt_out`, `unset`, or `all`.

## Delete what's been logged

The SQLite database is one file. Remove it:

```bash
rm "$(africalim config path data)"     # once `config path data` is wired up in M5
# or, today:
rm ~/.local/share/africalim/interactions.db
```

## Retention

Local records are retained until you delete them. Future remote records (when the aggregator goes live) will follow a published retention policy that will land here before the endpoint activates. Changes to retention will be announced via release notes.

## Your rights

Under POPIA (South Africa) and GDPR (EU/UK), you have rights of access, correction, deletion, and withdrawal of consent. To exercise any of these, file an issue at <https://github.com/landmanbester/africalim/issues> (for any data we receive once the aggregator is live) or — for local data only — manage the SQLite file directly.

## Legal basis

Personal data subject to POPIA / GDPR is processed only on the basis of your explicit, opt-in consent. You may withdraw consent at any time without affecting any local records you have already chosen to keep.

## Contact

Open an issue at <https://github.com/landmanbester/africalim/issues> for any data-subject request.

---

*This wording will be reviewed by a POPIA/GDPR-literate human before the v0.1.0 announcement (`plans/africalim_technical_spec.md` §10.5). Material changes between now and then will be tracked in commit history.*
