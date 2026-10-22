import csv
import io

from charset_normalizer import from_bytes

from src.app.common.text_extraction.base import ExtractedText, ExtractionError


def decode_text(data: bytes) -> str | None:
    """Decode bytes in an unknown encoding; None if it doesn't look like text."""
    if b"\x00" in data[:4096]:
        return None
    best = from_bytes(data).best()
    return str(best) if best is not None else None


def extract_csv(data: bytes) -> ExtractedText:
    text = decode_text(data)
    if text is None:
        raise ExtractionError("This CSV file isn't readable text.")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], ",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [" | ".join(c.strip() for c in row) for row in csv.reader(io.StringIO(text), dialect)]
    rows = [r for r in rows if r.strip(" |")]
    if not rows:
        raise ExtractionError("This CSV file has no data.")
    return ExtractedText("\n".join(rows), "csv", "text/csv")


def extract_plain_text(data: bytes) -> ExtractedText:
    text = decode_text(data)
    if text is None or not text.strip():
        raise ExtractionError("This text file is empty or unreadable.")
    return ExtractedText(text.strip(), "text", "text/plain")
