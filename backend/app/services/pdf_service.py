"""PDF handling: text extraction, identifier/metadata heuristics, reference stripping, download.

Nothing in here talks to Semantic Scholar or the LLM; paper_service orchestrates those.
"""
import logging
import re
from pathlib import Path

import pymupdf as fitz
import httpx

from ..models import ExtractedMetadata

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 25 * 1024 * 1024
FULL_TEXT_CHAR_CAP = 120_000

# arXiv margin stamp, e.g. "arXiv:2106.09685v2 [cs.CL] 16 Oct 2021" -- almost always the paper's own id.
_ARXIV_STAMP = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?\s*\[[\w.\-]+\]")
_ARXIV_NEW = re.compile(r"(?:arXiv:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_ARXIV_OLD = re.compile(r"(?:arXiv:\s*|arxiv\.org/(?:abs|pdf)/)([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", re.I)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)")

_REF_HEADING = re.compile(
    r"^[ \t]*(?:\d+\.?|[IVX]+\.)?[ \t]*(references|bibliography|works cited)[ \t]*$",
    re.I | re.M,
)
_APPENDIX_HEADING = re.compile(
    r"^[ \t]*(?:[A-Z]\.?[ \t]+)?(?i:appendix|appendices|supplementary material)\b.*$"
    # Lettered first appendix section: "A" alone on its line followed by a heading,
    # or "A." / "A " followed by an ALL-CAPS heading on the same line.
    r"|^[ \t]*A\.?[ \t]*\n[ \t]*[A-Z][^\n]{3,100}$"
    r"|^[ \t]*A\.?[ \t]+[A-Z][A-Z0-9 ,:\-]{6,}$",
    re.M,
)
_ABSTRACT = re.compile(
    r"\babstract\b[\s.:—\-]*(.+?)(?=\n\s*(?:\d\.?|I\.?)?\s*(?:introduction|keywords|index terms|ccs concepts)\b)",
    re.I | re.S,
)
_YEAR = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
_AFFILIATION_WORDS = re.compile(
    r"university|institute|department|school|college|laboratory|lab\b|inc\.|corp|google|microsoft|@|\d{3,}",
    re.I,
)


# Expand ligatures (\ufb01 -> "fi") and join words hyphenated across line breaks.
TEXT_FLAGS = (fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_LIGATURES) | fitz.TEXT_DEHYPHENATE
DICT_FLAGS = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES


class PdfService:
    def __init__(self, *, user_agent: str = "ResearchAssistant/0.1", timeout: float = 20.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.user_agent = user_agent
        self.timeout = timeout
        self._transport = transport

    # ---------- extraction ----------

    def extract_text(self, path: Path) -> tuple[str, str]:
        """Return (full_text, first_two_pages_text)."""
        with fitz.open(path) as doc:
            pages = [page.get_text("text", flags=TEXT_FLAGS) for page in doc]
        return "\n".join(pages), "\n".join(pages[:2])

    def find_identifiers(self, text: str) -> list[str]:
        """S2 lookup identifiers in priority order: arXiv stamp, then everything else in page order."""
        found: list[str] = []

        def add(ident: str) -> None:
            if ident not in found:
                found.append(ident)

        for m in _ARXIV_STAMP.finditer(text):
            add(f"arXiv:{m.group(1)}")

        hits: list[tuple[int, str]] = []
        for m in _ARXIV_NEW.finditer(text):
            hits.append((m.start(), f"arXiv:{m.group(1)}"))
        for m in _ARXIV_OLD.finditer(text):
            hits.append((m.start(), f"arXiv:{m.group(1)}"))
        for m in _DOI.finditer(text):
            doi = m.group(1).rstrip(".,;:)]}")
            hits.append((m.start(), f"DOI:{doi}"))
        for _, ident in sorted(hits):
            add(ident)
        return found

    def extract_abstract(self, text: str) -> str | None:
        m = _ABSTRACT.search(text)
        if not m:
            return None
        abstract = re.sub(r"(\w)- (\w)", r"\1\2", " ".join(m.group(1).split()))
        return abstract[:3000] or None

    def layout_metadata(self, path: Path, first_pages_text: str) -> ExtractedMetadata | None:
        """Font-size/layout heuristics over page 1. Last-resort metadata source."""
        try:
            with fitz.open(path) as doc:
                if not doc.page_count:
                    return None
                page = doc[0]
                page_height = page.rect.height
                pdf_meta = doc.metadata or {}
                lines = []
                for block in page.get_text("dict", flags=DICT_FLAGS)["blocks"]:
                    for line in block.get("lines", []):
                        if line.get("dir", (1, 0)) != (1, 0):
                            continue  # skip rotated text such as the arXiv margin stamp
                        text = "".join(s["text"] for s in line["spans"]).strip()
                        if not text:
                            continue
                        size = max(s["size"] for s in line["spans"])
                        lines.append((line["bbox"][1], size, text))
        except Exception as exc:  # corrupt PDF etc.
            log.info("layout heuristics failed: %s", exc)
            return None

        if not lines:
            return None
        lines.sort(key=lambda t: t[0])
        top = [l for l in lines if l[0] < page_height * 0.5] or lines
        max_size = max(l[1] for l in top)

        # Title: consecutive lines at (near) the largest font size.
        title_parts, title_end = [], None
        for i, (_, size, text) in enumerate(lines):
            if abs(size - max_size) < 0.6:
                title_parts.append(text)
                title_end = i
            elif title_parts:
                break
        title = re.sub(r"(\w)- (\w)", r"\1\2", " ".join(title_parts)).strip() or (pdf_meta.get("title") or "").strip()

        # Authors: lines between the title and the "Abstract" heading, minus affiliations/emails.
        authors: list[str] = []
        if title_end is not None:
            for _, _, text in lines[title_end + 1:]:
                if re.match(r"^\s*abstract\b", text, re.I):
                    break
                if _AFFILIATION_WORDS.search(text) or len(text) > 120:
                    continue
                for name in re.split(r",|\band\b|;|∗|\*|\d", text):
                    name = name.strip(" ,.*†‡")
                    if 2 <= len(name.split()) <= 4 and all(w[:1].isupper() for w in name.split()):
                        authors.append(name)
                if len(authors) >= 12:
                    break
        if not authors and pdf_meta.get("author"):
            authors = [a.strip() for a in re.split(r",|;|\band\b", pdf_meta["author"]) if a.strip()]

        year = None
        stamp = _ARXIV_STAMP.search(first_pages_text)
        header = re.split(r"\babstract\b", first_pages_text, maxsplit=1, flags=re.I)[0]
        m = _YEAR.search(header)
        if stamp:
            year = 2000 + int(stamp.group(1)[:2])  # arXiv ids start with YYMM of first submission
        elif m:
            year = int(m.group(1))
        elif (pdf_meta.get("creationDate") or "").startswith("D:"):
            year = int(pdf_meta["creationDate"][2:6])

        if not title:
            return None
        return ExtractedMetadata(
            title=title, authors=authors, year=year, abstract=self.extract_abstract(first_pages_text)
        )

    # ---------- LLM budget ----------

    def strip_references(self, text: str, cap: int = FULL_TEXT_CHAR_CAP) -> str:
        """Drop the bibliography (keeping any appendix after it), then cap the length."""
        refs = [m for m in _REF_HEADING.finditer(text) if m.start() > len(text) * 0.5]
        if refs:
            ref = refs[-1]
            body = text[: ref.start()]
            appendix = _APPENDIX_HEADING.search(text, ref.end())
            if appendix:
                body = body.rstrip() + "\n\n" + text[appendix.start():]
            text = body
        return text[:cap]

    # ---------- download (fails soft) ----------

    async def download_pdf(self, url: str, dest: Path) -> Path | None:
        """Download a PDF to dest. Returns None (never raises) if it isn't a usable PDF."""
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True, transport=self._transport,
                headers={"User-Agent": self.user_agent, "Accept": "application/pdf,*/*;q=0.8"},
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        log.info("PDF download %s -> HTTP %s", url, resp.status_code)
                        return None
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > MAX_PDF_BYTES:
                        log.info("PDF download %s too large (%d bytes)", url, declared)
                        return None
                    ctype = resp.headers.get("content-type", "").lower()
                    total, chunks, checked = 0, [], False
                    async for chunk in resp.aiter_bytes():
                        if not checked:
                            # Accept on declared PDF type OR %PDF- magic bytes; publisher HTML fails both.
                            if "application/pdf" not in ctype and b"%PDF-" not in chunk[:1024]:
                                log.info("PDF download %s is not a PDF (content-type %r)", url, ctype)
                                return None
                            checked = True
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            log.info("PDF download %s exceeded %d bytes", url, MAX_PDF_BYTES)
                            return None
                        chunks.append(chunk)
            data = b"".join(chunks)
            if b"%PDF-" not in data[:1024]:
                return None
            dest.write_bytes(data)
            return dest
        except Exception as exc:
            log.info("PDF download %s failed: %s", url, exc)
            return None
