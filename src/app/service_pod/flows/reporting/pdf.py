"""A small PDF writer for the management pack: text, rules and simple tables on A4 pages,
in the built-in Helvetica fonts (no font files, no external library). The output is plain
PDF 1.4 that any viewer opens; the bytes are deterministic for the same content and time."""

from collections.abc import Sequence

A4 = (595, 842)
MARGIN = 48
LINE = {9: 12, 10: 13, 12: 16, 16: 20}


def _escape(text: str) -> str:
    # Helvetica with WinAnsi: keep Latin-1, replace the rest
    safe = text.replace("\u2192", "->").replace("\u2212", "-").replace("\u2013", "-")
    safe = safe.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _width(text: str, size: int) -> float:
    """Rough Helvetica width (good enough for wrapping and right-aligned numbers)."""
    return len(text) * size * 0.5


class Pack:
    def __init__(self, title: str) -> None:
        self.title = title
        self.pages: list[list[str]] = []
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.pages.append([])
        self.y = A4[1] - MARGIN

    def _need(self, height: float) -> None:
        if self.y - height < MARGIN + 20:
            self._new_page()

    def _text(self, x: float, y: float, text: str, size: int, bold: bool) -> None:
        font = "F2" if bold else "F1"
        self.pages[-1].append(f"BT /{font} {size} Tf {x:.1f} {y:.1f} Td ({_escape(text)}) Tj ET")

    def heading(self, text: str, size: int = 12) -> None:
        # keep a heading with at least three lines of what follows it
        self._need(LINE.get(size, size + 4) + 8 + 3 * LINE[10])
        self.y -= 6
        self._text(MARGIN, self.y, text, size, True)
        self.y -= LINE.get(size, size + 4)

    def paragraph(self, text: str, size: int = 10, bold: bool = False) -> None:
        width = A4[0] - 2 * MARGIN
        words, line = text.split(), ""
        for word in words:
            trial = f"{line} {word}".strip()
            if _width(trial, size) > width and line:
                self._need(LINE[size])
                self._text(MARGIN, self.y, line, size, bold)
                self.y -= LINE[size]
                line = word
            else:
                line = trial
        if line:
            self._need(LINE[size])
            self._text(MARGIN, self.y, line, size, bold)
            self.y -= LINE[size]

    def rule(self) -> None:
        self._need(8)
        self.y -= 2
        self.pages[-1].append(
            f"0.8 G {MARGIN} {self.y:.1f} m {A4[0] - MARGIN} {self.y:.1f} l S 0 G"
        )
        self.y -= 8

    def table(self, rows: Sequence[Sequence[str]], widths: Sequence[float], size: int = 9) -> None:
        """First row is the header; columns after the first are right-aligned."""
        for i, row in enumerate(rows):
            self._need(LINE[size])
            x = float(MARGIN)
            for j, (cell, w) in enumerate(zip(row, widths, strict=False)):
                text = str(cell)
                cx = x if j == 0 else x + w - _width(text, size)
                self._text(cx, self.y, text, size, i == 0)
                x += w
            self.y -= LINE[size]
        self.y -= 4

    def render(self) -> bytes:
        objects: list[bytes] = []

        def add(body: str | bytes) -> int:
            objects.append(body.encode("latin-1") if isinstance(body, str) else body)
            return len(objects)

        catalog = add("")  # placeholders filled below
        pages_obj = add("")
        f1 = add(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        f2 = add(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        )
        kids = []
        total = len(self.pages)
        for n, ops in enumerate(self.pages, start=1):
            footer = (
                f"BT /F1 8 Tf {MARGIN} 24 Td ({_escape(self.title)} - page {n} of {total}) Tj ET"
            )
            stream = "\n".join([*ops, footer]).encode("latin-1")
            content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            kids.append(
                add(
                    f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                    f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> "
                    f"/Contents {content} 0 R >>"
                )
            )
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
        objects[pages_obj - 1] = (
            f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {total} >>"
        ).encode()

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode()
        out += f"startxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
