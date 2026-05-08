"""Unit tests for ``africalim.utils.retrieval``.

These tests are deliberately self-contained: they use ``tmp_path`` for all
fixtures and never reference ``tests/fixtures/mini_corpus/`` (that fixture is
reserved for the M1.3 integration tests).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from africalim.utils.retrieval import (
    FileContent,
    RepoStructure,
    RepoVersion,
    SearchHit,
    get_repo_version,
    list_repo_structure,
    read_file,
    search_codebase,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    **os.environ,
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=GIT_ENV,
        capture_output=True,
        text=True,
    )


def _make_search_corpus(root: Path) -> None:
    """Three small files: two Pythons and a text file, with one shared token."""
    (root / "alpha.py").write_text(
        "def foo():\n    return 'NEEDLE here'\n\n# trailing comment\n",
        encoding="utf-8",
    )
    (root / "beta.py").write_text(
        "import os\n\n\ndef bar():\n    NEEDLE = 1\n    return NEEDLE\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text(
        "plain text NEEDLE in here\nanother line\n",
        encoding="utf-8",
    )


def _init_git_repo(root: Path) -> str:
    """Initialise ``root`` as a git repo with one commit. Returns the commit hash."""
    _git(root, "init", "-b", "main")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")
    res = _git(root, "rev-parse", "HEAD")
    return res.stdout.strip()


# --------------------------------------------------------------------------- #
# search_codebase — ripgrep backend
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not on PATH")
def test_search_codebase_rg_finds_unique_string(tmp_path: Path) -> None:
    _make_search_corpus(tmp_path)
    hits = search_codebase("NEEDLE", tmp_path)
    assert hits, "expected at least one hit for NEEDLE"
    assert all(isinstance(h, SearchHit) for h in hits)
    assert all(h.repo == tmp_path.name for h in hits)
    files = {h.file_path for h in hits}
    # All three files contain NEEDLE; ripgrep should find each at least once.
    assert "alpha.py" in files
    assert "beta.py" in files
    assert "notes.txt" in files
    # Hits must be frozen pydantic models.
    with pytest.raises(Exception):
        hits[0].repo = "mutated"  # type: ignore[misc]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not on PATH")
def test_search_codebase_rg_glob_excludes_text(tmp_path: Path) -> None:
    _make_search_corpus(tmp_path)
    hits = search_codebase("NEEDLE", tmp_path, file_globs=["*.py"])
    files = {h.file_path for h in hits}
    assert "notes.txt" not in files
    assert files <= {"alpha.py", "beta.py"}
    assert files  # non-empty


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not on PATH")
def test_search_codebase_rg_max_results(tmp_path: Path) -> None:
    # Lots of hits in one file so we can verify truncation.
    target = tmp_path / "many.py"
    target.write_text("\n".join(f"line NEEDLE {i}" for i in range(20)) + "\n", encoding="utf-8")
    hits = search_codebase("NEEDLE", tmp_path, max_results=2)
    assert len(hits) == 2


# --------------------------------------------------------------------------- #
# search_codebase — fallback backend
# --------------------------------------------------------------------------- #


def test_search_codebase_fallback_matches_rg_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_search_corpus(tmp_path)
    # Pretend rg is not on PATH.
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    hits = search_codebase("NEEDLE", tmp_path)
    assert hits
    files = {h.file_path for h in hits}
    assert files == {"alpha.py", "beta.py", "notes.txt"}
    # Same SearchHit shape contract.
    for h in hits:
        assert h.repo == tmp_path.name
        assert h.line_number >= 1
        assert "NEEDLE" in h.line_text


def test_search_codebase_fallback_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_search_corpus(tmp_path)
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    hits = search_codebase("NEEDLE", tmp_path, file_globs=["*.py"])
    files = {h.file_path for h in hits}
    assert "notes.txt" not in files
    assert files <= {"alpha.py", "beta.py"}
    assert files


def test_search_codebase_fallback_max_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "many.py"
    target.write_text("\n".join(f"line NEEDLE {i}" for i in range(20)) + "\n", encoding="utf-8")
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    hits = search_codebase("NEEDLE", tmp_path, max_results=2)
    assert len(hits) == 2


def test_search_codebase_fallback_skips_ignored_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "real.py").write_text("NEEDLE 1\n", encoding="utf-8")
    pyc = tmp_path / "__pycache__"
    pyc.mkdir()
    (pyc / "cached.py").write_text("NEEDLE 2\n", encoding="utf-8")
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    hits = search_codebase("NEEDLE", tmp_path)
    files = {h.file_path for h in hits}
    assert files == {"real.py"}


def test_search_codebase_fallback_handles_binary_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Non-UTF-8 bytes must not crash the walker.
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00binary NEEDLE\n")
    (tmp_path / "ok.py").write_text("NEEDLE\n", encoding="utf-8")
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    hits = search_codebase("NEEDLE", tmp_path)
    files = {h.file_path for h in hits}
    # ``ok.py`` definitely matches; binary is opened with errors='replace' so
    # may or may not match — the contract is just "no crash".
    assert "ok.py" in files


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #


def _five_line_file(tmp_path: Path) -> Path:
    p = tmp_path / "five.txt"
    p.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    return p


def test_read_file_full(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    out = read_file(p)
    assert isinstance(out, FileContent)
    assert out.content == "a\nb\nc\nd\ne\n"
    assert out.total_lines == 5
    assert out.line_range is None
    assert out.truncated is False
    assert out.path == str(p.resolve())


def test_read_file_line_range_slice(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    out = read_file(p, line_range=(2, 4))
    assert out.content == "b\nc\nd\n"
    assert out.line_range == (2, 4)
    assert out.total_lines == 5
    assert out.truncated is False


def test_read_file_line_range_past_end_clamps(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    out = read_file(p, line_range=(1, 1000))
    assert out.content == "a\nb\nc\nd\ne\n"
    assert out.total_lines == 5
    assert out.truncated is False


def test_read_file_max_lines_truncates(tmp_path: Path) -> None:
    p = tmp_path / "ten.txt"
    p.write_text("\n".join(f"l{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    out = read_file(p, max_lines=2)
    assert out.content.count("\n") == 2
    assert out.truncated is True
    assert out.total_lines == 10


def test_read_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "nope.txt")


def test_read_file_bad_range_raises(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    with pytest.raises(ValueError):
        read_file(p, line_range=(5, 2))


def test_read_file_zero_start_raises(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    with pytest.raises(ValueError):
        read_file(p, line_range=(0, 3))


def test_read_file_handles_non_utf8_bytes(tmp_path: Path) -> None:
    p = tmp_path / "bin.txt"
    p.write_bytes(b"hello\n\xff\xfe\nworld\n")
    out = read_file(p)
    # errors='replace' means we don't crash; content has the replacement char.
    assert out.total_lines == 3


# --------------------------------------------------------------------------- #
# list_repo_structure
# --------------------------------------------------------------------------- #


def test_list_repo_structure_max_depth_one(tmp_path: Path) -> None:
    (tmp_path / "top.py").write_text("x\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("y\n", encoding="utf-8")
    deeper = sub / "deeper"
    deeper.mkdir()
    (deeper / "way_down.py").write_text("z\n", encoding="utf-8")

    out = list_repo_structure(tmp_path, max_depth=1)
    assert isinstance(out, RepoStructure)
    paths = {e.path for e in out.tree}
    # Depth 1 means we list top-level entries only.
    assert "top.py" in paths
    assert "sub" in paths
    assert "sub/deep.py" not in paths
    assert "sub/deeper" not in paths


def test_list_repo_structure_descends_within_depth(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("y\n", encoding="utf-8")
    out = list_repo_structure(tmp_path, max_depth=3)
    paths = {e.path for e in out.tree}
    assert "sub" in paths
    assert "sub/deep.py" in paths


def test_list_repo_structure_excludes_ignored_dirs(tmp_path: Path) -> None:
    (tmp_path / "kept.py").write_text("x\n", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    pyc = tmp_path / "__pycache__"
    pyc.mkdir()
    (pyc / "junk.pyc").write_bytes(b"\x00")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    out = list_repo_structure(tmp_path, max_depth=3)
    paths = {e.path for e in out.tree}
    assert "kept.py" in paths
    assert ".git" not in paths
    assert "__pycache__" not in paths
    assert ".venv" not in paths
    assert not any(p.startswith(".git/") for p in paths)
    assert not any(p.startswith("__pycache__/") for p in paths)


def test_list_repo_structure_repo_path_absolute(tmp_path: Path) -> None:
    out = list_repo_structure(tmp_path)
    assert Path(out.repo_path).is_absolute()


# --------------------------------------------------------------------------- #
# get_repo_version
# --------------------------------------------------------------------------- #


def test_get_repo_version_clean_repo(tmp_path: Path) -> None:
    commit_hash = _init_git_repo(tmp_path)
    out = get_repo_version(tmp_path)
    assert isinstance(out, RepoVersion)
    assert out.commit_hash == commit_hash
    assert out.branch == "main"
    assert out.is_dirty is False


def test_get_repo_version_dirty_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # Modify the tracked README to trigger dirty status.
    (tmp_path / "README.md").write_text("hello\nmore\n", encoding="utf-8")
    out = get_repo_version(tmp_path)
    assert out.is_dirty is True


def test_get_repo_version_untracked_files_not_dirty(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # Untracked file alone should NOT count as dirty (documented behaviour).
    (tmp_path / "newfile.txt").write_text("hello\n", encoding="utf-8")
    out = get_repo_version(tmp_path)
    assert out.is_dirty is False


def test_get_repo_version_non_git_dir(tmp_path: Path) -> None:
    out = get_repo_version(tmp_path)
    assert out.commit_hash is None
    assert out.branch is None
    assert out.is_dirty is False


def test_get_repo_version_detached_head_uses_short_hash(tmp_path: Path) -> None:
    commit_hash = _init_git_repo(tmp_path)
    # Detach HEAD by checking out the commit directly.
    _git(tmp_path, "checkout", "--detach", commit_hash)
    out = get_repo_version(tmp_path)
    assert out.commit_hash == commit_hash
    assert out.branch == commit_hash[:7]


def test_get_repo_version_nonexistent_path(tmp_path: Path) -> None:
    # Directory that does not exist on disk: still no exception, just sentinel result.
    bogus = tmp_path / "does-not-exist"
    out = get_repo_version(bogus)
    assert out.commit_hash is None
    assert out.branch is None
    assert out.is_dirty is False


def test_get_repo_version_empty_repo(tmp_path: Path) -> None:
    # ``git init`` with no commits — head.commit raises ValueError.
    _git(tmp_path, "init", "-b", "main")
    out = get_repo_version(tmp_path)
    assert out.commit_hash is None
    assert out.branch is None
    assert out.is_dirty is False


# --------------------------------------------------------------------------- #
# Extra edge cases
# --------------------------------------------------------------------------- #


def test_search_codebase_truncates_long_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force fallback so we test the shared _truncate_line code path deterministically.
    monkeypatch.setattr("africalim.utils.retrieval.shutil.which", lambda _name: None)
    long = "x" * 1500 + "NEEDLE"
    (tmp_path / "long.txt").write_text(long + "\n", encoding="utf-8")
    hits = search_codebase("NEEDLE", tmp_path)
    assert len(hits) == 1
    assert len(hits[0].line_text) == 1000


def test_read_file_start_past_end_of_file(tmp_path: Path) -> None:
    p = _five_line_file(tmp_path)
    out = read_file(p, line_range=(100, 200))
    assert out.content == ""
    assert out.total_lines == 5
    assert out.truncated is False
