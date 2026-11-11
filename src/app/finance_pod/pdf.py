"""Plain text PDFs (client invoices, statements): Helvetica, one column, paged.

Small on purpose: no layout engine, just lines. Each line is (text, size, bold); characters
outside Latin-1 are replaced, since the base fonts can't draw them.
"""

TOP, BOTTOM, LEFT = 790, 60, 50

Line = tuple[str, int, bool]  # text, font size, bold


def _escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render(lines: list[Line]) -> bytes:
    pages: list[list[str]] = [[]]
    y = TOP
    for text, size, bold in lines:
        step = size + 5
        if y - step < BOTTOM:
            pages.append([])
            y = TOP
        y -= step
        font = "F2" if bold else "F1"
        pages[-1].append(f"BT /{font} {size} Tf {LEFT} {y} Td ({_escape(text)}) Tj ET")

    objects: list[str] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",  # the page tree, filled in once the pages are numbered
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for ops in pages:
        stream = "\n".join(ops)
        objects.append(
            f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream"
        )
        content = len(objects)
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"

    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return out
