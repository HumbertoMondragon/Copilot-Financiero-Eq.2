"""
Text chunker for financial documents.

Strategy:
  1. Coarse split: markdown headers (##/###) or double-newline paragraphs.
  2. Fine split: segments larger than chunk_size are split at sentence boundaries.
  3. Merge: small adjacent segments are merged up to chunk_size.
  4. Overlap: prepend the tail of the previous chunk to each chunk.
  5. Position: start_char/end_char computed by forward string search.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document_loader import Document

_RE_MD_HEADER = re.compile(r"(?m)^(#{2,3}\s+.+)")
_SENTENCE_END = re.compile(r"[.!?\n]")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    cliente_id: str
    texto: str
    metadata: dict = field(default_factory=dict)


def chunk_document(
    document: "Document",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    texto = document.texto_completo
    if not texto.strip():
        return []

    # 1. Coarse split
    segments = _coarse_split(texto)

    # 2. Fine split — break anything over chunk_size at a sentence boundary
    fine: list[str] = []
    for seg in segments:
        if len(seg) <= chunk_size:
            fine.append(seg)
        else:
            fine.extend(_split_large(seg, chunk_size))

    # 3. Merge small segments
    merged = _merge_segments(fine, chunk_size)

    # 4. Apply overlap
    with_overlap = _apply_overlap(merged, chunk_overlap)

    # 5. Build Chunk objects with position metadata
    chunks: list[Chunk] = []
    search_start = 0
    for i, text in enumerate(with_overlap):
        # Locate position of the core text (without overlap prefix) in the original
        core = merged[i]
        pos = texto.find(core, search_start)
        if pos == -1:
            pos = texto.find(core.lstrip())
        start_char = max(0, pos)
        end_char = start_char + len(core)
        if pos != -1:
            search_start = pos

        chunks.append(Chunk(
            chunk_id=f"{document.doc_id}_{i}",
            doc_id=document.doc_id,
            cliente_id=document.cliente_id,
            texto=text,
            metadata={
                "chunk_index": i,
                "start_char": start_char,
                "end_char": end_char,
                "filename": document.filename,
            },
        ))
    return chunks


# ── Private helpers ────────────────────────────────────────────────────────────

def _coarse_split(texto: str) -> list[str]:
    """Split on markdown H2/H3 headers if present; otherwise on blank lines."""
    if _RE_MD_HEADER.search(texto):
        return _split_on_md_headers(texto)
    parts = [p.strip() for p in texto.split("\n\n")]
    return [p for p in parts if p]


def _split_on_md_headers(texto: str) -> list[str]:
    """Split preserving the header line as the start of each segment."""
    parts = _RE_MD_HEADER.split(texto)
    segments: list[str] = []
    current_parts: list[str] = []
    for part in parts:
        if _RE_MD_HEADER.match(part):
            if current_parts:
                seg = "\n".join(current_parts).strip()
                if seg:
                    segments.append(seg)
            current_parts = [part]
        else:
            current_parts.append(part)
    if current_parts:
        seg = "\n".join(current_parts).strip()
        if seg:
            segments.append(seg)
    return segments if segments else [texto.strip()]


def _split_large(text: str, chunk_size: int) -> list[str]:
    """Recursively split text that exceeds chunk_size at the last sentence boundary."""
    if len(text) <= chunk_size:
        return [text]

    # Search back from chunk_size for a sentence boundary
    window = text[max(0, chunk_size - 100): chunk_size]
    matches = list(_SENTENCE_END.finditer(window))
    if matches:
        cut = max(0, chunk_size - 100) + matches[-1].end()
    else:
        cut = chunk_size

    left = text[:cut].rstrip()
    right = text[cut:].lstrip()
    result = []
    if left:
        result.append(left)
    if right:
        result.extend(_split_large(right, chunk_size))
    return result


def _merge_segments(segments: list[str], chunk_size: int) -> list[str]:
    """Greedily merge consecutive segments that fit within chunk_size."""
    if not segments:
        return []
    merged: list[str] = []
    current = segments[0]
    for seg in segments[1:]:
        candidate = current + "\n\n" + seg
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            merged.append(current)
            current = seg
    merged.append(current)
    return merged


def _apply_overlap(segments: list[str], overlap: int) -> list[str]:
    """Prepend the tail of the previous segment to each segment."""
    if overlap <= 0 or len(segments) < 2:
        return list(segments)
    result = [segments[0]]
    for i in range(1, len(segments)):
        prefix = segments[i - 1][-overlap:]
        result.append(prefix + segments[i])
    return result
