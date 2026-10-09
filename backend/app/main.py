import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from .config import settings
from .db import init_db, make_engine
from .routers import assistant, papers, search

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the app. Tests pass an in-memory engine so the real data/app.db is never touched."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "engine", None) is None:
            app.state.engine = make_engine()
        init_db(app.state.engine)
        log.info(
            "Gemini API key: %s | Semantic Scholar API key: %s",
            "set" if settings.gemini_api_key else "NOT SET (summaries and Q&A disabled)",
            "set" if settings.s2_api_key else "not set (searches will mostly fall back to arXiv)",
        )
        yield

    app = FastAPI(title="AI Research Assistant", lifespan=lifespan)
    app.state.engine = engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(search.router)
    app.include_router(papers.router)
    app.include_router(assistant.router)
    return app


app = create_app()
