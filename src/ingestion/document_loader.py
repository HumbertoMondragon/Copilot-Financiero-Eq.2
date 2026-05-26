"""
Document loader — reads .txt, .md, and .pdf files into a Document dataclass.
PDF support requires pdfplumber; missing dependency raises DocumentLoadError.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import DocumentLoadError

_SUPPORTED_TEXT = {".txt", ".md", ".rst"}
_SUPPORTED_PDF = {".pdf"}


@dataclass
class Document:
    doc_id: str
    filename: str
    cliente_id: str
    tipo: str                   # "texto" | "pdf"
    texto_completo: str
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def load_document(filepath, cliente_id: str = "default") -> Document:
    path = Path(filepath)
    if not path.exists():
        raise DocumentLoadError(f"File not found: {filepath}")

    suffix = path.suffix.lower()

    if suffix in _SUPPORTED_TEXT:
        texto = _read_text(path)
        tipo = "texto"
    elif suffix in _SUPPORTED_PDF:
        texto = _read_pdf(path)
        tipo = "pdf"
    else:
        raise DocumentLoadError(
            f"Unsupported file type '{suffix}'. Supported: "
            f"{sorted(_SUPPORTED_TEXT | _SUPPORTED_PDF)}"
        )

    return Document(
        doc_id=str(uuid.uuid4()),
        filename=path.name,
        cliente_id=cliente_id,
        tipo=tipo,
        texto_completo=texto,
        metadata={"filepath": str(path.resolve()), "size_bytes": path.stat().st_size},
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise DocumentLoadError(
            "pdfplumber is required to read PDF files: pip install pdfplumber"
        ) from exc

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)
