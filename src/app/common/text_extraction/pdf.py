import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.app.common.text_extraction.base import ExtractedText, ExtractionError

CONTENT_TYPE = "application/pdf"
# Below this many characters across all pages the PDF is treated as scanned (image only)
MIN_TEXT_CHARS = 20


def extract_pdf(data: bytes) -> ExtractedText:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("This PDF is password protected. Upload an unprotected copy.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError("This PDF is damaged and can't be read.") from exc

    if sum(len(p.strip()) for p in pages) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "This PDF has no text layer (it looks scanned). Upload a text-based PDF "
            "or the original CSV/XLSX export."
        )

    warnings = []
    empty = [str(i) for i, p in enumerate(pages, start=1) if not p.strip()]
    if empty:
        warnings.append(f"No text found on page(s) {', '.join(empty)} (scanned pages?)")
    text = "\n\n".join(f"--- Page {i} ---\n{p.strip()}" for i, p in enumerate(pages, start=1))
    return ExtractedText(text, "pdf", CONTENT_TYPE, page_count=len(pages), warnings=warnings)
