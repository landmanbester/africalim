"""Plain-string constants for the consent flow.

Kept separate from :mod:`africalim.utils.consent` so wording can be reviewed
(and eventually translated) without touching control flow. No logic lives
here — only ``str`` literals.

Wording is aligned with ``PRIVACY.md`` at the repo root. If you change one,
re-read the other and keep them honest.
"""

from __future__ import annotations

LINK_TO_PRIVACY_MD: str = "https://github.com/landmanbester/africalim/blob/main/PRIVACY.md"
"""Canonical URL for the hosted privacy policy.

Referenced inside :data:`FIRST_RUN_PROMPT` and exposed for the future
``africalim config`` command so users can re-read the policy on demand.
"""


PRIVACY_SUMMARY: str = """\
What africalim records on your machine:

  - Your question and the agent's answer (with source citations).
  - The tool-call trace (which files it searched and read).
  - Model provider, model name, agent name and version, harness version.
  - Corpus commit hashes, call duration, and (when known) an estimated cost.
  - The error trace if a call fails.

What stays local, always:

  - The SQLite log file under your platform user data directory.
  - Your API keys (read only from environment variables, never logged).

What opting in means:

  - Records are marked as eligible for upload to a future project-run
    aggregator endpoint. In v0.1.0 the endpoint is not yet active, so
    nothing is transmitted regardless of your choice.
  - You can change your mind at any time via `africalim config set
    consent.status opt_in` or `opt_out`.

You can dump everything that has been logged with
`africalim export --consent all`. Delete the SQLite file to wipe it.
"""
"""Short bullet-list summary of the privacy posture.

Embedded inside :data:`FIRST_RUN_PROMPT` and exposed verbatim so the
``africalim config`` subcommand (M5) can print it on demand.
"""


FIRST_RUN_PROMPT: str = f"""\
africalim — first-run privacy check

africalim logs your interactions with its agents to a local SQLite
database. This helps you review what was asked and answered, and (only
if you opt in) lets future versions help improve the project's agents
by uploading anonymised interaction records.

{PRIVACY_SUMMARY}
Your rights under POPIA (South Africa) and GDPR (EU/UK) include access,
correction, deletion, and withdrawal of consent. africalim's default is
*opt out*; you have to actively choose to share.

Full policy: {LINK_TO_PRIVACY_MD}

Do you want to opt in to sharing future interaction records with the
africalim project?"""
"""Body shown to the user on first run.

Ends with a yes/no question so :func:`typer.confirm` can render it
straight without further formatting. The default behaviour at the call
site is *opt out* (privacy-by-default).
"""


OPT_IN_CONFIRMATION: str = (
    "Thanks — interactions will be marked as eligible for upload. You can change "
    "your mind at any time with `africalim config set consent.status opt_out`."
)
"""Echoed after the user opts in."""


OPT_OUT_CONFIRMATION: str = (
    "Got it — interactions stay local only. You can opt in later with `africalim config set consent.status opt_in`."
)
"""Echoed after the user opts out."""
