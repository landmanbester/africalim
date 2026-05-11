"""Integration tests for ``africalim.utils.retrieval`` against the mini_corpus.

These complement ``test_retrieval.py`` (which uses ad-hoc ``tmp_path`` repos)
by exercising the same primitives against the canonical synthetic corpus that
ships with the project. The corpus is materialised on demand by the
session-scoped ``mini_corpus_path`` fixture defined in ``tests/conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from africalim.utils.retrieval import (
    get_repo_version,
    list_repo_structure,
    read_file,
    search_codebase,
)

EXPECTED_HEAD_PREFIX = "24470c8"
EXPECTED_INITIAL_PREFIX = "5bd0bb6"


def test_search_codebase_finds_known_function(mini_corpus_path: Path) -> None:
    hits = search_codebase("solve_gains", mini_corpus_path)
    assert hits, "expected at least one hit for solve_gains"
    file_paths = {hit.file_path for hit in hits}
    assert any("calibration.py" in p for p in file_paths), file_paths
    for hit in hits:
        assert hit.repo == "mini_corpus"
        assert "solve_gains" in hit.line_text


def test_search_codebase_respects_file_globs(mini_corpus_path: Path) -> None:
    py_hits = search_codebase("synthcal", mini_corpus_path, file_globs=["*.py"])
    md_hits = search_codebase("synthcal", mini_corpus_path, file_globs=["*.md"])
    assert all(hit.file_path.endswith(".py") for hit in py_hits)
    assert all(hit.file_path.endswith(".md") for hit in md_hits)
    assert py_hits, "expected synthcal references inside .py files"


def test_search_codebase_max_results_truncates(mini_corpus_path: Path) -> None:
    hits = search_codebase("def ", mini_corpus_path, max_results=2)
    assert len(hits) <= 2


def test_read_file_reads_readme(mini_corpus_path: Path) -> None:
    readme = read_file(mini_corpus_path / "README.md")
    assert "synthcal" in readme.content.lower()
    assert readme.total_lines > 0
    assert readme.truncated is False


def test_read_file_with_line_range(mini_corpus_path: Path) -> None:
    cli = read_file(mini_corpus_path / "src" / "synthcal" / "cli.py", line_range=(1, 3))
    assert cli.line_range == (1, 3)
    assert cli.content.count("\n") <= 3


def test_list_repo_structure_excludes_dot_git(mini_corpus_path: Path) -> None:
    structure = list_repo_structure(mini_corpus_path, max_depth=2)
    paths = {entry.path for entry in structure.tree}
    assert ".git" not in {p.split("/")[0] for p in paths}
    assert any(p.startswith("src") for p in paths)


def test_get_repo_version_pinned_head(mini_corpus_path: Path) -> None:
    version = get_repo_version(mini_corpus_path)
    assert version.commit_hash is not None
    assert version.commit_hash.startswith(EXPECTED_HEAD_PREFIX), (
        f"mini_corpus HEAD should start with {EXPECTED_HEAD_PREFIX}, got {version.commit_hash}. "
        "If the tarball was regenerated, update EXPECTED_HEAD_PREFIX."
    )
    assert version.branch == "main"
    assert version.is_dirty is False


def test_get_repo_version_initial_commit_in_history(mini_corpus_path: Path) -> None:
    """The initial commit hash must be reachable from HEAD."""
    import subprocess

    log = subprocess.run(
        ["git", "-C", str(mini_corpus_path), "log", "--pretty=%H"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split()
    assert any(h.startswith(EXPECTED_INITIAL_PREFIX) for h in log), (
        f"expected initial commit {EXPECTED_INITIAL_PREFIX} in mini_corpus history; got {log}"
    )


def test_search_codebase_fallback_matches_rg(mini_corpus_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rg_hits = search_codebase("psf_from_uv", mini_corpus_path)
    monkeypatch.setattr("shutil.which", lambda *_args, **_kwargs: None)
    fallback_hits = search_codebase("psf_from_uv", mini_corpus_path)
    rg_locations = {(h.file_path, h.line_number) for h in rg_hits}
    fallback_locations = {(h.file_path, h.line_number) for h in fallback_hits}
    assert rg_locations == fallback_locations, (rg_locations, fallback_locations)
