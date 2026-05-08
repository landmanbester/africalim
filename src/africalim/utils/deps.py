"""Harness layer — dependency container.

Defines the static-config Pydantic models (:class:`CorpusRepo`,
:class:`CorpusConfig`) and the runtime container (:class:`HarnessDeps`)
that the harness builds once at CLI startup and threads through every
agent invocation.

Architectural invariants (see ``CLAUDE.md`` and
``plans/initialise_africalim.md`` §1):

1. Agents access shared infrastructure **only** via
   ``RunContext[HarnessDeps].deps``; they must never import the
   underlying modules directly.
2. :class:`HarnessDeps` is a frozen dataclass — once built, its
   identity is stable for the lifetime of the run.
3. :class:`CorpusRepo` and :class:`CorpusConfig` are frozen Pydantic
   models so the CLI can hand them to multiple agents without worrying
   about mid-run mutation.

``CorpusRepo.path`` is normalised with :meth:`pathlib.Path.expanduser`
at validation time so user-config files can use ``~``-prefixed paths,
but **not** ``.resolve()``-d. Resolution depends on the current working
directory at config-read time, which is not necessarily the directory
the agent will run in; the agent code can resolve at point of use if
it cares.

File existence is **not** checked here. Corpora may be cloned lazily,
and we'd rather fail loudly at the agent's first repo access than at
config load.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from africalim.utils.consent import ConsentManager
from africalim.utils.logger import InteractionLogger


class CorpusRepo(BaseModel):
    """One git-tracked corpus the harness exposes to agents.

    :param name: Short identifier the agent uses to refer to the repo
        (for example ``"stimela2"``). Must match the name agents pass to
        :meth:`CorpusConfig.by_name`.
    :param path: On-disk location of the working tree. ``~`` is expanded
        at validation time; the path is **not** resolved against the
        current working directory and is **not** required to exist.
    :param url: Optional upstream URL. Stored for reference / future
        ``africalim corpus sync``; not used in v0.1.0.
    :param ref: Branch, tag, or commit-ish the harness expects. Defaults
        to ``"main"``. Used by version-stamping logic in the runner.
    :param commit_hash: Optional explicit commit pin. When set, takes
        precedence over :attr:`ref` for version-stamping purposes.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    path: Path
    url: str | None = None
    ref: str = "main"
    commit_hash: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _expand_user(cls, value: object) -> Path:
        """Normalise ``path`` with :meth:`Path.expanduser` only.

        We deliberately avoid :meth:`Path.resolve`: relative paths
        encountered at config-load time may be intended relative to the
        config file's directory or to the eventual cwd, and the harness
        cannot know which. Callers that need an absolute path should
        resolve at point of use.
        """
        return Path(value).expanduser()  # type: ignore[arg-type]


class CorpusConfig(BaseModel):
    """Ordered registry of :class:`CorpusRepo` values, keyed by name.

    Order is the order of declaration in :attr:`repos`; :meth:`names`
    preserves it so CLI output and corpus-summary rendering are
    deterministic.
    """

    model_config = ConfigDict(frozen=True)

    repos: list[CorpusRepo] = Field(default_factory=list)

    def by_name(self, name: str) -> CorpusRepo:
        """Return the registered repo with ``name``.

        :raises KeyError: with a message listing all known names when
            ``name`` is not registered, so the agent error surface is
            actionable rather than a bare ``KeyError(name)``.
        """
        for repo in self.repos:
            if repo.name == name:
                return repo
        known = ", ".join(repo.name for repo in self.repos) or "<none>"
        raise KeyError(
            f"unknown corpus repo {name!r}; known repos: {known}",
        )

    def names(self) -> list[str]:
        """Return the registered repo names in declaration order."""
        return [repo.name for repo in self.repos]


@dataclass(frozen=True)
class HarnessDeps:
    """Shared infrastructure injected into every agent run.

    Built once at CLI startup; passed into every agent invocation via
    ``pydantic_ai.RunContext.deps``. Agents must access these through
    ``ctx.deps.<field>`` and never import the underlying modules
    directly.

    :param corpus: Static catalogue of corpora the agent may search.
    :param logger: SQLite-backed interaction logger. Owned by the
        harness; closed by the CLI on shutdown.
    :param consent: Read-only view onto the user's persisted consent
        state.
    :param harness_version: Version string written into every
        :class:`~africalim.utils.logger.InteractionRecord`. Sourced from
        ``africalim.__version__`` at CLI startup.
    """

    corpus: CorpusConfig
    logger: InteractionLogger
    consent: ConsentManager
    harness_version: str
