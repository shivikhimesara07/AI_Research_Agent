from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlmodel import Session, select

from ..db import get_session
from ..deps import get_paper_service
from ..models import Paper, PaperMeta, PaperOut
from ..services.paper_service import PaperService

router = APIRouter(prefix="/api/papers", tags=["papers"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def get_paper_or_404(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found")
    return paper


@router.get("", response_model=list[PaperOut])
def list_papers(session: Session = Depends(get_session)):
    papers = session.exec(select(Paper).order_by(Paper.created_at.desc())).all()
    return [PaperOut.from_paper(p) for p in papers]


@router.post("", response_model=PaperOut, status_code=201)
def save_paper(
    meta: PaperMeta,
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    return PaperOut.from_paper(service.save_meta(session, meta))


@router.post("/upload", response_model=PaperOut, status_code=201)
async def upload_paper(
    response: Response,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    """201 with a new paper, or 200 with the existing paper when the same PDF was uploaded before."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "PDF is larger than 25 MB")
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(400, "File is not a PDF")
    try:
        paper, created = await service.ingest_upload(session, file.filename or "upload.pdf", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not created:
        response.status_code = 200
    return PaperOut.from_paper(paper)


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(paper_id: int, session: Session = Depends(get_session)):
    return PaperOut.from_paper(get_paper_or_404(session, paper_id))


@router.delete("/{paper_id}", status_code=204)
def delete_paper(
    paper_id: int,
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    service.delete(session, get_paper_or_404(session, paper_id))
