from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..deps import get_search_service
from ..models import Paper, SearchResponse
from ..services.search_service import SearchBadRequest, SearchService, SearchUnavailable

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    service: SearchService = Depends(get_search_service),
    session: Session = Depends(get_session),
):
    try:
        resp = await service.search(q.strip(), limit)
    except SearchBadRequest as exc:
        raise HTTPException(400, str(exc))
    except SearchUnavailable as exc:
        raise HTTPException(503, str(exc))

    ids = [r.external_id for r in resp.results if r.external_id]
    if ids:
        saved = session.exec(select(Paper.external_id, Paper.id).where(Paper.external_id.in_(ids))).all()
        saved_map = dict(saved)
        for r in resp.results:
            r.saved_id = saved_map.get(r.external_id)
    return resp
