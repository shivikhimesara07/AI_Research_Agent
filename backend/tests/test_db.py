"""The in-place migration that adds Paper.file_hash to databases created before it existed."""
import hashlib

from sqlalchemy import inspect, text

from app.db import init_db, make_engine

PDF = b"%PDF-1.7 previously stored paper"


def test_migration_adds_file_hash_and_backfills_from_disk(tmp_path):
    stored = tmp_path / "old.pdf"
    stored.write_bytes(PDF)
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # an HW1-era table without the file_hash column
        conn.execute(text("CREATE TABLE paper (id INTEGER PRIMARY KEY, source VARCHAR, title VARCHAR, "
                          "authors JSON, pdf_path VARCHAR)"))
        conn.execute(text("INSERT INTO paper VALUES (1, 'upload', 'Old', '[]', :p), "
                          "(2, 'upload', 'Missing file', '[]', '/nowhere.pdf'), "
                          "(3, 'semantic_scholar', 'No pdf', '[]', NULL)"), {"p": str(stored)})

    init_db(engine)

    assert "file_hash" in {c["name"] for c in inspect(engine).get_columns("paper")}
    with engine.connect() as conn:
        hashes = dict(conn.execute(text("SELECT id, file_hash FROM paper")).all())
    assert hashes == {1: hashlib.sha256(PDF).hexdigest(), 2: None, 3: None}
    engine.dispose()


def test_migration_is_a_no_op_on_current_schema(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'new.db'}")
    init_db(engine)
    init_db(engine)  # second run must not try to add the column again
    assert "file_hash" in {c["name"] for c in inspect(engine).get_columns("paper")}
    engine.dispose()


def test_foreign_keys_are_enforced(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fk.db'}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    engine.dispose()
