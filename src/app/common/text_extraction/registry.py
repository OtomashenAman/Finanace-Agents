"""File type detection + extractor lookup. Add a type: write an extractor, register it here."""

from pathlib import PurePath

import filetype

from src.app.common.text_extraction.base import ExtractedText, ExtractionError, Extractor
from src.app.common.text_extraction.delimited import decode_text, extract_csv, extract_plain_text
from src.app.common.text_extraction.pdf import extract_pdf
from src.app.common.text_extraction.spreadsheet import extract_xlsx
from src.app.common.text_extraction.word import extract_docx

# Detected by content (magic bytes), never trusted from the filename
BINARY_EXTRACTORS: dict[str, Extractor] = {
    "pdf": extract_pdf,
    "xlsx": extract_xlsx,
    "docx": extract_docx,
}
# Plain text has no magic bytes: the extension picks the parser once it decodes as text
TEXT_EXTRACTORS: dict[str, Extractor] = {
    ".csv": extract_csv,
    ".tsv": extract_csv,
    ".txt": extract_plain_text,
}
IMAGE_TYPES = {"jpg", "png", "gif", "webp", "tif", "bmp", "heic"}

SUPPORTED_LABEL = "PDF (text-based), XLSX, CSV, DOCX or TXT"


def extract_text(data: bytes, filename: str) -> ExtractedText:
    """Turn an uploaded file into text, or raise ExtractionError with a user-facing reason."""
    if not data:
        raise ExtractionError("The file is empty.")

    kind = filetype.guess_extension(data)
    if kind in BINARY_EXTRACTORS:
        return BINARY_EXTRACTORS[kind](data)
    if kind in IMAGE_TYPES:
        raise ExtractionError(
            "Images and scanned documents aren't supported yet (no OCR). "
            f"Upload a {SUPPORTED_LABEL} file."
        )
    if kind is None:
        suffix = PurePath(filename).suffix.lower()
        if suffix in TEXT_EXTRACTORS and decode_text(data) is not None:
            return TEXT_EXTRACTORS[suffix](data)
    raise ExtractionError(f"Unsupported file type. Upload a {SUPPORTED_LABEL} file.")
