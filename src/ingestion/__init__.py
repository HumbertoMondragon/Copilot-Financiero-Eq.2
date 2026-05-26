"""
Document ingestion package.
Loads, chunks, and stores qualitative financial documents.
"""
from __future__ import annotations


class DocumentLoadError(Exception):
    pass


def ingest(filepath, cliente_id: str, store, vector_store=None) -> dict:
    """
    Load a document, chunk it, and add everything to the store.
    If vector_store is provided, also embed and store chunks there.
    Returns a summary dict with doc metadata and chunk count.
    """
    from .document_loader import load_document
    from .chunker import chunk_document

    doc = load_document(filepath, cliente_id)
    chunks = chunk_document(doc)
    store.add_document(doc)
    store.add_chunks(chunks)

    embeddings_stored = False
    if vector_store is not None:
        vector_store.add_chunks(chunks)
        embeddings_stored = True

    return {
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "cliente_id": doc.cliente_id,
        "chunks_created": len(chunks),
        "texto_length": len(doc.texto_completo),
        "embeddings_stored": embeddings_stored,
    }
