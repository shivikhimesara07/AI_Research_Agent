"""Orchestration over the DB + search/PDF/LLM services. No FastAPI imports here."""
import asyncio
import logging
import re
import uuid
from pathlib import Path

from sqlmodel import Session, select

from ..models import ExtractedMetadata, Message, Paper, PaperMeta
from .llm_service import LLMService
from .pdf_service import PdfService
from .s2_client import S2Client, S2Error
from .search_service import s2_to_meta

log = logging.getLogger(__name__)

HISTORY_EXCHANGES = 4  # question/answer pairs sent with each new question


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class PaperService:
    def __init__(self, s2: S2Client, pdf: PdfService, llm: LLMService, upload_dir: Path):
        self.s2 = s2
        self.pdf = pdf
        self.llm = llm
        self.upload_dir = upload_dir

    # ---------- library ----------

    def save_meta(self, session: Session, meta: PaperMeta) -> Paper:
        """Metadata-only save. Never downloads anything (full text is fetched lazily)."""
        if meta.external_id:
            existing = session.exec(select(Paper).where(Paper.external_id == meta.external_id)).first()
            if existing:
                return existing
        paper = Paper(**meta.model_dump())
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper

    def delete(self, session: Session, paper: Paper) -> None:
        if paper.pdf_path:
            Path(paper.pdf_path).unlink(missing_ok=True)
        for msg in session.exec(select(Message).where(Message.paper_id == paper.id)):
            session.delete(msg)
        session.delete(paper)
        session.commit()

    # ---------- upload ----------

    async def ingest_upload(self, session: Session, filename: str, data: bytes) -> Paper:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        path = self.upload_dir / f"upload_{uuid.uuid4().hex}.pdf"
        path.write_bytes(data)
        try:
            full_text, first_pages = await asyncio.to_thread(self.pdf.extract_text, path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ValueError(f"Could not read PDF: {exc}") from exc

        meta, external_id, extra = await self.extract_upload_metadata(first_pages, path, filename)

        if external_id:
            existing = session.exec(select(Paper).where(Paper.external_id == external_id)).first()
            if existing:
                # Same paper already saved from search: attach the PDF and its text to it.
                if existing.pdf_path and existing.pdf_path != str(path):
                    Path(existing.pdf_path).unlink(missing_ok=True)
                existing.pdf_path = str(path)
                existing.full_text = full_text or existing.full_text
                existing.full_text_status = "ok" if full_text.strip() else existing.full_text_status
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing

        paper = Paper(
            source="upload",
            external_id=external_id,
            title=meta.title,
            authors=meta.authors,
            year=meta.year,
            abstract=meta.abstract,
            url=extra.get("url"),
            pdf_path=str(path),
            full_text=full_text if full_text.strip() else None,
            full_text_status="ok" if full_text.strip() else "failed",
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper

    async def extract_upload_metadata(
        self, first_pages: str, path: Path, filename: str = "upload.pdf"
    ) -> tuple[ExtractedMetadata, str | None, dict]:
        """Pipeline: (a) identifier -> S2 lookup, (b) Gemini JSON, (c) layout heuristics.

        Returns (metadata, s2_paper_id_or_None, extras). Stops at the first stage that yields a
        title and at least one author.
        """
        # (a) arXiv id / DOI found in the text, looked up on Semantic Scholar.
        page1_head = _norm(first_pages[:3000])
        for ident in self.pdf.find_identifiers(first_pages)[:5]:
            try:
                item = await self.s2.lookup(ident)
            except S2Error as exc:
                log.info("S2 lookup %s failed: %s", ident, exc)
                continue
            found = s2_to_meta(item)
            # Guard against ids of *cited* papers: the hit's title must appear near the top of page 1.
            if not found.title or _norm(found.title) not in page1_head:
                log.info("S2 lookup %s -> %r doesn't match page 1; skipping", ident, found.title)
                continue
            if found.authors:
                meta = ExtractedMetadata(
                    title=found.title,
                    authors=found.authors,
                    year=found.year,
                    abstract=found.abstract or self.pdf.extract_abstract(first_pages),
                )
                log.info("upload metadata via S2 lookup %s", ident)
                return meta, found.external_id, {"url": found.url, "stage": "s2_lookup"}

        # (b) Gemini structured extraction.
        try:
            meta = await self.llm.extract_metadata(first_pages)
        except Exception as exc:  # not configured, etc.
            log.info("LLM metadata extraction unavailable: %s", exc)
            meta = None
        if meta and meta.title.strip() and meta.authors:
            if not meta.abstract:
                meta.abstract = self.pdf.extract_abstract(first_pages)
            log.info("upload metadata via LLM")
            return meta, None, {"stage": "llm"}

        # (c) PyMuPDF layout heuristics.
        meta = await asyncio.to_thread(self.pdf.layout_metadata, path, first_pages)
        if meta:
            log.info("upload metadata via layout heuristics")
            return meta, None, {"stage": "layout"}

        return (
            ExtractedMetadata(
                title=Path(filename).stem or "Untitled upload",
                authors=[],
                abstract=self.pdf.extract_abstract(first_pages),
            ),
            None,
            {"stage": "filename"},
        )

    # ---------- full text (lazy) ----------

    async def ensure_full_text(self, session: Session, paper: Paper, *, retry_failed: bool = False) -> bool:
        """Make sure paper.full_text is populated if at all possible. Returns True on success.

        Only called from summary/ask -- never from save -- so saving never blocks on a download.
        """
        if paper.full_text:
            return True
        if paper.full_text_status == "failed" and not retry_failed:
            return False

        path = Path(paper.pdf_path) if paper.pdf_path else None
        if not (path and path.exists()):
            path = None
            url = paper.pdf_url
            if not url and paper.external_id and paper.external_id.startswith("arXiv:"):
                url = f"https://arxiv.org/pdf/{paper.external_id.removeprefix('arXiv:')}"
            if url:
                path = await self.pdf.download_pdf(url, self.upload_dir / f"paper_{paper.id}.pdf")

        text = ""
        if path:
            try:
                text, _ = await asyncio.to_thread(self.pdf.extract_text, path)
            except Exception as exc:
                log.info("text extraction failed for paper %s: %s", paper.id, exc)

        if text.strip():
            paper.pdf_path = str(path)
            paper.full_text = text
            paper.full_text_status = "ok"
        else:
            paper.full_text_status = "failed"
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper.full_text_status == "ok"

    def _llm_input(self, paper: Paper) -> tuple[str, str]:
        """(text, basis) to send to the LLM: stripped full text if we have it, else the abstract."""
        if paper.full_text:
            return self.pdf.strip_references(paper.full_text), "full_text"
        return paper.abstract or "(No abstract or full text is available for this paper.)", "abstract"

    # ---------- LLM features ----------

    async def summarize(self, session: Session, paper: Paper, *, refresh: bool = False) -> tuple[str, str]:
        has_full = await self.ensure_full_text(session, paper, retry_failed=refresh)
        cache_ok = paper.summary and (
            paper.summary_basis == "full_text" or (paper.summary_basis == "abstract" and not has_full)
        )
        if cache_ok and not refresh:
            return paper.summary, paper.summary_basis

        text, basis = self._llm_input(paper)
        summary = await self.llm.summarize(paper.title, text, basis)
        paper.summary = summary
        paper.summary_basis = basis
        session.add(paper)
        session.commit()
        return summary, basis

    async def ask(self, session: Session, paper: Paper, question: str) -> tuple[str, str]:
        await self.ensure_full_text(session, paper)
        text, basis = self._llm_input(paper)

        recent = session.exec(
            select(Message)
            .where(Message.paper_id == paper.id)
            .order_by(Message.id.desc())
            .limit(HISTORY_EXCHANGES * 2)
        ).all()
        history = [(m.role, m.content) for m in reversed(recent)]
        # Gemini expects the conversation to start with a user turn.
        while history and history[0][0] != "user":
            history.pop(0)

        log.info("ask paper=%s basis=%s history_messages=%d text_chars=%d", paper.id, basis, len(history), len(text))
        answer = await self.llm.answer(paper.title, text, basis, history, question)
        session.add(Message(paper_id=paper.id, role="user", content=question))
        session.add(Message(paper_id=paper.id, role="assistant", content=answer))
        session.commit()
        return answer, basis

    def messages(self, session: Session, paper_id: int) -> list[Message]:
        return list(
            session.exec(select(Message).where(Message.paper_id == paper_id).order_by(Message.id))
        )
