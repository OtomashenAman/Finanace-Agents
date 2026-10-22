import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ExtractedText:
    text: str
    extractor: str  # e.g. "pdf", "xlsx"
    content_type: str
    page_count: int | None = None  # pages (PDF) or sheets (XLSX)
    warnings: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    """The file can't be turned into text. The message is safe to show to users."""


Extractor = Callable[[bytes], ExtractedText]

# XLSX/DOCX are ZIP archives: refuse anything that inflates absurdly (zip bombs)
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def check_zip_archive(data: bytes, kind: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"This {kind} file is damaged and can't be read.") from exc
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ExtractionError(f"This {kind} file expands to more than 100 MB and was refused.")
