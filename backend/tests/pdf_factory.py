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


def make_layout_pdf(path: Path, pages: list[list[dict]], *, metadata: dict | None = None) -> Path:
    """Full control over placement. Each item: {"text", "x"=72, "y", "size"=10, "font"="helv", "rotate"=0}.

    Items are written in list order, which is the order a PDF producer would emit them in.
    Items without "y" flow down the page below the previous one.
    """
    doc = pymupdf.open()
    for items in pages:
        page = doc.new_page()
        y = 72.0
        for item in items:
            size = item.get("size", 10)
            if "y" in item:
                y = item["y"]
            page.insert_text((item.get("x", 72), y), item["text"], fontsize=size,
                             fontname=item.get("font", "helv"), rotate=item.get("rotate", 0))
            if "y" not in item or item.get("advance", True):
                y += size + 6
    if metadata:
        doc.set_metadata(metadata)
    doc.save(path)
    doc.close()
    return path


class KnownPaper:
    """A test paper whose metadata and contents we know, so expected values come from the input."""

    TITLE = "Tidal Attention Pruning for Protein Contact Maps"
    AUTHORS = ["Ingrid Halvorsen", "Chidi Okafor", "Lucia Ferrante"]
    YEAR = 2024
    ABSTRACT = "We study how attention heads in protein language models can be pruned without losing accuracy."
    # Facts that appear ONLY in the body on page 2 -- never in the title, abstract, or metadata.
    BODY_FACT_1 = "18,437"
    BODY_FACT_2 = "58.3"

    @classmethod
    def pages(cls) -> list[list[Line]]:
        return [
            [
                (cls.TITLE, 18),
                "Ingrid Halvorsen, Chidi Okafor and Lucia Ferrante",
                "Institute for Computational Biology, Example University",
                f"Workshop on Efficient Biology Models, {cls.YEAR}",
                "Abstract",
                cls.ABSTRACT,
                "1 Introduction",
                "Protein language models are slow at inference time.",
            ],
            [
                "2 Experiments",
                f"The KESTREL-Contacts benchmark contains exactly {cls.BODY_FACT_1} protein chains.",
                f"Removing the saliency warm-up drops P@L/5 from 71.9 to {cls.BODY_FACT_2}.",
            ],
        ]

    @classmethod
    def build(cls, path: Path) -> bytes:
        return make_pdf(path, cls.pages()).read_bytes()


def pdf_bytes(tmp_path: Path, pages: list[list[Line]], name: str = "doc.pdf", **kwargs) -> bytes:
    return make_pdf(tmp_path / name, pages, **kwargs).read_bytes()
