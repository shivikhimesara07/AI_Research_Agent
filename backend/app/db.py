"""Database engine and session dependency."""
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import event
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


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
