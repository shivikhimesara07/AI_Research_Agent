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

        self.error: Exception | None = None

    async def search(self, query: str, limit: int = 20) -> SearchResponse:
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.response.model_copy(deep=True)


class FakePdfService:
    def __init__(self):
        self.downloads: list[str] = []
        self.full_text = "Fake full text of the paper.\nIntroduction\n..."
        # Knobs for individual tests:
        self.identifiers: list[str] = []
        self.extract_error: Exception | None = None
        self.download_bytes: bytes | None = None  # set to simulate a successful download
        self.layout_result: ExtractedMetadata | None = ExtractedMetadata(
            title="Layout Title", authors=["A. Author"], year=2020
        )
        self.extract_calls = 0

    def extract_text(self, path: Path) -> tuple[str, str]:
        self.extract_calls += 1
        if self.extract_error:
            raise self.extract_error
        return self.full_text, self.full_text[:2000]

    def find_identifiers(self, text: str) -> list[str]:
        return list(self.identifiers)

    def extract_abstract(self, text: str) -> str | None:
        return "Fake abstract."

    def layout_metadata(self, path: Path, first_pages_text: str) -> ExtractedMetadata | None:
        return self.layout_result

    def strip_references(self, text: str, cap: int = 120_000) -> str:
        return text[:cap]

    async def download_pdf(self, url: str, dest: Path) -> Path | None:
        self.downloads.append(url)
        if self.download_bytes is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.download_bytes)
        return dest


class FakeLLMService:
    def __init__(self):
        self.calls: list[tuple] = []
        # Knobs for individual tests:
        self.error: Exception | None = None  # raised by summarize/answer
        self.metadata_result: ExtractedMetadata | None = ExtractedMetadata(
            title="LLM Title", authors=["L. Model"], year=2024, abstract="LLM abstract."
        )
        self.metadata_error: Exception | None = None

    async def summarize(self, title: str, text: str, basis: str) -> str:
        self.calls.append(("summarize", title, basis))
        if self.error:
            raise self.error
        return f"Summary of {title} ({basis})"

    async def answer(self, title, text, basis, history, question) -> str:
        self.calls.append(("answer", question, list(history)))
        if self.error:
            raise self.error
        return f"Answer to: {question}"

    async def extract_metadata(self, first_pages_text: str) -> ExtractedMetadata | None:
        self.calls.append(("extract_metadata",))
        if self.metadata_error:
            raise self.metadata_error
        return self.metadata_result


class FakeS2Client:
    """Stands in for S2Client.lookup: identifier -> S2 item dict, or an exception to raise."""

    def __init__(self):
        self.items: dict[str, dict | Exception] = {}
        self.lookups: list[str] = []

    async def lookup(self, identifier: str) -> dict:
        self.lookups.append(identifier)
        from app.services.s2_client import S2NotFound

        item = self.items.get(identifier, S2NotFound(identifier))
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def engine():
    # StaticPool: every connection shares the same in-memory DB (otherwise each gets an empty one).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


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
def fake_s2():
    return FakeS2Client()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def paper_service(fake_s2, fake_pdf, fake_llm, tmp_path):
    return deps.PaperService(fake_s2, fake_pdf, fake_llm, tmp_path / "uploads")


@pytest.fixture
def client(engine, fake_search, fake_pdf, fake_llm, fake_s2, tmp_path):
    app = create_app(engine=engine)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[deps.get_search_service] = lambda: fake_search
    app.dependency_overrides[deps.get_pdf_service] = lambda: fake_pdf
    app.dependency_overrides[deps.get_llm_service] = lambda: fake_llm
    # Fake S2 too, so no API test can reach the real Semantic Scholar.
    app.dependency_overrides[deps.get_paper_service] = lambda: deps.PaperService(
        fake_s2, fake_pdf, fake_llm, tmp_path / "uploads"
    )
    with TestClient(app) as c:
        yield c
