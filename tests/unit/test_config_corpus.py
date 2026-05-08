"""Unit tests for :mod:`africalim.utils.corpus_config`."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils.corpus_config import (
    CorpusConfig,
    CorpusRepo,
    default_corpus_path,
    load_corpus,
    save_corpus,
)


def _read_raw(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_default_corpus_path_under_user_config() -> None:
    assert default_corpus_path().name == "corpus.toml"
    assert "africalim" in str(default_corpus_path())


def test_load_returns_empty_for_missing_file(tmp_path: Path) -> None:
    config = load_corpus(tmp_path / "corpus.toml")
    assert isinstance(config, CorpusConfig)
    assert config.repos == []


def test_round_trip_basic(tmp_path: Path) -> None:
    path = tmp_path / "corpus.toml"
    original = CorpusConfig(
        repos=[
            CorpusRepo(
                name="pfb-imaging",
                path=Path("~/.cache/africalim/corpus/pfb-imaging"),
                url="https://github.com/ratt-ru/pfb-imaging",
                ref="main",
            ),
        ],
    )
    save_corpus(original, path)
    reloaded = load_corpus(path)
    assert len(reloaded.repos) == 1
    repo = reloaded.repos[0]
    assert repo.name == "pfb-imaging"
    assert repo.url == "https://github.com/ratt-ru/pfb-imaging"
    assert repo.ref == "main"
    assert repo.commit_hash is None


def test_round_trip_honours_commit_hash_pin(tmp_path: Path) -> None:
    """A pinned commit_hash survives the round-trip alongside ref."""
    path = tmp_path / "corpus.toml"
    pinned = CorpusConfig(
        repos=[
            CorpusRepo(
                name="stimela2",
                path=Path("/tmp/stimela2"),
                url="https://github.com/caracal-pipeline/stimela2",
                ref="dev",
                commit_hash="deadbeef" * 5,
            ),
        ],
    )
    save_corpus(pinned, path)
    reloaded = load_corpus(path)
    assert reloaded.repos[0].commit_hash == "deadbeef" * 5
    assert reloaded.repos[0].ref == "dev"


def test_save_omits_none_optionals(tmp_path: Path) -> None:
    path = tmp_path / "corpus.toml"
    config = CorpusConfig(
        repos=[CorpusRepo(name="local", path=Path("/tmp/local"))],
    )
    save_corpus(config, path)
    raw = _read_raw(path)
    [entry] = raw["repo"]
    assert "url" not in entry
    assert "commit_hash" not in entry
    assert entry["ref"] == "main"


def test_load_rejects_non_array_repo_section(tmp_path: Path) -> None:
    path = tmp_path / "corpus.toml"
    path.write_text('repo = "not a list"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus(path)


def test_load_validates_each_repo(tmp_path: Path) -> None:
    """A malformed repo entry surfaces as ValidationError, not silent drop."""
    from pydantic import ValidationError

    path = tmp_path / "corpus.toml"
    # Missing required ``name`` field.
    path.write_text('[[repo]]\npath = "/tmp/x"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_corpus(path)
