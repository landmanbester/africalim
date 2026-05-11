"""Harness layer — retrieval primitives.

This module provides the four retrieval primitives the harness exposes to
agents (via tool wrappers in the agent layer): code search, file reading,
repository structure listing, and git version snapshotting.

These functions are deliberately plain, fully unit-testable, and have no
dependency on pydantic-ai. Heavy dependencies (``gitpython``) are imported
lazily inside the functions that need them so the module stays cheap to
import.

``search_codebase`` shells out to ``rg`` (ripgrep) when the binary is on
``PATH`` and falls back to a Python ``re``-based walker otherwise. Both
backends produce the same ``SearchHit`` shape.

``list_repo_structure`` honours a small built-in ignore set (``.git``,
``__pycache__``, ``.venv``, ``node_modules``, ``.pytest_cache``,
``.ruff_cache``). ``.gitignore`` honouring is **not** implemented in this
release: it would require the ``pathspec`` dependency, which is not currently
in the project's dependency tree, and the plan explicitly forbids adding new
dependencies for this. If/when ``pathspec`` is added, extend
``list_repo_structure`` accordingly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# Built-in ignore set used by the fallback search walker and by
# ``list_repo_structure``. Kept small and uncontroversial.
_BUILTIN_IGNORES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Hard cap on the length of any single matched line we surface, to avoid
# log bloat from minified JS, generated YAML, etc.
_MAX_LINE_LEN: int = 1000


class SearchHit(BaseModel):
    """A single line-level match produced by ``search_codebase``."""

    model_config = ConfigDict(frozen=True)

    repo: str
    file_path: str
    line_number: int
    line_text: str
    context_before: list[str] = []
    context_after: list[str] = []


class FileContent(BaseModel):
    """The (possibly sliced) contents of a single file."""

    model_config = ConfigDict(frozen=True)

    path: str
    content: str
    line_range: tuple[int, int] | None
    total_lines: int
    truncated: bool


class RepoEntry(BaseModel):
    """One node in a ``RepoStructure`` tree."""

    model_config = ConfigDict(frozen=True)

    path: str
    is_dir: bool
    depth: int


class RepoStructure(BaseModel):
    """A directory tree snapshot of a repository."""

    model_config = ConfigDict(frozen=True)

    repo_path: str
    tree: list[RepoEntry]


class RepoVersion(BaseModel):
    """Commit-level identity of a repository at a point in time."""

    model_config = ConfigDict(frozen=True)

    repo_path: str
    commit_hash: str | None
    branch: str | None
    is_dirty: bool


def _truncate_line(text: str) -> str:
    """Strip a trailing newline and cap line length at ``_MAX_LINE_LEN``."""
    text = text.rstrip("\n")
    if len(text) > _MAX_LINE_LEN:
        text = text[:_MAX_LINE_LEN]
    return text


def _rg_search(
    query: str,
    repo_path: Path,
    max_results: int,
    file_globs: list[str] | None,
) -> list[SearchHit]:
    """Run ripgrep and parse its JSON event stream into ``SearchHit`` objects."""
    cmd: list[str] = [
        "rg",
        "--json",
        "--max-count",
        str(max_results),
        "--no-heading",
        "-e",
        query,
    ]
    if file_globs:
        for glob in file_globs:
            cmd.extend(["--glob", glob])
    cmd.append(str(repo_path))

    # ripgrep exits 1 when there are no matches; that is not an error for us.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    repo_name = repo_path.name
    hits: list[SearchHit] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_text = data.get("path", {}).get("text")
        line_text_raw = data.get("lines", {}).get("text", "")
        line_number = data.get("line_number")
        if path_text is None or line_number is None:
            continue
        try:
            rel = str(Path(path_text).resolve().relative_to(repo_path.resolve()))
        except ValueError:
            rel = path_text
        hits.append(
            SearchHit(
                repo=repo_name,
                file_path=rel,
                line_number=int(line_number),
                line_text=_truncate_line(line_text_raw),
            )
        )
        if len(hits) >= max_results:
            break
    return hits


def _matches_any_glob(name: str, globs: list[str]) -> bool:
    from fnmatch import fnmatch

    return any(fnmatch(name, g) for g in globs)


def _fallback_search(
    query: str,
    repo_path: Path,
    max_results: int,
    file_globs: list[str] | None,
) -> list[SearchHit]:
    """Pure-Python fallback used when ``rg`` is missing.

    Walks ``repo_path``, skipping the built-in ignore set, and runs a
    case-sensitive ``re.search`` over each file's lines. Produces the same
    ``SearchHit`` shape as the ripgrep backend.
    """
    pattern = re.compile(re.escape(query))
    repo_name = repo_path.name
    hits: list[SearchHit] = []

    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        # Skip anything that lives under an ignored directory.
        if any(part in _BUILTIN_IGNORES for part in path.relative_to(repo_path).parts):
            continue
        if file_globs and not _matches_any_glob(path.name, file_globs):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if pattern.search(line):
                        hits.append(
                            SearchHit(
                                repo=repo_name,
                                file_path=str(path.relative_to(repo_path)),
                                line_number=lineno,
                                line_text=_truncate_line(line),
                            )
                        )
                        if len(hits) >= max_results:
                            return hits
        except OSError:
            # Unreadable file (permissions, broken symlink, etc.) — skip.
            continue
    return hits


def search_codebase(
    query: str,
    repo_path: Path,
    max_results: int = 20,
    file_globs: list[str] | None = None,
) -> list[SearchHit]:
    """Run ripgrep over a repo and return structured hits.

    Falls back to a Python ``re``-based walker if ``rg`` is not on ``PATH``.
    Both backends produce the same ``SearchHit`` shape.

    Args:
        query: Literal string to search for. Special regex characters are
            escaped in the fallback path; ripgrep uses its own regex engine
            but receives the same string verbatim, so callers should pass a
            literal unless they have audited the consequences.
        repo_path: Root directory to search.
        max_results: Hard cap on the number of hits returned.
        file_globs: Optional list of glob patterns (e.g. ``["*.py"]``)
            passed to ripgrep's ``--glob`` flag. The fallback applies them
            to file names only.
    """
    if shutil.which("rg") is not None:
        return _rg_search(query, repo_path, max_results, file_globs)
    return _fallback_search(query, repo_path, max_results, file_globs)


def read_file(
    path: Path,
    line_range: tuple[int, int] | None = None,
    max_lines: int = 500,
) -> FileContent:
    """Read a file (or a slice of lines) with safety bounds.

    Args:
        path: Absolute path to the file.
        line_range: Optional ``(start, end)`` tuple, 1-indexed and inclusive.
            ``end`` is clamped to the file's length; values larger than the
            file simply return whatever is available.
        max_lines: Hard cap on the number of lines returned. If the
            requested window exceeds this cap, the result is truncated and
            ``truncated`` is set to ``True``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If ``line_range`` is malformed (non-positive bounds or
            ``start > end``).
    """
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")
    if line_range is not None:
        start, end = line_range
        if start < 1 or end < 1 or start > end:
            raise ValueError(f"Invalid line_range {line_range!r}: expected 1-indexed (start, end) with start <= end")

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        all_lines = fh.readlines()
    total_lines = len(all_lines)

    if line_range is None:
        window = all_lines
        window_size = total_lines
    else:
        start, end = line_range
        # Clamp end to total_lines; allow start > total_lines to yield empty.
        end_clamped = min(end, total_lines)
        if start > total_lines:
            window = []
        else:
            window = all_lines[start - 1 : end_clamped]
        # The "computed window" — what the user asked for, clamped to file bounds.
        window_size = max(0, min(end, total_lines) - start + 1) if start <= total_lines else 0

    truncated = False
    if len(window) > max_lines:
        window = window[:max_lines]
        truncated = True
    elif window_size > max_lines:
        # Defensive: window_size larger than max_lines means we already capped above.
        truncated = True

    content = "".join(window)
    return FileContent(
        path=str(path.resolve()),
        content=content,
        line_range=line_range,
        total_lines=total_lines,
        truncated=truncated,
    )


def list_repo_structure(
    repo_path: Path,
    max_depth: int = 3,
) -> RepoStructure:
    """Produce a directory tree of a repo, respecting common ignore patterns.

    Skips entries listed in the built-in ignore set (``.git``,
    ``__pycache__``, ``.venv``, ``node_modules``, ``.pytest_cache``,
    ``.ruff_cache``).

    .. note::
       ``.gitignore`` honouring is **not** implemented because it would
       require adding the ``pathspec`` dependency, which is currently out
       of scope. If ``pathspec`` is added later, extend this function to
       parse the repo-root ``.gitignore`` and filter accordingly.
    """
    repo_path = repo_path.resolve()
    entries: list[RepoEntry] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return
        for child in children:
            if child.name in _BUILTIN_IGNORES:
                continue
            rel = str(child.relative_to(repo_path))
            entries.append(RepoEntry(path=rel, is_dir=child.is_dir(), depth=depth))
            if child.is_dir():
                walk(child, depth + 1)

    walk(repo_path, depth=1)
    return RepoStructure(repo_path=str(repo_path), tree=entries)


def get_repo_version(repo_path: Path) -> RepoVersion:
    """Return commit hash, branch, and dirty status of a repo.

    For a non-git directory, returns ``RepoVersion(commit_hash=None,
    branch=None, is_dirty=False)``. Does **not** raise.

    Conventions:

    * Detached HEAD: ``branch`` is set to the first 7 characters of the
      commit hash (so ``branch`` is always informative for the log).
    * Dirty status: untracked files do **not** count as dirty
      (``repo.is_dirty(untracked_files=False)``). Only tracked-file
      modifications, staged changes, etc. do.
    """
    # Lazy import: gitpython is medium-weight and not needed at module load.
    import git  # type: ignore[import-untyped]

    repo_path_str = str(repo_path.resolve())
    try:
        repo = git.Repo(repo_path, search_parent_directories=False)
    except git.exc.InvalidGitRepositoryError:
        return RepoVersion(repo_path=repo_path_str, commit_hash=None, branch=None, is_dirty=False)
    except git.exc.NoSuchPathError:
        return RepoVersion(repo_path=repo_path_str, commit_hash=None, branch=None, is_dirty=False)

    try:
        commit_hash = repo.head.commit.hexsha
    except (ValueError, git.exc.GitCommandError):
        # Empty repo: no HEAD commit yet.
        return RepoVersion(
            repo_path=repo_path_str,
            commit_hash=None,
            branch=None,
            is_dirty=repo.is_dirty(untracked_files=False),
        )

    if repo.head.is_detached:
        branch: str | None = commit_hash[:7]
    else:
        try:
            branch = repo.active_branch.name
        except TypeError:
            branch = commit_hash[:7]

    is_dirty = repo.is_dirty(untracked_files=False)
    return RepoVersion(
        repo_path=repo_path_str,
        commit_hash=commit_hash,
        branch=branch,
        is_dirty=is_dirty,
    )
