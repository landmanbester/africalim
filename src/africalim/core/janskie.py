"""Janskie — radio-interferometry tooling Q&A agent.

Single-file implementation backing ``africalim janskie``. Heavy
dependencies (``pydantic-ai``, ``rich``, ``platformdirs``) are imported
lazily inside :func:`janskie` so importing this module from cab
generators or test fixtures stays cheap.

The module exposes:

- :class:`SourceCitation` / :class:`JanskieOutput` — pydantic schemas
  for the structured agent output.
- :func:`build_agent` — constructs a pydantic-ai ``Agent`` wired to
  :class:`HarnessDeps` with three corpus-search tools.
- :func:`janskie` — the actual command implementation. The Typer
  wrapper at :mod:`africalim.cli.janskie` lazy-imports this function;
  hip-cargo's cab generator also points the generated cab's
  ``command:`` field at ``africalim.core.janskie.janskie``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from africalim.utils.deps import CorpusConfig, HarnessDeps
from africalim.utils.retrieval import FileContent, RepoStructure, SearchHit

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


JANSKIE_AGENT_NAME: str = "janskie"
JANSKIE_AGENT_VERSION: str = "0.1.0"

_EMPTY_CORPUS_SUMMARY: str = (
    "(No corpus repositories are configured. Refuse to answer "
    "code-specific questions until the user runs `africalim config` to "
    "point at one.)"
)

# The system prompt template. ``{corpus_summary}`` is filled at agent
# build time; the JSON example uses doubled braces to survive
# ``str.format``.
_SYSTEM_PROMPT_TEMPLATE: str = """\
# Janskie — radio-interferometry tooling assistant

You are **janskie**, an assistant that answers questions about
radio-interferometry software: imagers, calibrators, pipeline
frameworks, and the surrounding ecosystem.

## Available corpus

The harness has indexed the following repositories. You may only make
specific factual claims that you can ground in one of these:

{corpus_summary}

If the available corpus is empty, refuse code-specific questions and
direct the user to run `africalim config` to point at one or more
corpus repositories.

## Hard rules

1. **Read code before you answer.** Prefer using the
   `search_codebase`, `read_file`, and `list_repo_structure` tools to
   ground every factual claim. Do not rely on memory of public
   documentation: the user is asking *because* documentation is
   incomplete or out of date.
2. **Cite every claim.** Every factual statement in `answer` must be
   backed by at least one entry in `sources`. A `SourceCitation` must
   reference a concrete `repo`, `file_path`, and (where you read a
   slice) a 1-indexed inclusive `line_range`. Cite the file even when
   you only skimmed its structure.
3. **Refuse, don't speculate.** If the question is outside the
   indexed corpus, or you cannot find supporting evidence after a
   reasonable search, say so. Set `confidence="low"`, leave `sources`
   empty (or include only the structural searches you ran), and
   explain the gap in `caveats`.
4. **Be honest about uncertainty.** Use `confidence`:
   - `"high"`: the claim is directly supported by code you read in
     this turn.
   - `"medium"`: the claim is partially supported (e.g. you read the
     surrounding module but not the exact function) or relies on
     reasonable inference.
   - `"low"`: you could not verify the claim against the corpus.
5. **Use `caveats` for gotchas.** Surface version-specific behaviour,
   open issues you noticed in the code, and follow-up reads the user
   should do.

## Output schema

Your reply is parsed as a `JanskieOutput`:

```
{{
  "answer":     "<natural-language answer>",
  "sources":    [{{"repo": "...", "file_path": "...", "line_range": [start, end], "commit_hash": "..."}}],
  "confidence": "high" | "medium" | "low",
  "caveats":    ["..."]
}}
```

The `commit_hash` field is stamped by the harness from the corpus
snapshot taken when this run started; if you know the repo's commit
hash from a tool result use it, otherwise leave it as the empty string
and the caller will fill it in.

