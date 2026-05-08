"""Unit tests for ``africalim.utils.deps``.

Sync tests (no asyncio). Each test gets isolated paths via ``tmp_path``
so cases never see one another's writes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from pydantic import ValidationError

from africalim.utils.consent import ConsentManager
from africalim.utils.deps import CorpusConfig, CorpusRepo, HarnessDeps
from africalim.utils.logger import InteractionLogger

# --------------------------------------------------------------------------- #
# CorpusRepo
# --------------------------------------------------------------------------- #


def test_corpus_repo_round_trips_with_explicit_fields(tmp_path: Path) -> None:
    """All fields survive a round trip via ``model_dump`` / re-construction."""
    repo = CorpusRepo(
        name="stimela2",
        path=tmp_path / "stimela2",
        url="https://github.com/caracal-pipeline/stimela2",
        ref="v2.0",
        commit_hash="deadbeef" * 5,
    )
    assert repo.name == "stimela2"
    assert repo.path == tmp_path / "stimela2"
    assert repo.url == "https://github.com/caracal-pipeline/stimela2"
    assert repo.ref == "v2.0"
    assert repo.commit_hash == "deadbeef" * 5

    rebuilt = CorpusRepo.model_validate(repo.model_dump())
    assert rebuilt == repo


def test_corpus_repo_defaults() -> None:
    """``url`` and ``commit_hash`` default to None; ``ref`` defaults to 'main'."""
    repo = CorpusRepo(name="x", path=Path("/tmp/x"))
    assert repo.url is None
    assert repo.commit_hash is None
    assert repo.ref == "main"


def test_corpus_repo_expands_tilde_in_path() -> None:
    """``~`` in path is resolved against ``$HOME`` at validation time."""
    repo = CorpusRepo(name="user-repo", path=Path("~/code/foo"))
    home = Path("~").expanduser()
    assert repo.path == home / "code" / "foo"
    # Hard property: no leading "~" survives.
    assert "~" not in str(repo.path)


def test_corpus_repo_accepts_string_path() -> None:
    """String paths are coerced through ``Path(...).expanduser()``."""
    repo = CorpusRepo(name="strpath", path="~/code/bar")  # type: ignore[arg-type]
    assert repo.path == Path("~").expanduser() / "code" / "bar"


def test_corpus_repo_keeps_relative_paths_relative() -> None:
    """A relative input is expanded but **not** resolved against cwd.

    The validator must call ``expanduser`` only — never ``resolve()``,
    because that would silently anchor the path to whichever cwd the
    config happened to be loaded under.
    """
    repo = CorpusRepo(name="rel", path=Path("relative/sub"))
    assert repo.path == Path("relative/sub")
    assert not repo.path.is_absolute()


def test_corpus_repo_does_not_require_path_to_exist(tmp_path: Path) -> None:
    """Validation does not touch the filesystem."""
    nonexistent = tmp_path / "definitely-not-here"
    repo = CorpusRepo(name="ghost", path=nonexistent)
    assert repo.path == nonexistent
    assert not repo.path.exists()


def test_corpus_repo_is_frozen(tmp_path: Path) -> None:
    """Pydantic ``frozen=True`` blocks attribute assignment."""
    repo = CorpusRepo(name="x", path=tmp_path / "x")
    with pytest.raises(ValidationError):
        repo.name = "y"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# CorpusConfig
# --------------------------------------------------------------------------- #


def _three_repos(tmp_path: Path) -> list[CorpusRepo]:
    return [
        CorpusRepo(name="alpha", path=tmp_path / "alpha"),
        CorpusRepo(name="bravo", path=tmp_path / "bravo"),
        CorpusRepo(name="charlie", path=tmp_path / "charlie"),
    ]


def test_corpus_config_defaults_to_empty() -> None:
    """An empty config is a valid (but unhelpful) starting point."""
    cfg = CorpusConfig()
    assert cfg.repos == []
    assert cfg.names() == []


def test_corpus_config_by_name_finds_repo(tmp_path: Path) -> None:
    """``by_name`` returns the registered :class:`CorpusRepo`."""
    cfg = CorpusConfig(repos=_three_repos(tmp_path))
    assert cfg.by_name("bravo").path == tmp_path / "bravo"


def test_corpus_config_by_name_raises_with_known_names(tmp_path: Path) -> None:
    """Unknown names produce a ``KeyError`` listing all known names."""
    cfg = CorpusConfig(repos=_three_repos(tmp_path))
    with pytest.raises(KeyError) as exc:
        cfg.by_name("delta")
    msg = str(exc.value)
    assert "delta" in msg
    for known in ("alpha", "bravo", "charlie"):
        assert known in msg


def test_corpus_config_by_name_empty_registry_message() -> None:
    """The unknown-name message survives an empty registry without crashing."""
    cfg = CorpusConfig()
    with pytest.raises(KeyError) as exc:
        cfg.by_name("anything")
    assert "anything" in str(exc.value)


def test_corpus_config_names_preserves_declaration_order(tmp_path: Path) -> None:
    """``names()`` returns names in declaration order, not sorted."""
    cfg = CorpusConfig(repos=_three_repos(tmp_path))
    assert cfg.names() == ["alpha", "bravo", "charlie"]

    cfg2 = CorpusConfig(
        repos=[
            CorpusRepo(name="charlie", path=tmp_path / "c"),
            CorpusRepo(name="alpha", path=tmp_path / "a"),
            CorpusRepo(name="bravo", path=tmp_path / "b"),
        ]
    )
    assert cfg2.names() == ["charlie", "alpha", "bravo"]


def test_corpus_config_is_frozen(tmp_path: Path) -> None:
    """``CorpusConfig`` is also frozen."""
    cfg = CorpusConfig(repos=_three_repos(tmp_path))
    with pytest.raises(ValidationError):
        cfg.repos = []  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# HarnessDeps
# --------------------------------------------------------------------------- #


def test_harness_deps_is_a_dataclass_with_expected_fields() -> None:
    """``HarnessDeps`` is a frozen dataclass; the four field names are stable."""
    assert dataclasses.is_dataclass(HarnessDeps)
    field_names = [f.name for f in dataclasses.fields(HarnessDeps)]
    assert field_names == ["corpus", "logger", "consent", "harness_version"]


def test_harness_deps_round_trips_and_exposes_each_field(tmp_path: Path) -> None:
    """Build with real loggers/managers; smoke-check each field is reachable."""
    db_path = tmp_path / "interactions.db"
    config_path = tmp_path / "config.toml"
    corpus = CorpusConfig(repos=[CorpusRepo(name="solo", path=tmp_path / "solo")])

    with InteractionLogger(db_path) as logger:
        consent = ConsentManager(config_path)
        deps = HarnessDeps(
            corpus=corpus,
            logger=logger,
            consent=consent,
            harness_version="0.1.0",
        )

        assert deps.corpus is corpus
        assert deps.corpus.by_name("solo").path == tmp_path / "solo"
        assert deps.logger is logger
        assert deps.consent is consent
        assert deps.consent.get_status() == "unset"
        assert deps.harness_version == "0.1.0"


def test_harness_deps_is_frozen(tmp_path: Path) -> None:
    """Reassignment on a frozen dataclass raises ``FrozenInstanceError``."""
    db_path = tmp_path / "interactions.db"
    config_path = tmp_path / "config.toml"
    corpus = CorpusConfig()

    with InteractionLogger(db_path) as logger:
        consent = ConsentManager(config_path)
        deps = HarnessDeps(
            corpus=corpus,
            logger=logger,
            consent=consent,
            harness_version="0.1.0",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            deps.harness_version = "9.9.9"  # type: ignore[misc]
