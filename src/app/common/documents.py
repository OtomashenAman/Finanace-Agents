"""Getting a document in front of an agent: its text when it has one, else page images.

Text-based PDF, DOCX, XLSX, CSV and TXT give text, and figures the agent reads from them are
checked against that text. Photos (PNG/JPEG) and scanned PDFs (their embedded page images,
first pages only) go to the vision model as images; what it reads there can't be checked
against text, so it's marked for a person to confirm.
"""

import io
from dataclasses import dataclass, field

import filetype
from pypdf import PdfReader

from src.app.common.text_extraction.base import ExtractionError
from src.app.common.text_extraction.registry import extract_text
from src.app.core.llm.base import ImageInput

MAX_PAGES = 3
MAX_TEXT = 30_000
IMAGE_KINDS = {"png": "image/png", "jpg": "image/jpeg"}


@dataclass
class DocumentInput:
    text: str | None = None
    images: list[ImageInput] = field(default_factory=list)
    problem: str | None = None  # why neither could be had

    @property
    def readable(self) -> bool:
        return bool(self.text) or bool(self.images)


def _pdf_images(data: bytes, max_pages: int) -> list[ImageInput]:
    images: list[ImageInput] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for page in reader.pages[:max_pages]:
            for image in page.images:
                kind = filetype.guess_extension(image.data)
                if kind in IMAGE_KINDS:
                    images.append(ImageInput(IMAGE_KINDS[kind], image.data))
    except Exception:  # pypdf raises many types for odd files
        return []
    return images


def prepare(data: bytes, filename: str, max_pages: int = MAX_PAGES) -> DocumentInput:
    """`max_pages`: how many page images of a scanned PDF to take (a statement needs more
    than a tax form)."""
    kind = filetype.guess_extension(data)
    if kind in IMAGE_KINDS:
        return DocumentInput(images=[ImageInput(IMAGE_KINDS[kind], data)])
    try:
        text = extract_text(data, filename).text.strip()
    except ExtractionError as exc:
        text, reason = "", str(exc)
    else:
        reason = "no text in the document"
    if text:
        return DocumentInput(text=text[:MAX_TEXT])
    if kind == "pdf":
        images = _pdf_images(data, max_pages)
        if images:
            return DocumentInput(images=images)
        reason = "a scanned PDF whose pages couldn't be read as images"
    return DocumentInput(problem=reason)


def digits(value: str | None) -> str:
    return "".join(c for c in value or "" if c.isdigit())
