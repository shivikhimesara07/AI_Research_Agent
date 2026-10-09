# AI Research Assistant: architecture and conventions

Web app to search papers, save them to a local library, upload PDFs, and summarize / ask
questions about a paper's **full text** with an LLM.

Stack: React 19 + Vite + Tailwind v4 (JSX) · FastAPI · SQLite via SQLModel · Semantic Scholar
(arXiv fallback) · PyMuPDF · Gemini via `google-genai`.

## Layout
```
backend/app/
  main.py          create_app(engine=None) factory; lifespan creates tables on app.state.engine
  config.py        Settings from repo-root .env
  db.py            make_engine, init_db, get_session (uses request.app.state.engine)
  models.py        SQLModel tables (Paper, Message) + Pydantic request/response schemas
  deps.py          service providers — the ONLY place services are constructed
  routers/         search.py, papers.py, assistant.py  (thin: parse → call service → map errors)
  services/
    s2_client.py       Semantic Scholar HTTP: x-api-key, 1 req/s throttle, retry/backoff
    search_service.py  SearchService (S2 → arXiv fallback), ArxivClient, s2_to_meta
    pdf_service.py     text extraction, identifier regexes, layout heuristics,
                       strip_references, download_pdf (fails soft)
    llm_service.py     LLMService protocol + GeminiLLMService
    paper_service.py   orchestration: save, upload pipeline, ensure_full_text, summarize, ask
backend/tests/     conftest.py (fakes + in-memory DB), test_*.py
frontend/src/      api.js (all fetch calls), App.jsx, components/
```

## Conventions (keep these true)
- **Routers stay thin; logic lives in services.** Services never import FastAPI and receive
  their dependencies via constructors. Add new services to `deps.py` so tests can override them.
- Route code depends on `LLMService` (the protocol), never on Gemini directly.
- **`POST /api/papers` writes metadata only — it never downloads.** Full text is fetched lazily by
  `PaperService.ensure_full_text`, called only from summary/ask, so Save never blocks.
  A failed fetch sets `full_text_status="failed"`; asks don't retry it, `summary?refresh=true` does.
- **Search fallback:** arXiv only on 429 / 5xx / timeout / network error (after retries) or
  401/403 (logged WARNING, `fallback_reason="s2_auth_error"`). S2 400 → HTTP 400, no fallback.
  **Empty S2 results are returned as-is — never fall back on empty.** Responses always carry
  `source` and `fallback_reason`.
- **Upload metadata order** (stop at first result with title + ≥1 author):
  (a) arXiv id / DOI regex → S2 lookup, accepted only if the S2 title appears in the first ~3k
  chars of page 1 (guards against cited ids); (b) Gemini JSON with `response_schema`, validated
  with Pydantic; (c) PyMuPDF font-size heuristics; else filename.
- **LLM budget:** `strip_references` drops the bibliography (keeps appendices after it) and caps at
  120k chars. Ask sends only the last 4 Q/A exchanges (`HISTORY_EXCHANGES`).
- **Summary cache:** `summary_basis` is stored; an `abstract`-based summary is regenerated once
  full text becomes available.
- `download_pdf` accepts `application/pdf` OR `%PDF-` magic bytes, caps at 25 MB, sets a
  User-Agent and timeout, and returns `None` instead of raising.
- Never commit `.env` or `backend/data/` (SQLite DB + uploaded/downloaded PDFs).

## Env vars (repo-root `.env`, see `.env.example`)
`GEMINI_API_KEY` (needed for summary/Q&A), `SEMANTIC_SCHOLAR_API_KEY` (optional; without it S2 is
heavily rate-limited and search often falls back to arXiv), `GEMINI_MODEL` (default
`gemini-2.5-flash`). Optional: `DATA_DIR`, `DATABASE_URL`, `S2_BASE_URL`, `ARXIV_BASE_URL`.

## Commands
```bash
# backend (port 8001 — 8000 is commonly taken on the dev machine)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd backend && .venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8001
cd backend && .venv/bin/pytest

# frontend (port 5174; Vite proxies /api → :8001, override with BACKEND_URL)
cd frontend && npm install && npm run dev
```

## Testing
`tests/conftest.py` builds the app with `create_app(engine=<in-memory StaticPool engine>)` and
overrides `get_session` and every `deps.py` provider with `FakeSearchService`, `FakePdfService`,
`FakeLLMService`. Tests must never hit the network or create `backend/data/app.db`.
