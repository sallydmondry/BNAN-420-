"""Get text out of an uploaded offer, entirely in memory and offline.

* PDF  -> embedded text via pdfplumber; scanned PDFs fall back to page images + OCR.
* Image (PNG/JPEG/WebP) -> RapidOCR (ONNX models bundled with the package; no network).
* DOCX -> python-docx paragraphs and tables.
* TXT / EML / MD -> UTF-8 decode.

PRIVACY: bytes are never written to disk and text is never logged.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

TextSource = Literal["text", "pdf_text", "ocr"]

_OCR = None
_OCR_LOCK = threading.Lock()


class UnsupportedFile(ValueError):
    """Raised for file types TrueOffer cannot read."""


@dataclass
class Extraction:
    text: str
    source: TextSource
    pages: int = 1
    warnings: list[str] = field(default_factory=list)


def _ocr_engine():
    global _OCR
    with _OCR_LOCK:
        if _OCR is None:
            from rapidocr import RapidOCR  # lazy: ~1s model load
            _OCR = RapidOCR()
        return _OCR


def _ocr_image(img) -> str:
    """OCR a PIL image and return its lines in reading order."""
    import numpy as np

    rgb = img.convert("RGB")
    # Small images OCR poorly; upscale so text is at least ~1,600 px wide.
    if rgb.width < 1600:
        scale = 1600 / rgb.width
        rgb = rgb.resize((int(rgb.width * scale), int(rgb.height * scale)))
    eng = _ocr_engine()
    with _OCR_LOCK:
        res = eng(np.array(rgb))
    txts = list(getattr(res, "txts", None) or [])
    return "\n".join(t for t in txts if t and t.strip())


def sniff(content: bytes, file_name: Optional[str], media_type: Optional[str]) -> str:
    """Identify the file kind from magic bytes first, then extension/media type."""
    head = content[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff" or (content[:4] == b"RIFF" and content[8:12] == b"WEBP"):
        return "image"
    if head.startswith(b"PK\x03\x04"):
        name = (file_name or "").lower()
        if name.endswith(".docx") or (media_type or "").endswith("wordprocessingml.document"):
            return "docx"
        raise UnsupportedFile("Zip archives are not supported. Upload a PDF, image, DOCX or text file.")
    try:
        content[:4096].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        pass
    raise UnsupportedFile("Unsupported file type. Upload a PDF, PNG/JPG image, DOCX or text file.")


def extract_text(content: bytes, file_name: Optional[str] = None, media_type: Optional[str] = None,
                 max_pages: int = 10) -> Extraction:
    """Return the text of an uploaded offer and how it was obtained."""
    kind = sniff(content, file_name, media_type)
    if kind == "text":
        return Extraction(text=content.decode("utf-8", errors="replace"), source="text")
    if kind == "docx":
        import docx

        d = docx.Document(io.BytesIO(content))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return Extraction(text="\n".join(parts), source="text")
    if kind == "image":
        from PIL import Image

        with Image.open(io.BytesIO(content)) as img:
            return Extraction(text=_ocr_image(img), source="ocr")
    # PDF
    import pdfplumber

    warnings: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        n = len(pdf.pages)
        if n > max_pages:
            warnings.append(f"Only the first {max_pages} of {n} pages were read.")
        pages = pdf.pages[:max_pages]
        text = "\n".join((p.extract_text() or "") for p in pages)
    if len(text.strip()) >= 80:
        return Extraction(text=text, source="pdf_text", pages=min(n, max_pages), warnings=warnings)
    # Scanned PDF: render pages and OCR them.
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(content)
    try:
        out = []
        for i in range(min(len(doc), max_pages)):
            img = doc[i].render(scale=2.0).to_pil()
            out.append(_ocr_image(img))
    finally:
        doc.close()
    warnings.append("This PDF had no embedded text, so it was read with OCR. Double-check the fields.")
    return Extraction(text="\n".join(out), source="ocr", pages=min(n, max_pages), warnings=warnings)
