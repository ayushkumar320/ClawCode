"""Tests for memory.store — ChromaDB + embedding function are mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from memory import store as ms
from memory.exceptions import LessonStoreError


@pytest.fixture()
def fake_chroma(monkeypatch):
    """Replace chromadb.PersistentClient and the embedding loader with stubs."""
    coll = MagicMock()
    coll.query.return_value = {"documents": [["lesson-a", "lesson-b"]]}
    client = MagicMock()
    client.get_or_create_collection.return_value = coll

    fake_module = SimpleNamespace(PersistentClient=MagicMock(return_value=client))
    monkeypatch.setitem(__import__("sys").modules, "chromadb", fake_module)
    monkeypatch.setattr(ms, "_embedding_fn", lambda: "fake-embedder")
    return client, coll


def test_collection_name_sanitizes() -> None:
    assert ms.collection_name("acme/widget") == "repo-acme-widget"
    assert ms.collection_name("a/b") == "repo-a-b"
    assert ms.collection_name("a") == "repo-a"
    long = ms.collection_name("x" * 100)
    assert len(long) <= 63 and len(long) >= 3


def test_collection_name_minimum_length() -> None:
    # Empty slug → still satisfies the >=3 length requirement.
    assert len(ms.collection_name("")) >= 3


def test_init_creates_dir(tmp_path: Path, fake_chroma) -> None:
    subdir = tmp_path / "nested" / "chroma"
    ms.LessonStore(subdir)
    assert subdir.is_dir()


async def test_add_lesson_ok(tmp_path: Path, fake_chroma) -> None:
    _, coll = fake_chroma
    store = ms.LessonStore(tmp_path)
    await store.add_lesson("o/r", "remember to lint")
    coll.add.assert_called_once()
    kwargs = coll.add.call_args.kwargs
    assert kwargs["documents"] == ["remember to lint"]
    assert kwargs["metadatas"] == [{"repo": "o/r"}]


async def test_add_lesson_empty_skipped(tmp_path: Path, fake_chroma) -> None:
    _, coll = fake_chroma
    store = ms.LessonStore(tmp_path)
    await store.add_lesson("o/r", "   ")
    coll.add.assert_not_called()


async def test_top_k_returns_documents(tmp_path: Path, fake_chroma) -> None:
    store = ms.LessonStore(tmp_path)
    out = await store.top_k("o/r", "lint?", k=2)
    assert out == ["lesson-a", "lesson-b"]


async def test_top_k_empty_query(tmp_path: Path, fake_chroma) -> None:
    store = ms.LessonStore(tmp_path)
    assert await store.top_k("o/r", "  ", k=3) == []


async def test_add_lesson_wraps_errors(tmp_path: Path, fake_chroma) -> None:
    _, coll = fake_chroma
    coll.add.side_effect = RuntimeError("boom")
    store = ms.LessonStore(tmp_path)
    with pytest.raises(LessonStoreError):
        await store.add_lesson("o/r", "x")


async def test_top_k_wraps_errors(tmp_path: Path, fake_chroma) -> None:
    _, coll = fake_chroma
    coll.query.side_effect = RuntimeError("boom")
    store = ms.LessonStore(tmp_path)
    with pytest.raises(LessonStoreError):
        await store.top_k("o/r", "x", k=1)
