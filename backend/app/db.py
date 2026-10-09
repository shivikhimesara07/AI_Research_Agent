"""Database engine and session dependency."""
import hashlib
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import settings


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.db_url
    if url.startswith("sqlite:///"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    _enable_sqlite_foreign_keys(engine)
    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    # SQLite ignores ON DELETE CASCADE unless foreign keys are enabled per connection.
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db(engine: Engine) -> None:
    from . import models  # noqa: F401  (register tables on the metadata)

    SQLModel.metadata.create_all(engine)
    _migrate(engine)


def _migrate(engine: Engine) -> None:
    """Tiny in-place migrations for databases created before a column existed.

    create_all() only creates missing tables, never missing columns.
    """
    columns = {c["name"] for c in inspect(engine).get_columns("paper")}
    if "file_hash" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE paper ADD COLUMN file_hash VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_paper_file_hash ON paper (file_hash)"))
        # Backfill hashes from PDFs already on disk so re-uploads of them are deduplicated.
        rows = conn.execute(text("SELECT id, pdf_path FROM paper WHERE pdf_path IS NOT NULL")).all()
        for paper_id, pdf_path in rows:
            path = Path(pdf_path)
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                conn.execute(
                    text("UPDATE paper SET file_hash = :h WHERE id = :id"), {"h": digest, "id": paper_id}
                )


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
