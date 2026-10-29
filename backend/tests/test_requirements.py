"""Tests written from the HW1 requirements, not from the implementation.

Every expected value comes either from the requirement itself or from content we put into the
input (a generated PDF, a Semantic Scholar payload). Nothing is imported from app constants.
Only the LLM is faked; the PDF parser, metadata pipeline, routers and database are real.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import deps
from app.db import get_session, init_db, make_engine
from app.main import create_app
from app.services.s2_client import S2Client
from app.services.search_service import ArxivClient, SearchService
from sqlmodel import Session

from .conftest import no_network
from .pdf_factory import KnownPaper, make_pdf


def upload(client, data, name="paper.pdf"):
    return client.post("/api/papers/upload", files={"file": (name, data, "application/pdf")})


# ---------- R1: search returns title, authors, year, abstract, link ----------

S2_PAYLOAD = {
    "total": 1,
    "data": [{
        "paperId": "abc123",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": [{"authorId": "1", "name": "Patrick Lewis"}, {"authorId": "2", "name": "Ethan Perez"}],
        "year": 2020,
        "abstract": "Large pre-trained language models have been shown to store factual knowledge.",
        "url": "https://www.semanticscholar.org/paper/abc123",
        "openAccessPdf": {"url": "https://arxiv.org/pdf/2005.11401"},
        "externalIds": {"ArXiv": "2005.11401"},
    }],
}


def test_search_returns_title_authors_year_abstract_and_link(engine):
    # Real SearchService + real S2Client; only the HTTP response from Semantic Scholar is canned.
    s2 = S2Client("https://s2.test/graph/v1", None, min_interval=0,
                  transport=httpx.MockTransport(lambda req: httpx.Response(200, json=S2_PAYLOAD)))
    search = SearchService(s2, ArxivClient("https://arxiv.invalid", transport=no_network()))
    app = create_app(engine=engine)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[deps.get_search_service] = lambda: search
    with TestClient(app) as client:
        result = client.get("/api/search", params={"q": "retrieval augmented generation"}).json()["results"][0]

    source = S2_PAYLOAD["data"][0]
    assert result["title"] == source["title"]
    assert result["authors"] == ["Patrick Lewis", "Ethan Perez"]
    assert result["year"] == 2020
    assert result["abstract"] == source["abstract"]
    assert result["url"] == source["url"]                   # link to the paper
    assert result["pdf_url"] == "https://arxiv.org/pdf/2005.11401"


# ---------- R2: saved papers persist across restart ----------


def test_saved_paper_survives_backend_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'library.db'}"
    paper = {"source": "semantic_scholar", "external_id": "abc123", "title": "A Paper Worth Keeping",
             "authors": ["Patrick Lewis"], "year": 2020}

    first_engine = make_engine(db_url)
    with TestClient(create_app(engine=first_engine)) as client:
        saved_id = client.post("/api/papers", json=paper).json()["id"]
    first_engine.dispose()  # "shut down" the backend: no connection survives

    second_engine = make_engine(db_url)
    with TestClient(create_app(engine=second_engine)) as client:
        library = client.get("/api/papers").json()
    second_engine.dispose()

    assert [(p["id"], p["title"], p["authors"], p["year"]) for p in library] == [
        (saved_id, "A Paper Worth Keeping", ["Patrick Lewis"], 2020)]


# ---------- R3: upload extracts title, authors, year, abstract ----------
# (The main API version is test_api.py::test_upload_creates_paper.)


def test_upload_extracts_metadata_end_to_end(real_client, tmp_path):
    body = upload(real_client, KnownPaper.build(tmp_path / "known.pdf")).json()
    assert body["title"] == KnownPaper.TITLE
    assert body["authors"] == KnownPaper.AUTHORS
    assert body["year"] == KnownPaper.YEAR
    assert body["abstract"] == KnownPaper.ABSTRACT


@pytest.mark.xfail(strict=True, reason="Known bug found by this test: the layout heuristic silently drops "
                   "authors whose names contain lowercase particles (got ['Mei Chen'] only).")
def test_upload_extracts_authors_with_lowercase_name_particles(real_client, tmp_path):
    # Real author names often contain lowercase particles ("van", "de", "von").
    data = make_pdf(tmp_path / "p.pdf", [[
        ("Graph Neural Networks for Crop Yield", 18),
        "Anna van der Berg, Luis de la Cruz and Mei Chen",
        "Abstract", "We predict crop yields.", "1 Introduction",
    ]]).read_bytes()
    assert upload(real_client, data).json()["authors"] == ["Anna van der Berg", "Luis de la Cruz", "Mei Chen"]


def test_upload_corrupt_pdf_is_rejected_cleanly(real_client):
    resp = upload(real_client, b"%PDF-1.7\nthis is not a real PDF body")
    assert resp.status_code == 400
    assert real_client.get("/api/papers").json() == []


# ---------- R4: summaries are based on the paper's content, not its metadata ----------


def test_summary_is_generated_from_body_text(real_client, recording_llm, tmp_path):
    paper = upload(real_client, KnownPaper.build(tmp_path / "known.pdf")).json()
    resp = real_client.post(f"/api/papers/{paper['id']}/summary").json()

    sent = recording_llm.summaries[-1]["text"]
    # Facts that exist only on page 2 must reach the LLM; metadata alone could not contain them.
    assert KnownPaper.BODY_FACT_1 in sent and KnownPaper.BODY_FACT_2 in sent
    assert resp == {"summary": "summary #1", "summary_basis": "full_text"}


def test_summary_without_any_paper_content_says_so(real_client, recording_llm):
    # A search result with no PDF: the app can only use the abstract, and must report that.
    paper = real_client.post("/api/papers", json={
        "source": "semantic_scholar", "external_id": "no-pdf", "title": "Paywalled Paper",
        "abstract": "Only this abstract is available."}).json()
    resp = real_client.post(f"/api/papers/{paper['id']}/summary").json()
    assert resp["summary_basis"] == "abstract"
    assert "Only this abstract is available." in recording_llm.summaries[-1]["text"]


# ---------- R5: Q&A answers come from the paper's content ----------


def test_question_is_answered_from_body_text(real_client, recording_llm, tmp_path):
    paper = upload(real_client, KnownPaper.build(tmp_path / "known.pdf")).json()
    question = "How many protein chains are in the benchmark?"
    resp = real_client.post(f"/api/papers/{paper['id']}/ask", json={"question": question}).json()

    call = recording_llm.questions[-1]
    assert call["question"] == question
    assert KnownPaper.BODY_FACT_1 in call["text"]  # the answer can come from the paper body
    assert resp == {"answer": "answer #1", "content_basis": "full_text"}
    history = real_client.get(f"/api/papers/{paper['id']}/messages").json()
    assert [(m["role"], m["content"]) for m in history] == [("user", question), ("assistant", "answer #1")]
