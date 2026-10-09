"""Shared fixtures: fake services injected through deps.py + an in-memory SQLite DB."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import deps
from app.db import get_session, init_db
from app.main import create_app
from app.models import ExtractedMetadata, SearchResponse, SearchResult


class FakeSearchService:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        self.response = SearchResponse(
            source="semantic_scholar",
            results=[
                SearchResult(
                    source="semantic_scholar",
                    external_id="fake-1",
                    title="Attention Is All You Need",
                    authors=["Ashish Vaswani", "Noam Shazeer"],
                    year=2017,
                    abstract="We propose the Transformer.",
                    url="https://example.org/paper",
                )
            ],
        )

    async def search(self, query: str, limit: int = 20) -> SearchResponse:
        self.calls.append((query, limit))
        return self.response.model_copy(deep=True)


class FakePdfService:
    def __init__(self):
        self.downloads: list[str] = []
        self.full_text = "Fake full text of the paper.\nIntroduction\n..."

    def extract_text(self, path: Path) -> tuple[str, str]:
        return self.full_text, self.full_text[:2000]

    def find_identifiers(self, text: str) -> list[str]:
        return []

    def extract_abstract(self, text: str) -> str | None:
        return "Fake abstract."

    def layout_metadata(self, path: Path, first_pages_text: str) -> ExtractedMetadata | None:
        return ExtractedMetadata(title="Layout Title", authors=["A. Author"], year=2020)

    def strip_references(self, text: str, cap: int = 120_000) -> str:
        return text[:cap]

    async def download_pdf(self, url: str, dest: Path) -> Path | None:
        self.downloads.append(url)
        return None


class FakeLLMService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def summarize(self, title: str, text: str, basis: str) -> str:
        self.calls.append(("summarize", title, basis))
        return f"Summary of {title} ({basis})"

    async def answer(self, title, text, basis, history, question) -> str:
        self.calls.append(("answer", question, list(history)))
        return f"Answer to: {question}"

    async def extract_metadata(self, first_pages_text: str) -> ExtractedMetadata | None:
        self.calls.append(("extract_metadata",))
        return ExtractedMetadata(title="LLM Title", authors=["L. Model"], year=2024, abstract="LLM abstract.")


@pytest.fixture
def engine():
    # StaticPool: every connection shares the same in-memory DB (otherwise each gets an empty one).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_search():
    return FakeSearchService()


@pytest.fixture
def fake_pdf():
    return FakePdfService()


@pytest.fixture
def fake_llm():
    return FakeLLMService()


@pytest.fixture
def client(engine, fake_search, fake_pdf, fake_llm, tmp_path):
    app = create_app(engine=engine)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[deps.get_search_service] = lambda: fake_search
    app.dependency_overrides[deps.get_pdf_service] = lambda: fake_pdf
    app.dependency_overrides[deps.get_llm_service] = lambda: fake_llm
    app.dependency_overrides[deps.get_paper_service] = lambda: deps.PaperService(
        deps.get_s2_client(), fake_pdf, fake_llm, tmp_path / "uploads"
    )
    with TestClient(app) as c:
        yield c
