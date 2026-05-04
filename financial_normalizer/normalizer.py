"""
Orchestrator: normalize(filepath, cliente_id) → normalized JSON dict.

Decision tree:
  .xlsx / .xls  → parser_excel → validate → (if invalid) → parser_llm
  .pdf          → parser_pdf_texto → validate → (if invalid) → parser_llm
  scanned .pdf  → parser_pdf_escaneado → validate → (if invalid) → parser_llm
"""
from __future__ import annotations

import logging
import json
from pathlib import Path

from .parsers import ParseError
from .parsers import parser_excel, parser_pdf_texto, parser_pdf_escaneado, parser_llm
from .validator import validate

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

_EXCEL_EXTS = {".xlsx", ".xls", ".xlsm"}
_PDF_EXTS = {".pdf"}


def normalize(filepath: str | Path, cliente_id: str = "default") -> dict:
    """
    Main entry point. Returns the normalized schema dict.
    Raises ParseError if all parsers fail.
    """
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext in _EXCEL_EXTS:
        return _run_with_fallback(
            primary=lambda: parser_excel.parse(path, cliente_id),
            label="parser_excel",
            filepath=path,
            cliente_id=cliente_id,
        )

    if ext in _PDF_EXTS:
        # Determine if scanned by trying text extraction first
        is_scanned = _looks_scanned(path)
        if is_scanned:
            return _run_with_fallback(
                primary=lambda: parser_pdf_escaneado.parse(path, cliente_id),
                label="parser_pdf_escaneado",
                filepath=path,
                cliente_id=cliente_id,
            )
        else:
            return _run_with_fallback(
                primary=lambda: parser_pdf_texto.parse(path, cliente_id),
                label="parser_pdf_texto",
                filepath=path,
                cliente_id=cliente_id,
            )

    raise ParseError(f"Unsupported file type: {ext!r}")


def _run_with_fallback(primary, label: str, filepath: Path, cliente_id: str) -> dict:
    result = None
    try:
        result = primary()
        validation = validate(result)
        _log_result(label, validation, filepath)
        if validation["valid"]:
            return result
        logger.warning(
            "Primary parser %s produced invalid result; falling back to LLM. Errors: %s",
            label, validation["errors"],
        )
    except ParseError as exc:
        logger.warning("Primary parser %s failed: %s; falling back to LLM.", label, exc)

    # LLM fallback: extract raw text and send to LLM
    raw_text = _extract_raw_text(filepath)
    llm_result = parser_llm.parse(raw_text, cliente_id)
    validation = validate(llm_result)
    _log_result("parser_llm", validation, filepath)
    return llm_result


def _log_result(parser: str, validation: dict, filepath: Path) -> None:
    status = "VALID" if validation["valid"] else "INVALID"
    logger.info(
        json.dumps({
            "parser": parser,
            "file": str(filepath),
            "status": status,
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        })
    )


def _looks_scanned(path: Path) -> bool:
    """Heuristic: if pdfplumber finds no text on the first page, treat as scanned."""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return True
            text = pdf.pages[0].extract_text() or ""
            return len(text.strip()) < 50
    except Exception:
        return False


def _extract_raw_text(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    if ext in _EXCEL_EXTS:
        try:
            import pandas as pd
            dfs = pd.read_excel(str(filepath), sheet_name=None, header=None)
            parts = []
            for name, df in dfs.items():
                parts.append(f"[Sheet: {name}]")
                parts.append(df.fillna("").to_string(index=False))
            return "\n".join(parts)
        except Exception:
            return ""
    if ext in _PDF_EXTS:
        try:
            import pdfplumber
            with pdfplumber.open(str(filepath)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return ""
    return ""
