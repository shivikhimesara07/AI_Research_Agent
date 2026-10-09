"""Service providers. Tests replace these via app.dependency_overrides."""
from functools import lru_cache

from fastapi import Depends

from .config import settings
from .services.llm_service import GeminiLLMService, LLMService
from .services.paper_service import PaperService
from .services.pdf_service import PdfService
from .services.s2_client import S2Client
from .services.search_service import ArxivClient, SearchService


@lru_cache
def get_s2_client() -> S2Client:
    # One shared instance so the throttle applies across all requests. Without a key S2 almost
    # always answers 429, so don't spend seconds retrying before the arXiv fallback.
    return S2Client(
        settings.s2_base_url,
        settings.s2_api_key,
        max_attempts=3 if settings.s2_api_key else 1,
        user_agent=settings.user_agent,
    )


@lru_cache
def get_search_service() -> SearchService:
    return SearchService(get_s2_client(), ArxivClient(settings.arxiv_base_url, user_agent=settings.user_agent))


@lru_cache
def get_pdf_service() -> PdfService:
    return PdfService(user_agent=settings.user_agent)


@lru_cache
def get_llm_service() -> LLMService:
    return GeminiLLMService(settings.gemini_api_key, settings.gemini_model)


def get_paper_service(
    pdf: PdfService = Depends(get_pdf_service),
    llm: LLMService = Depends(get_llm_service),
) -> PaperService:
    return PaperService(get_s2_client(), pdf, llm, settings.upload_dir)
