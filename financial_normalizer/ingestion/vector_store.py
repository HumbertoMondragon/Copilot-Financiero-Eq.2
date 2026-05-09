"""
ChromaDB-backed vector store for financial document chunks.

Uses sentence-transformers "all-MiniLM-L6-v2" for local embeddings —
no API key required, model is ~80 MB and cached after first download.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chunker import Chunk


@dataclass
class SearchResult:
    chunk_id: str
    texto: str
    score: float
    cliente_id: str
    filename: str
    chunk_index: int


class VectorStore:
    def __init__(
        self,
        persist_directory: str = "./chroma_db",
        collection_name: str = "documentos",
    ) -> None:
        import os
        import chromadb
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Write ──────────────────────────────────────────────────────────────────

    def add_chunks(self, chunks: list["Chunk"]) -> None:
        if not chunks:
            return
        texts = [c.texto for c in chunks]
        embeddings = self._model.encode(texts, show_progress_bar=False).tolist()
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "cliente_id": c.cliente_id,
                    "filename": c.metadata.get("filename", ""),
                    "chunk_index": c.metadata.get("chunk_index", 0),
                }
                for c in chunks
            ],
        )

    def delete_by_cliente(self, cliente_id: str) -> None:
        results = self._collection.get(where={"cliente_id": cliente_id})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)

    # ── Read ───────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        cliente_id: str,
        n_results: int = 5,
    ) -> list[SearchResult]:
        try:
            count = self._collection.count()
        except Exception:
            return []

        if count == 0:
            return []

        # Cap n_results to what's actually stored to avoid ChromaDB errors
        effective_n = min(n_results, count)

        query_embedding = self._model.encode([query], show_progress_bar=False).tolist()
        try:
            raw = self._collection.query(
                query_embeddings=query_embedding,
                n_results=effective_n,
                where={"cliente_id": cliente_id},
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        results: list[SearchResult] = []
        ids = raw.get("ids", [[]])[0]
        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        for chunk_id, texto, meta, dist in zip(ids, docs, metas, distances):
            # ChromaDB cosine distance → similarity: score = 1 - distance
            score = round(max(0.0, 1.0 - dist), 4)
            results.append(SearchResult(
                chunk_id=chunk_id,
                texto=texto,
                score=score,
                cliente_id=meta.get("cliente_id", ""),
                filename=meta.get("filename", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
            ))
        return results

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        all_items = self._collection.get(include=["metadatas"])
        metas = all_items.get("metadatas") or []
        by_cliente: dict[str, int] = {}
        for m in metas:
            key = m.get("cliente_id", "unknown")
            by_cliente[key] = by_cliente.get(key, 0) + 1
        return {
            "total_chunks": len(metas),
            "by_cliente": by_cliente,
        }