Keep `answer` concise and structured. Bullet lists and short code
blocks are welcome when they help; long prose is not.
"""


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class SourceCitation(BaseModel):
    """A single citation pointing at a concrete location in the corpus.

    :param repo: Name of the corpus repo as registered in
        :class:`africalim.utils.deps.CorpusConfig`.
    :param file_path: Repo-relative path of the cited file.
    :param line_range: Optional 1-indexed inclusive ``(start, end)``
        line range. Omit when the citation refers to a whole file.
    :param commit_hash: The commit hash of the corpus repo at the time
        the citation was produced. Stamped at run time so a stored
        :class:`~africalim.utils.logger.InteractionRecord` is reproducible.
    """

    repo: str
    file_path: str
    line_range: tuple[int, int] | None = None
    commit_hash: str


class JanskieOutput(BaseModel):
    """Structured reply produced by the janskie agent.

    :param answer: Natural-language answer to the user's question.
    :param sources: Concrete citations backing the claims in
        :attr:`answer`. May be empty only when :attr:`confidence` is
        ``"low"`` and :attr:`caveats` explains why no source could be
        produced.
    :param confidence: Self-reported confidence band. ``"high"`` requires
        at least one citation read from the corpus; ``"medium"`` is for
        partially-supported claims; ``"low"`` is for "I don't know" /
        "outside the corpus" answers.
    :param caveats: Optional list of caveats, gotchas, or follow-up
        suggestions surfaced alongside the answer.
    """

    answer: str
    sources: list[SourceCitation]
    confidence: Literal["high", "medium", "low"]
    caveats: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent construction
# --------------------------------------------------------------------------- #


def _render_corpus_summary(corpus: CorpusConfig) -> str:
    """Render a bulleted list of corpus repos for the system prompt.

    URLs are intentionally omitted: the model only needs the name, ref,
    and on-disk path to issue tool calls. Returns the no-corpus sentinel
    when ``corpus.repos`` is empty.
    """
    if not corpus.repos:
        return _EMPTY_CORPUS_SUMMARY
    lines = [f"- {repo.name} (ref: {repo.ref}) at {repo.path}" for repo in corpus.repos]
    return "\n".join(lines)


def _backfill_commit_hashes(output: JanskieOutput, corpus_versions: dict[str, str]) -> None:
    """Fill in empty ``commit_hash`` on each citation from ``corpus_versions``.

    The system prompt tells the model to leave ``commit_hash`` empty
    when it does not know the value, with the harness backfilling from
    the corpus snapshot taken at run start. The lookup is by repo name;
    citations referencing a repo that is not in ``corpus_versions`` are
    left untouched. Mutates ``output`` in place.
    """
    for src in output.sources:
        if not src.commit_hash:
            backfill = corpus_versions.get(src.repo)
            if backfill:
                src.commit_hash = backfill


def _load_corpus_with_warnings(*, stderr: object | None = None) -> CorpusConfig:
    """Load the user corpus config, dropping repos whose path is missing.

    Each dropped repo emits one ``warning: ...`` line to ``stderr``
    (``sys.stderr`` by default). Filtering keeps the rendered system
    prompt and the retrieval tools in sync: the agent only sees repos
    it can actually search. A missing corpus file yields an empty
    config — same refusal behaviour as before this wiring landed.
    """
    import sys

    from africalim.utils.corpus_config import load_corpus

    stream = stderr if stderr is not None else sys.stderr

    raw = load_corpus()
    valid = []
    for repo in raw.repos:
        if repo.path.exists():
            valid.append(repo)
        else:
            print(
                f"warning: corpus repo {repo.name!r} at {repo.path} does not exist; skipping",
                file=stream,
            )
    return CorpusConfig(repos=valid)


def build_agent(
    deps: HarnessDeps,
    *,
    model: str | Model = "anthropic:claude-sonnet-4-6",
) -> Agent[HarnessDeps, JanskieOutput]:
    """Construct the janskie agent wired to harness retrieval primitives.

    Args:
        deps: Harness deps. Used at build time only to render the
            ``{corpus_summary}`` placeholder; per-run resolution still
            happens via ``RunContext[HarnessDeps].deps`` inside each tool.
        model: Either a pydantic-ai model identifier
            ``"<provider>:<model_name>"`` or a concrete
            :class:`pydantic_ai.models.Model` instance. Strings trigger
            eager provider construction (and the matching API-key
            check); a ``Model`` instance bypasses that, which is what
            tests use to stay hermetic. Defaults to the production
            string identifier ``"anthropic:claude-sonnet-4-6"``.

    Returns:
        A configured ``Agent[HarnessDeps, JanskieOutput]`` ready to be
        passed to :func:`africalim.utils.runner.run_agent_sync`.
    """
    rendered = _SYSTEM_PROMPT_TEMPLATE.format(
        corpus_summary=_render_corpus_summary(deps.corpus),
    )

    agent: Agent[HarnessDeps, JanskieOutput] = Agent(
        model,
        deps_type=HarnessDeps,
        output_type=JanskieOutput,
        system_prompt=rendered,
    )

    @agent.tool
    async def search_codebase(
        ctx: RunContext[HarnessDeps],
        repo: str,
        query: str,
        max_results: int = 20,
        file_globs: list[str] | None = None,
    ) -> list[SearchHit]:
        """Search ``query`` inside the corpus repo named ``repo``."""
        from africalim.utils.retrieval import search_codebase as _search

        try:
            repo_meta = ctx.deps.corpus.by_name(repo)
        except KeyError as exc:
            raise ModelRetry(str(exc)) from exc
        return _search(
            query,
            repo_meta.path,
            max_results=max_results,
            file_globs=file_globs,
        )

    @agent.tool
    async def read_file(
        ctx: RunContext[HarnessDeps],
        repo: str,
        file_path: str,
        line_range: tuple[int, int] | None = None,
        max_lines: int = 500,
    ) -> FileContent:
        """Read a file from the corpus repo. ``file_path`` is repo-relative."""
        from africalim.utils.retrieval import read_file as _read

        try:
            repo_meta = ctx.deps.corpus.by_name(repo)
        except KeyError as exc:
            raise ModelRetry(str(exc)) from exc
        repo_root = repo_meta.path.resolve()
        target = (repo_meta.path / file_path).resolve()
        # Path-safety: target must be inside repo_root. Comparing the
        # resolved paths defeats ``..`` traversal and symlink escapes.
        # Surface as ModelRetry so the model can correct the path rather
        # than aborting the whole run on a bad guess.
        if target != repo_root and not str(target).startswith(str(repo_root) + "/"):
            raise ModelRetry(f"file_path {file_path!r} escapes repo {repo!r}")
        try:
            return _read(target, line_range=line_range, max_lines=max_lines)
        except OSError as exc:
            # Catches FileNotFoundError, IsADirectoryError, PermissionError —
            # all of which are recoverable model mistakes (wrong path / not a
            # file) rather than harness bugs.
            raise ModelRetry(f"cannot read {file_path!r} in repo {repo!r}: {exc}") from exc

    @agent.tool
    async def list_repo_structure(
        ctx: RunContext[HarnessDeps],
        repo: str,
        max_depth: int = 3,
    ) -> RepoStructure:
        """List the structure of a corpus repo (top-level by default)."""
        from africalim.utils.retrieval import list_repo_structure as _list

        try:
            repo_meta = ctx.deps.corpus.by_name(repo)
        except KeyError as exc:
            raise ModelRetry(str(exc)) from exc
        return _list(repo_meta.path, max_depth=max_depth)

    return agent


# --------------------------------------------------------------------------- #
# Command entry point — what cli/janskie.py and the generated cab both call.
# --------------------------------------------------------------------------- #


def janskie(
    question: str,
    provider: str | None = None,
    model: str | None = None,
    no_log: bool = False,
) -> None:
    """Ask janskie a question about radio-interferometry tooling.

    Resolves the model identifier, builds a :class:`HarnessDeps`,
    constructs the agent, runs it via
    :func:`africalim.utils.runner.run_agent_sync`, and pretty-prints
    the structured :class:`JanskieOutput`.

    Args:
        question: The user question.
        provider: LLM provider override (e.g. ``"anthropic"``,
            ``"openai"``). ``None`` falls back to user config / spec
            default.
        model: Model name override within ``provider``.
        no_log: When ``True``, skip persisting the interaction.
    """
    import platformdirs
    import typer
    from rich import print as rich_print
    from rich.panel import Panel

    import africalim
    from africalim.utils.consent import ConsentManager, default_config_path
    from africalim.utils.deps import HarnessDeps
    from africalim.utils.logger import InteractionLogger
    from africalim.utils.models import build_model
    from africalim.utils.retrieval import get_repo_version
    from africalim.utils.runner import AgentRunFailure, run_agent_sync

    # 1. Consent. Status may stay "unset" on non-interactive abort; the
    #    runner will then mark the interaction as "skipped" rather than
    #    refusing to log entirely.
    consent = ConsentManager(default_config_path())
    consent.first_run_prompt()

    # 2. Resolve model. ``build_model`` raises a clear MissingAPIKeyError
    #    if the env var for the resolved provider is absent; we let it
    #    propagate so the user sees the actionable message.
    model_str = build_model(provider, model, user_config=None)
    if ":" not in model_str:
        rich_print(
            f"[red]Error:[/red] resolved model identifier {model_str!r} does not "
            f"match the expected '<provider>:<model_name>' form.",
        )
        raise typer.Exit(code=1)
    model_provider, model_name = model_str.split(":", 1)

    # 3. Build harness deps. Load corpus from user config and filter out
    #    repos whose on-disk path is missing so the system prompt and
    #    retrieval tools agree about what is searchable.
    corpus = _load_corpus_with_warnings()
    db_path = platformdirs.user_data_path("africalim") / "interactions.db"
    logger = InteractionLogger(db_path)
    deps = HarnessDeps(
        corpus=corpus,
        logger=logger,
        consent=consent,
        harness_version=africalim.__version__,
    )

    # 4. Build the agent.
    agent = build_agent(deps, model=model_str)

    # 5. Snapshot corpus versions. With an empty corpus this dict stays
    #    empty too; once the corpus-config layer wires real repos it
    #    populates {name: hash} pairs, skipping any whose path is missing.
    corpus_versions: dict[str, str] = {}
    for repo in deps.corpus.repos:
        if not repo.path.exists():
            continue
        version = get_repo_version(repo.path)
        corpus_versions[repo.name] = version.commit_hash or ""

    # 6. Run. The output post-process closure backfills empty
    #    commit_hash values on each citation from the corpus snapshot
    #    taken in step 5 — runs before the row is logged so the
    #    persisted record carries the correct hashes.
    def _backfill(output: JanskieOutput) -> None:
        _backfill_commit_hashes(output, corpus_versions)

    try:
        result = run_agent_sync(
            agent,
            question,
            deps,
            agent_name=JANSKIE_AGENT_NAME,
            agent_version=JANSKIE_AGENT_VERSION,
            model_provider=model_provider,
            model_name=model_name,
            corpus_versions=corpus_versions,
            output_post_process=_backfill,
            no_log=no_log,
        )
    except AgentRunFailure as exc:
        rich_print(f"[red]janskie run failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    # 7. Pretty-print.
    output = result.output
    sections: list[str] = [str(output.answer).strip()]
    if output.sources:
        src_lines = ["", "[bold]Sources[/bold]"]
        for src in output.sources:
            line_range = f":{src.line_range[0]}-{src.line_range[1]}" if src.line_range is not None else ""
            src_lines.append(f"  - {src.repo}/{src.file_path}{line_range} @ {src.commit_hash or '-'}")
        sections.append("\n".join(src_lines))
    if output.caveats:
        cav_lines = ["", "[bold]Caveats[/bold]"]
        cav_lines.extend(f"  - {c}" for c in output.caveats)
        sections.append("\n".join(cav_lines))
    sections.append(f"\n[dim]confidence: {output.confidence}[/dim]")

    rich_print(
        Panel.fit(
            "\n".join(sections),
            title=f"janskie: {question}",
            border_style="cyan",
        )
    )
