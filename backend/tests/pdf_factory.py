"""Build small real PDFs for tests with PyMuPDF.

A page is a list of lines; each line is either a string (10pt) or a (text, fontsize) tuple.
"""
from pathlib import Path

import pymupdf

Line = str | tuple[str, float]


def make_pdf(
    path: Path,
    pages: list[list[Line]],
    *,
    stamp: str | None = None,
    metadata: dict | None = None,
) -> Path:
    doc = pymupdf.open()
    for i, lines in enumerate(pages):
        page = doc.new_page()
        y = 72.0
        for line in lines:
            text, size = (line, 10.0) if isinstance(line, str) else line
            page.insert_text((72, y), text, fontsize=size)
            y += size + 6
        if stamp and i == 0:
            # Rotated text in the left margin, like the arXiv submission stamp.
            page.insert_text((30, 600), stamp, fontsize=14, rotate=90)
    if metadata:
        doc.set_metadata(metadata)
    doc.save(path)
    doc.close()
    return path


def pdf_bytes(tmp_path: Path, pages: list[list[Line]], name: str = "doc.pdf", **kwargs) -> bytes:
    return make_pdf(tmp_path / name, pages, **kwargs).read_bytes()
