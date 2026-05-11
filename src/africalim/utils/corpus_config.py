"""Corpus-config file schema and CRUD helpers.

The corpus config lives at ``~/.config/africalim/corpus.toml`` by
default and lists the git-tracked corpora the harness exposes to
agents. The data models themselves live in
:mod:`africalim.utils.deps` (where the :class:`HarnessDeps` container
needs them) and are re-exported here so the agent layer can stay
decoupled from the harness internals.

TOML shape::

    [[repo]]
    name = "pfb-imaging"
    path = "~/.cache/africalim/corpus/pfb-imaging"
    url = "https://github.com/ratt-ru/pfb-imaging"
    ref = "main"
    # Optional commit_hash = "abc123..." pin
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils.deps import CorpusConfig, CorpusRepo

__all__ = [
    "CorpusConfig",
    "CorpusRepo",
    "default_corpus_path",
    "load_corpus",
    "save_corpus",
]


def default_corpus_path() -> Path:
    """Return the platform-default ``corpus.toml`` location."""
    return platformdirs.user_config_path("africalim") / "corpus.toml"


def _read_raw_toml(path: Path) -> dict[str, Any]:
    """Read ``path`` as a TOML mapping, returning ``{}`` if absent."""
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _write_raw_toml(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path``, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)


def load_corpus(path: Path | None = None) -> CorpusConfig:
    """Read the corpus config from ``path`` (default: platform path).

    Returns ``CorpusConfig(repos=[])`` for a missing file. Each entry
    is validated through :class:`CorpusRepo`, so a malformed entry
    raises :class:`pydantic.ValidationError`.
    """
    target = path if path is not None else default_corpus_path()
    raw = _read_raw_toml(target)
    repo_entries = raw.get("repo", [])
    if not isinstance(repo_entries, list):
        raise ValueError(
            f"expected [[repo]] array of tables in {target}, got {type(repo_entries).__name__}",
        )
    repos = [CorpusRepo.model_validate(entry) for entry in repo_entries]
    return CorpusConfig(repos=repos)


def save_corpus(config: CorpusConfig, path: Path | None = None) -> None:
    """Persist ``config`` as TOML to ``path`` (default: platform path).

    ``Path`` instances on each :class:`CorpusRepo` are written back as
    strings; ``None``-valued optional fields (e.g. ``commit_hash``,
    ``url``) are omitted so the on-disk file stays clean.
    """
    target = path if path is not None else default_corpus_path()
    repo_entries: list[dict[str, Any]] = []
    for repo in config.repos:
        entry: dict[str, Any] = {
            "name": repo.name,
            "path": str(repo.path),
            "ref": repo.ref,
        }
        if repo.url is not None:
            entry["url"] = repo.url
        if repo.commit_hash is not None:
            entry["commit_hash"] = repo.commit_hash
        repo_entries.append(entry)
    _write_raw_toml(target, {"repo": repo_entries})
