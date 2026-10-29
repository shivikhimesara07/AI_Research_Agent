"""End-to-end tests of the HTTP API with fake search/PDF/LLM services and an in-memory DB."""
import pytest

from app.routers import papers as papers_router
from app.services.llm_service import LLMError, LLMNotConfigured, LLMRateLimited
from app.services.search_service import SearchBadRequest, SearchUnavailable

PDF = b"%PDF-1.7 uploaded bytes"
META = {"source": "semantic_scholar", "external_id": "s2-1", "title": "Saved Paper",
        "authors": ["A. Author"], "year": 2020, "abstract": "An abstract.", "url": "https://s2/1"}


def save(client, **overrides):
    resp = client.post("/api/papers", json={**META, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload(client, data=PDF, name="paper.pdf"):
    return client.post("/api/papers/upload", files={"file": (name, data, "application/pdf")})


# ---------- search ----------


def test_search_marks_results_already_in_library(client):
    assert client.get("/api/search", params={"q": "x"}).json()["results"][0]["saved_id"] is None
    saved = save(client, external_id="fake-1")
    result = client.get("/api/search", params={"q": "x"}).json()["results"][0]
    assert result["saved_id"] == saved["id"]


def test_search_strips_query_and_passes_limit(client, fake_search):
    client.get("/api/search", params={"q": "  transformers  ", "limit": 5})
    assert fake_search.calls == [("transformers", 5)]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x", "limit": 0}, {"q": "x", "limit": 101}])
def test_search_validates_parameters(client, params):
    assert client.get("/api/search", params=params).status_code == 422


@pytest.mark.parametrize("error, status", [(SearchBadRequest("bad"), 400), (SearchUnavailable("both down"), 503)])
def test_search_errors_map_to_http_status(client, fake_search, error, status):
    fake_search.error = error
    resp = client.get("/api/search", params={"q": "x"})
    assert resp.status_code == status
    assert resp.json()["detail"]


# ---------- library ----------


def test_library_starts_empty(client):
    assert client.get("/api/papers").json() == []


def test_save_and_list_papers_newest_first(client):
    first = save(client, external_id="a", title="First")
    second = save(client, external_id="b", title="Second")
    listed = client.get("/api/papers").json()
    assert [p["id"] for p in listed] == [second["id"], first["id"]]
    assert first["full_text_status"] == "pending" and first["has_pdf"] is False


def test_saving_same_paper_twice_returns_existing(client):
    assert save(client)["id"] == save(client)["id"]
    assert len(client.get("/api/papers").json()) == 1


def test_save_rejects_invalid_body(client):
    assert client.post("/api/papers", json={"title": "no source"}).status_code == 422
    assert client.post("/api/papers", json={**META, "source": "wikipedia"}).status_code == 422


def test_get_paper(client):
    saved = save(client)
    assert client.get(f"/api/papers/{saved['id']}").json()["title"] == "Saved Paper"


@pytest.mark.parametrize("method, path", [
    ("get", "/api/papers/999"), ("delete", "/api/papers/999"), ("post", "/api/papers/999/summary"),
    ("get", "/api/papers/999/messages"),
])
def test_unknown_paper_returns_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_ask_unknown_paper_returns_404(client):
    assert client.post("/api/papers/999/ask", json={"question": "Q?"}).status_code == 404


def test_delete_removes_paper_and_its_messages(client):
    saved = save(client)
    client.post(f"/api/papers/{saved['id']}/ask", json={"question": "Q?"})
    assert client.delete(f"/api/papers/{saved['id']}").status_code == 204
    assert client.get(f"/api/papers/{saved['id']}").status_code == 404
    assert client.get("/api/papers").json() == []


# ---------- upload ----------


def test_upload_creates_paper(client):
    resp = upload(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "upload" and body["has_pdf"] and body["full_text_status"] == "ok"


def test_upload_rejects_non_pdf(client):
    resp = upload(client, b"just some notes", "notes.txt")
    assert resp.status_code == 400 and resp.json()["detail"] == "File is not a PDF"


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(papers_router, "MAX_UPLOAD_BYTES", 100)
    resp = upload(client, PDF + b"0" * 200)
    assert resp.status_code == 413 and "25 MB" in resp.json()["detail"]


def test_upload_unreadable_pdf_returns_400(client, fake_pdf):
    fake_pdf.extract_error = RuntimeError("corrupt xref")
    resp = upload(client)
    assert resp.status_code == 400 and "Could not read PDF" in resp.json()["detail"]


def test_upload_missing_file_returns_422(client):
    assert client.post("/api/papers/upload").status_code == 422


# ---------- summary ----------


def test_summary_uses_abstract_when_no_pdf_available(client):
    saved = save(client)
    resp = client.post(f"/api/papers/{saved['id']}/summary")
    assert resp.status_code == 200
    assert resp.json() == {"summary": "Summary of Saved Paper (abstract)", "summary_basis": "abstract"}


def test_summary_uses_full_text_for_uploads(client):
    paper = upload(client).json()
    assert client.post(f"/api/papers/{paper['id']}/summary").json()["summary_basis"] == "full_text"


def test_summary_is_cached_on_the_paper(client, fake_llm):
    paper = upload(client).json()
    client.post(f"/api/papers/{paper['id']}/summary")
    client.post(f"/api/papers/{paper['id']}/summary")
    assert sum(c[0] == "summarize" for c in fake_llm.calls) == 1
    assert client.get(f"/api/papers/{paper['id']}").json()["summary_basis"] == "full_text"


@pytest.mark.parametrize(
    "error, status, detail",
    [(LLMRateLimited("slow down"), 503, "rate limited"),
     (LLMNotConfigured("GEMINI_API_KEY is not set."), 503, "GEMINI_API_KEY is not set."),
     (LLMError("Gemini error 500: boom"), 502, "Gemini error 500: boom")],
)
def test_llm_errors_map_to_http_status(client, fake_llm, error, status, detail):
    saved = save(client)
    fake_llm.error = error
    for resp in (client.post(f"/api/papers/{saved['id']}/summary"),
                 client.post(f"/api/papers/{saved['id']}/ask", json={"question": "Q?"})):
        assert resp.status_code == status
        assert detail in resp.json()["detail"]


# ---------- Q&A ----------


def test_ask_returns_answer_and_stores_history(client):
    saved = save(client)
    resp = client.post(f"/api/papers/{saved['id']}/ask", json={"question": "  What datasets?  "})
    assert resp.json() == {"answer": "Answer to: What datasets?", "content_basis": "abstract"}
    messages = client.get(f"/api/papers/{saved['id']}/messages").json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "What datasets?"), ("assistant", "Answer to: What datasets?")]


@pytest.mark.parametrize("body, status", [({"question": "   "}, 400), ({"question": ""}, 400), ({}, 422)])
def test_ask_rejects_empty_question(client, body, status):
    saved = save(client)
    assert client.post(f"/api/papers/{saved['id']}/ask", json=body).status_code == status


def test_failed_question_is_not_saved(client, fake_llm):
    saved = save(client)
    fake_llm.error = LLMError("boom")
    client.post(f"/api/papers/{saved['id']}/ask", json={"question": "Q?"})
    assert client.get(f"/api/papers/{saved['id']}/messages").json() == []
