"""Test fixtures for africalim.

The ``mini_corpus`` synthetic git repo lives in ``mini_corpus.tar.gz`` and is
extracted on demand by the session-scoped ``mini_corpus_path`` pytest fixture
defined in ``tests/conftest.py``. We can't ship a literal nested ``.git/``
directory inside the parent repo without it becoming a broken gitlink.
"""

from __future__ import annotations

from pathlib import Path

MINI_CORPUS_TARBALL: Path = Path(__file__).resolve().parent / "mini_corpus.tar.gz"
"""Absolute path to the gzipped tarball containing the synthetic corpus."""

__all__ = ["MINI_CORPUS_TARBALL"]
