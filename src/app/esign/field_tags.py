"""PandaDoc field tags in a template's text: where signers sign, and the dynamic fields.

A tag is `{type*:role:id___}` (https://developers.pandadoc.com/docs/field-tags):

- type: textfield (t), date (d), checkbox (c), signature (s), initials (i), dropdown (dd),
  radio (r), stamp (st)
- `*` after the type: not required
- role: who fills it in. Here always signer1, signer2... (the 1st, 2nd... signer of a send)
- id (optional): names the field, so its value can be filled in when the document is sent
- underscores: make the field wider

PandaDoc turns each tag into a field when the document is created; this module only reads
them, so the app can show a template's fields and ask for their values before sending.
"""

import io
import re
import zipfile
from dataclasses import asdict, dataclass
from typing import Any

from docx import Document
from pypdf import PdfReader

TYPES = {
    "textfield": "textfield",
    "t": "textfield",
    "date": "date",
    "d": "date",
    "checkbox": "checkbox",
    "c": "checkbox",
    "signature": "signature",
    "s": "signature",
    "initials": "initials",
    "i": "initials",
    "dropdown": "dropdown",
    "dd": "dropdown",
    "radio": "radio",
    "r": "radio",
    "stamp": "stamp",
    "st": "stamp",
}
# Types whose value the sender can fill in when sending (the signer sees it filled in)
PREFILLABLE = frozenset({"textfield", "date", "checkbox"})
ROLE = re.compile(r"^signer([1-9]|10)$")

_TAG = re.compile(
    r"\{\s*(?P<type>[A-Za-z]+)(?P<optional>\*)?\s*:\s*(?P<role>[A-Za-z0-9]+)"
    r"(?:\s*:\s*(?P<id>[A-Za-z0-9-]+))?\s*_*\s*\}"
)


@dataclass(frozen=True)
class FieldTag:
    type: str  # the long name: textfield, date, signature...
    role: str
    id: str | None
    required: bool

    @property
    def prefillable(self) -> bool:
        return self.id is not None and self.type in PREFILLABLE

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "prefillable": self.prefillable}


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        return ""
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    for section in document.sections:
        for part in (section.header, section.footer):
            parts.extend(p.text for p in part.paragraphs)
    return "\n".join(parts)


def _rtf_text(data: bytes) -> str:
    text = data.decode("latin-1", "replace")
    # Drop control words and groups' braces that aren't part of a tag
    text = re.sub(r"\\[a-z]+-?\d* ?", "", text)
    return text


def read_text(data: bytes, content_type: str) -> str:
    """The template's text; empty when it can't be read (PandaDoc still gets the file)."""
    try:
        if content_type == "application/pdf":
            return _pdf_text(data)
        if content_type == "application/rtf":
            return _rtf_text(data)
        if zipfile.is_zipfile(io.BytesIO(data)):
            return _docx_text(data)
    except Exception:  # odd files: no tags found, the upload itself still works
        return ""
    return ""


def find_tags(text: str) -> list[FieldTag]:
    """Every field tag, in order, once per (type, role, id) (ids name one field)."""
    found: list[FieldTag] = []
    seen: set[tuple[str, str, str | None]] = set()
    for m in _TAG.finditer(text):
        kind = TYPES.get(m["type"].lower())
        if kind is None:
            continue
        key = (kind, m["role"], m["id"])
        if m["id"] is None or key not in seen:
            seen.add(key)
            found.append(FieldTag(kind, m["role"], m["id"], m["optional"] is None))
    return found


def problems(tags: list[FieldTag]) -> list[str]:
    """What PandaDoc would refuse, said before anything is sent."""
    out = []
    bad_roles = sorted({t.role for t in tags if not ROLE.match(t.role)})
    if bad_roles:
        out.append(
            "Field tags must name the signer as signer1, signer2... "
            f"(found: {', '.join(bad_roles)})."
        )
    by_id: dict[str, set[tuple[str, str]]] = {}
    for t in tags:
        if t.id:
            by_id.setdefault(t.id, set()).add((t.type, t.role))
    clashes = sorted(i for i, uses in by_id.items() if len(uses) > 1)
    if clashes:
        out.append(f"A field id is used for different fields: {', '.join(clashes)}.")
    return out


def signers_needed(tags: list[dict[str, Any]]) -> int:
    """How many signers the template's tags expect (signer3 -> 3)."""
    numbers = [int(m[1]) for t in tags if (m := ROLE.match(str(t.get("role", ""))))]
    return max(numbers, default=0)
