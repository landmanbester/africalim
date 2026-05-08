"""Top-level pytest configuration for africalim.

Provides session-scoped fixtures used across multiple test modules. Notably
exposes ``mini_corpus_path``, which extracts the synthetic git-repo fixture
from ``tests/fixtures/mini_corpus.tar.gz`` exactly once per session.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

import pytest

from tests.fixtures import MINI_CORPUS_TARBALL


@pytest.fixture(scope="session")
def mini_corpus_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Yield an absolute path to a freshly-extracted mini_corpus repository.

    The fixture is gzipped and stored under ``tests/fixtures/`` because nested
    ``.git/`` directories cannot be checked into the parent repo without
    becoming broken gitlinks. Extracting once per session keeps tests fast
    while guaranteeing each session sees the canonical contents.
    """
    extract_root = tmp_path_factory.mktemp("mini_corpus_root")
    with tarfile.open(MINI_CORPUS_TARBALL, "r:gz") as tar:
        tar.extractall(extract_root, filter="data")
    repo_path = extract_root / "mini_corpus"
    assert (repo_path / ".git").is_dir(), "mini_corpus tarball missing .git dir"
    yield repo_path
    shutil.rmtree(extract_root, ignore_errors=True)
