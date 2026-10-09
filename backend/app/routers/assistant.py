from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..db import get_session
from ..deps import get_paper_service
from ..models import AskRequest, AskResponse, MessageOut, SummaryResponse
from ..services.llm_service import LLMError, LLMNotConfigured, LLMRateLimited
from ..services.paper_service import PaperService
from .papers import get_paper_or_404

router = APIRouter(prefix="/api/papers", tags=["assistant"])


def _llm_http_error(exc: LLMError) -> HTTPException:
    if isinstance(exc, LLMRateLimited):
        return HTTPException(503, "The LLM is rate limited right now. Try again in a minute.")
    if isinstance(exc, LLMNotConfigured):
        return HTTPException(503, "GEMINI_API_KEY is not configured on the server.")
    return HTTPException(502, str(exc))


@router.post("/{paper_id}/summary", response_model=SummaryResponse)
async def summarize(
    paper_id: int,
    refresh: bool = False,
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    paper = get_paper_or_404(session, paper_id)
    try:
        summary, basis = await service.summarize(session, paper, refresh=refresh)
    except LLMError as exc:
        raise _llm_http_error(exc)
    return SummaryResponse(summary=summary, summary_basis=basis)


@router.get("/{paper_id}/messages", response_model=list[MessageOut])
def list_messages(
    paper_id: int,
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    get_paper_or_404(session, paper_id)
    return [MessageOut(**m.model_dump()) for m in service.messages(session, paper_id)]


@router.post("/{paper_id}/ask", response_model=AskResponse)
async def ask(
    paper_id: int,
    body: AskRequest,
    session: Session = Depends(get_session),
    service: PaperService = Depends(get_paper_service),
):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Question is empty")
    paper = get_paper_or_404(session, paper_id)
    try:
        answer, basis = await service.ask(session, paper, question)
    except LLMError as exc:
        raise _llm_http_error(exc)
    return AskResponse(answer=answer, content_basis=basis)
