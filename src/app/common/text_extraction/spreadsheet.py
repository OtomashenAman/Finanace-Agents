import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook

from src.app.common.text_extraction.base import (
    ExtractedText,
    ExtractionError,
    check_zip_archive,
)

CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float):
        # Avoid binary-float noise like 12500.000000001 in finance figures
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value).strip()


def extract_xlsx(data: bytes) -> ExtractedText:
    check_zip_archive(data, "XLSX")
    try:
        # data_only: cached cell values, never formulas; read_only: streaming, low memory
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for broken files
        raise ExtractionError("This XLSX file is damaged and can't be read.") from exc

    sections = []
    try:
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [cell_text(v) for v in row]
                if any(cells):
                    rows.append(" | ".join(cells).rstrip(" |"))
            if rows:
                sections.append(f"## Sheet: {sheet.title}\n" + "\n".join(rows))
        sheet_count = len(workbook.worksheets)
    finally:
        workbook.close()

    if not sections:
        raise ExtractionError("This spreadsheet has no data.")
    return ExtractedText("\n\n".join(sections), "xlsx", CONTENT_TYPE, page_count=sheet_count)
