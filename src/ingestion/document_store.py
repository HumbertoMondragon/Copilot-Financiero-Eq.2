"""
In-memory document store (Phase 3 will replace with ChromaDB).
Stores Document and Chunk objects keyed by doc_id.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document_loader import Document
    from .chunker import Chunk


class DocumentStore:
    def __init__(self) -> None:
        self._documents: dict[str, "Document"] = {}
        self._chunks: dict[str, list["Chunk"]] = {}

    # ── Write ──────────────────────────────────────────────────────────────────

    def add_document(self, doc: "Document") -> None:
        self._documents[doc.doc_id] = doc
        if doc.doc_id not in self._chunks:
            self._chunks[doc.doc_id] = []

    def add_chunks(self, chunks: list["Chunk"]) -> None:
        for chunk in chunks:
            self._chunks.setdefault(chunk.doc_id, []).append(chunk)

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_document(self, doc_id: str) -> "Document | None":
        return self._documents.get(doc_id)

    def get_chunks(self, doc_id: str) -> list["Chunk"]:
        return list(self._chunks.get(doc_id, []))

    def list_documents(self, cliente_id: str | None = None) -> list["Document"]:
        docs = list(self._documents.values())
        if cliente_id is not None:
            docs = [d for d in docs if d.cliente_id == cliente_id]
        return docs

    def retrieve(self, query: str, cliente_id: str | None = None, top_k: int = 5) -> list["Chunk"]:
        """
        Keyword-based retrieval (case-insensitive substring match).
        Phase 3 will replace this with vector similarity search.
        """
        query_lower = query.lower()
        candidates: list["Chunk"] = []
        for doc_id, chunk_list in self._chunks.items():
            doc = self._documents.get(doc_id)
            if cliente_id is not None and (doc is None or doc.cliente_id != cliente_id):
                continue
            for chunk in chunk_list:
                if query_lower in chunk.texto.lower():
                    candidates.append(chunk)
        return candidates[:top_k]

    # ── Admin ──────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._documents.clear()
        self._chunks.clear()

    def stats(self) -> dict:
        total_chunks = sum(len(v) for v in self._chunks.values())
        return {
            "total_documents": len(self._documents),
            "total_chunks": total_chunks,
            "documents_by_cliente": _count_by(self._documents.values(), "cliente_id"),
        }


def _count_by(items, attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = getattr(item, attr, "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts
