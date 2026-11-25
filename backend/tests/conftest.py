"""Test configuration.

* Uses the TEST_DATABASE_URL database and a separate Qdrant collection, so tests
  never touch application data.
* Unit tests use small SYNTHETIC inputs (clearly marked) only to exercise parser
  and calculation code paths; they are not financial data and are never stored
  outside the isolated test database.
* Tests that need genuine documents look in FINRAG_TEST_DOCS (default
  /opt/finrag_testdocs) and are skipped if those files are not present.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
_env = dotenv_values(ROOT / ".env")
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL") or "postgresql+psycopg://finrag:finrag@localhost:5432/finrag_test"
os.environ["QDRANT_COLLECTION"] = "finrag_test_chunks"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="finrag_test_uploads_")
os.environ["RATE_LIMIT_DEFAULT"] = "10000/minute"
os.environ["RATE_LIMIT_AUTH"] = "10000/minute"
os.environ["RATE_LIMIT_CHAT"] = "10000/minute"
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

TEST_DOCS = Path(os.environ.get("FINRAG_TEST_DOCS", "/opt/finrag_testdocs"))
# Genuine public annual report used for accuracy tests (expected values in test_parsers.py come
# from its consolidated statements, PDF pages 99-100). Override with FINRAG_TEST_PDF.
REAL_PDF = Path(os.environ.get("FINRAG_TEST_PDF", str(TEST_DOCS / "RIL-Integrated-Annual-Report-2024-25.pdf")))
DERIVED = TEST_DOCS / "derived"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the schema in the test DB through the real Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings
    from app.database.session import get_engine, reset_engine
    from sqlalchemy import text

    get_settings.cache_clear()
    reset_engine()
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(cfg, "head")
    from app.rag import vector_store

    s = get_settings()
    if vector_store.client().collection_exists(s.qdrant_collection):
        vector_store.client().delete_collection(s.qdrant_collection)
    yield
    if vector_store.client().collection_exists(s.qdrant_collection):
        vector_store.client().delete_collection(s.qdrant_collection)


@pytest.fixture()
def db():
    from app.database.session import SessionLocal

    s = SessionLocal()
    yield s
    s.close()


def need_real_pdf():
    if not REAL_PDF.exists():
        pytest.skip(f"genuine test PDF not present at {REAL_PDF}")
    return REAL_PDF


def need_derived(name: str) -> Path:
    p = DERIVED / name
    if not p.exists():
        pytest.skip(f"derived fixture {p} not present (run tests/fixtures/build_derived_fixtures.py)")
    return p
