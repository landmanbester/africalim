"""Harness layer — consent management.

This module owns the ``[consent]`` section of the user-config TOML file.
It is intentionally self-contained: M5 will layer a broader user-config
reader on top of the same file *without* breaking the format owned here.

Only the ``[consent]`` block is read or written by :class:`ConsentManager`.
Any other top-level keys/sections that already exist on disk are
preserved on write so future config code can coexist.

The TOML shape is::

    [consent]
    status = "unset"           # one of: "opt_in" | "opt_out" | "unset"
    prompt_shown = false

``__init__`` does **not** create the file; it only records the path. The
file is created lazily by :meth:`ConsentManager.set_status`. This keeps
``get_status`` cheap and side-effect free.

The first-run prompt is privacy-by-default: on EOF / non-interactive
stdin (``typer.Abort``), status stays ``"unset"`` and ``prompt_shown``
stays ``False`` so the next run prompts again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import platformdirs
import tomli_w
import typer

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils.consent_text import (
    FIRST_RUN_PROMPT,
    OPT_IN_CONFIRMATION,
    OPT_OUT_CONFIRMATION,
)
from africalim.utils.logger import ConsentStatus

_VALID_STATUSES: frozenset[str] = frozenset({"opt_in", "opt_out", "unset"})


def default_config_path() -> Path:
    """Return the XDG-compliant default config-file path.

    Equivalent to ``platformdirs.user_config_path("africalim") /
    "config.toml"``. The directory is **not** created here — callers
    decide whether to create it (typically only :class:`ConsentManager`
    does, lazily, on first write).
    """
    return platformdirs.user_config_path("africalim") / "config.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file into a dict, returning ``{}`` if it's missing."""
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _dump_toml(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as TOML to ``path``, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)


class ConsentManager:
    """Read/write the ``[consent]`` section of the user-config TOML.

    The manager is intentionally narrow: it owns exactly two keys
    (``status`` and ``prompt_shown``) under the ``[consent]`` table and
    leaves everything else in the file untouched. M5's broader config
    layer composes around it.
    """

    def __init__(self, config_path: Path) -> None:
        """Record the config-file path. The file is **not** created here.

        :param config_path: Absolute or relative path to the TOML file.
            Tests should pass an explicit ``tmp_path``; production code
            uses :func:`default_config_path`.
        """
        self._path: Path = config_path

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def get_status(self) -> ConsentStatus:
        """Return the persisted consent status.

        Returns ``"unset"`` when the file is missing, when the
        ``[consent]`` table is missing, or when the recorded value is
        not one of the known statuses (defensive: a hand-edited config
        should never crash the agent).
        """
        data = _load_toml(self._path)
        consent = data.get("consent", {})
        status = consent.get("status", "unset")
        if status not in _VALID_STATUSES:
            return "unset"
        return status  # type: ignore[return-value]

    def set_status(self, status: ConsentStatus) -> None:
        """Persist ``status`` and mark the prompt as shown.

        Other top-level keys/sections in the file are preserved. Any
        explicit call here is treated as user-acknowledged, so
        ``prompt_shown`` is always set to ``True``.
        """
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid consent status {status!r}; expected one of {sorted(_VALID_STATUSES)}")
        data = _load_toml(self._path)
        consent = data.get("consent")
        if not isinstance(consent, dict):
            consent = {}
        consent["status"] = status
        consent["prompt_shown"] = True
        data["consent"] = consent
        _dump_toml(self._path, data)

    # ------------------------------------------------------------------ #
    # First-run prompt
    # ------------------------------------------------------------------ #

    def first_run_prompt(self) -> ConsentStatus:
        """Show the first-run prompt if it hasn't been shown yet.

        Behaviour:

        - If :attr:`prompt_shown` is already ``True``, return the
          existing :meth:`get_status` without prompting.
        - Otherwise call ``typer.confirm`` with the privacy-by-default
          ``default=False`` and persist the answer:

          - ``True`` → ``"opt_in"``
          - ``False`` → ``"opt_out"``
          - :exc:`typer.Abort` (EOF / non-interactive) → leave status
            ``"unset"`` and ``prompt_shown`` ``False`` so the next run
            prompts again.

        Echoes the matching confirmation message (opt-in / opt-out)
        after a successful prompt.
        """
        if self.prompt_shown:
            return self.get_status()

        try:
            answer = typer.confirm(FIRST_RUN_PROMPT, default=False)
        except typer.Abort:
            # Non-interactive or user-cancelled: keep state as 'unset'
            # and re-prompt next run.
            return self.get_status()

        if answer:
            self.set_status("opt_in")
            typer.echo(OPT_IN_CONFIRMATION)
        else:
            self.set_status("opt_out")
            typer.echo(OPT_OUT_CONFIRMATION)
        return self.get_status()

    # ------------------------------------------------------------------ #
    # Read-only properties
    # ------------------------------------------------------------------ #

    @property
    def prompt_shown(self) -> bool:
        """Whether the first-run prompt has already been answered.

        Read directly from disk so external edits to the config file
        are picked up on the next access.
        """
        data = _load_toml(self._path)
        consent = data.get("consent", {})
        return bool(consent.get("prompt_shown", False))
