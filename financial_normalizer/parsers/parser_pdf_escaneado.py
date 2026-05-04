"""
Scanned PDF parser: pdf2image → OpenCV preprocessing → pytesseract OCR (TSV layout mode).
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_path

from . import ParseError
from ..profiles import get_profile
from ..parsers.parser_pdf_texto import _parse_text


def parse(filepath: str | Path, cliente_id: str = "default") -> dict:
    profile = get_profile(cliente_id)
    scale = profile.get("scale", 1.0)

    try:
        images = convert_from_path(str(filepath), dpi=300)
    except Exception as exc:
        raise ParseError(f"pdf2image failed: {exc}") from exc

    if not images:
        raise ParseError("No pages found in scanned PDF.")

    full_text_parts: list[str] = []
    for img in images:
        processed = _preprocess(img)
        text = pytesseract.image_to_string(processed, lang="spa", config="--psm 6")
        full_text_parts.append(text)

    full_text = "\n".join(full_text_parts)
    if not full_text.strip():
        raise ParseError("OCR produced no text from scanned PDF.")

    result = _parse_text(full_text, cliente_id, scale)
    result["fuente"] = "pdf_escaneado"
    return result


def _preprocess(pil_image) -> np.ndarray:
    """Grayscale → threshold → deskew."""
    img = np.array(pil_image)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    deskewed = _deskew(thresh)
    return deskewed


def _deskew(image: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(image < 128))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.5:
        return image
    h, w = image.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    return rotated
