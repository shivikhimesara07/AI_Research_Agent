# AI Research Assistant

A web app for finding, organizing, and understanding research papers. Search Semantic Scholar,
save papers to a local library, upload your own PDFs, and use an LLM (Google Gemini) to summarize a
paper or answer questions about it — based on the paper's full text, not just its abstract.

## Features

| Feature | How it works |
|---|---|
| **Search papers** | Keyword/topic search via the Semantic Scholar API, falling back to the arXiv API if S2 is rate-limited or down. Results show title, authors, year, abstract, and links to the paper page / PDF. The UI shows which source answered. |
| **Local library** | Save any result to a SQLite database. The library persists across page refreshes and server restarts, and can be filtered and pruned. |
| **PDF upload** | Upload a PDF; the app extracts its text and metadata (title, authors, year, abstract) and renders it like a search result. Metadata comes from (1) an arXiv ID/DOI found in the PDF and looked up on Semantic Scholar, (2) Gemini structured extraction, or (3) font-size/layout heuristics, in that order. |
| **Summaries** | Gemini writes a structured summary (problem, approach, experiments, contributions, limitations) from the full text. For saved search results, the open-access PDF is downloaded on first use. If no full text can be obtained, the summary is based on the abstract and the UI says so. |
| **Q&A** | Ask natural-language questions about a paper ("What datasets are used?", "What are the limitations?"). Chat history is saved per paper. |

## Architecture

```
frontend/  React + Vite + Tailwind  ──/api (Vite proxy)──▶  backend/  FastAPI
                                                              ├── routers/   HTTP layer only
                                                              ├── services/  search, PDF, LLM, orchestration
                                                              └── SQLite (SQLModel)  backend/data/app.db
```

- `backend/app/services/search_service.py` + `s2_client.py` — Semantic Scholar (API key, throttling, retries) with arXiv fallback
- `backend/app/services/pdf_service.py` — PyMuPDF text extraction, metadata heuristics, reference stripping, safe PDF download
- `backend/app/services/llm_service.py` — Gemini summaries, Q&A, and JSON metadata extraction
- `backend/app/services/paper_service.py` — ties it together (upload pipeline, lazy full-text fetching, caching)
- `backend/app/deps.py` — builds the services; tests swap them for fakes

See [ARCHITECTURE.md](ARCHITECTURE.md) for design rules and conventions.

### API

| Method | Path | Description |
|---|---|---|
| GET | `/api/search?q=&limit=` | Search papers |
| GET / POST | `/api/papers` | List library / save a paper |
| POST | `/api/papers/upload` | Upload a PDF (multipart `file`) |
| GET / DELETE | `/api/papers/{id}` | Get / remove a paper |
| POST | `/api/papers/{id}/summary?refresh=` | Generate (or return cached) summary |
| GET | `/api/papers/{id}/messages` | Q&A history |
| POST | `/api/papers/{id}/ask` | Ask a question `{"question": "..."}` |

Interactive API docs: http://localhost:8001/docs

## Setup

Requirements: Python 3.11+ and Node.js 20+.

### 1. API keys

```bash
cp .env.example .env
```

Edit `.env`:

- `GEMINI_API_KEY` — required for summaries and Q&A ([get one](https://aistudio.google.com/apikey))
- `SEMANTIC_SCHOLAR_API_KEY` — optional but recommended; without it searches are heavily rate-limited
  and often fall back to arXiv ([request one](https://www.semanticscholar.org/product/api))
- `GEMINI_MODEL` — optional, defaults to `gemini-2.5-flash`

`.env` is gitignored — never commit it.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8001
```

### 3. Frontend (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5174.

The database and PDFs are stored in `backend/data/` (created automatically).

### Known limitations

- **Upload size is checked only on the server.** A file over 25 MB is fully uploaded before it is
  rejected with "PDF is larger than 25 MB"; on a slow connection that wait can be noticeable.
- **The summary loading message always mentions downloading the PDF**, even for papers that have
  no PDF available.
- **Abstract-only summaries can add small inferences.** When no full text is available the model is
  told so, but it may still expand acronyms that the abstract leaves unexplained.
- **Duplicate detection for uploads is byte-exact.** Re-uploading the same file is detected; a
  different copy of the same paper (e.g. another arXiv version) is only matched when an arXiv ID
  or DOI lookup resolves it to a paper already in the library.
- In the development server, React StrictMode fetches a paper's details twice when it is opened.
  Production builds do not.

### Tests

```bash
cd backend && .venv/bin/pytest
```

Tests use fake search/PDF/LLM services and an in-memory database, so they need no API keys or network.
