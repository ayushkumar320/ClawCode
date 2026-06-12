"""Per-repo lesson store backed by ChromaDB + sentence-transformer embeddings."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from memory.exceptions import LessonStoreError

logger = logging.getLogger(__name__)

_COLLECTION_RE = re.compile(r"[^A-Za-z0-9._-]")
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def collection_name(repo_slug: str) -> str:
    """Sanitize ``repo_slug`` into a valid ChromaDB collection name (3-63 chars)."""
    safe = _COLLECTION_RE.sub("-", repo_slug.strip())
    name = f"repo-{safe}"[:63]
    if len(name) < 3:
        name = f"{name}-x"
    return name


@lru_cache(maxsize=1)
def _embedding_fn() -> Any:
    """Lazily build the sentence-transformer embedding function (loaded once)."""
    from chromadb.utils import embedding_functions  # type: ignore[import-not-found]

    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=_EMBEDDING_MODEL)


class LessonStore:
    """ChromaDB-backed lesson store; one collection per repo, isolated by slug."""

    def __init__(self, chroma_dir: Path) -> None:
        """Open (or create) a persistent ChromaDB rooted at ``chroma_dir``."""
        import chromadb  # type: ignore[import-not-found]

        chroma_dir.mkdir(parents=True, exist_ok=True)
        self._dir = chroma_dir
        try:
            self._client = chromadb.PersistentClient(path=str(chroma_dir))
        except Exception as exc:  # noqa: BLE001 — Chroma error surface is broad
            raise LessonStoreError(f"chroma client init failed: {exc}") from exc

    def _collection(self, repo_slug: str) -> Any:
        """Return (or create) the per-repo collection with embedding function attached."""
        return self._client.get_or_create_collection(
            name=collection_name(repo_slug),
            embedding_function=_embedding_fn(),
        )

    async def add_lesson(self, repo_slug: str, text: str) -> None:
        """Persist ``text`` as a lesson for ``repo_slug``. Empty text is a no-op."""
        if not text or not text.strip():
            return
        coll = self._collection(repo_slug)
        try:
            await asyncio.to_thread(
                coll.add,
                documents=[text],
                ids=[str(uuid.uuid4())],
                metadatas=[{"repo": repo_slug}],
            )
        except Exception as exc:  # noqa: BLE001 — Chroma error surface is broad
            raise LessonStoreError(f"add_lesson failed for {repo_slug}: {exc}") from exc
        logger.info("lesson stored for %s (%d chars)", repo_slug, len(text))

    async def top_k(self, repo_slug: str, query: str, *, k: int = 3) -> list[str]:
        """Return up to ``k`` lessons most relevant to ``query`` for this repo."""
        if not query or not query.strip():
            return []
        coll = self._collection(repo_slug)
        try:
            res = await asyncio.to_thread(coll.query, query_texts=[query], n_results=k)
        except Exception as exc:  # noqa: BLE001 — Chroma error surface is broad
            raise LessonStoreError(f"top_k failed for {repo_slug}: {exc}") from exc
        docs = res.get("documents") or [[]]
        return list(docs[0]) if docs else []
