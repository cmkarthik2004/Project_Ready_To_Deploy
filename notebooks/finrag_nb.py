"""Shared helpers for the FinRAG learning notebooks.

* Makes the production backend importable (`import app...`) — notebooks use the
  REAL implementation, they never copy it.
* Loads configuration through the application's own settings (which read `.env`),
  and exposes only NON-SECRET values for display.
* Locates the documents you experiment with. FinRAG ships no documents: put your
  own financial files (or the public test documents listed in
  docs/evaluation/README.md) in a folder and point FINRAG_NOTEBOOK_DOCS at it.

Never print `get_settings()` directly in a notebook: it contains the database
password and the JWT secret.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

# quieter notebooks: no download progress bars / HF token hints in saved outputs
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
warnings.filterwarnings("ignore", message="IProgress not found")

NOTEBOOK_DIR = Path(__file__).resolve().parent
PROJECT_DIR = NOTEBOOK_DIR.parent
BACKEND_DIR = PROJECT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DOCS_DIR = Path(os.environ.get("FINRAG_NOTEBOOK_DOCS", os.environ.get("FINRAG_TEST_DOCS", "/opt/finrag_testdocs")))
SECRET_FIELDS = {"jwt_secret", "database_url", "llm_api_key", "qdrant_api_key"}


def doc_path(name: str) -> Path:
    """Path of a document in DOCS_DIR; raises a clear error if you have not provided it."""
    p = DOCS_DIR / name
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Put your own financial document there, or download the public test documents "
            f"listed in docs/evaluation/README.md, or set FINRAG_NOTEBOOK_DOCS to another folder.")
    return p


def safe_settings(*names: str) -> dict:
    """Selected application settings with secrets removed (safe to display)."""
    from app.core.config import get_settings

    s = get_settings().model_dump()
    keys = names or [k for k in s if k not in SECRET_FIELDS]
    return {k: (str(s[k]) if isinstance(s[k], Path) else s[k]) for k in keys if k not in SECRET_FIELDS}


def db_session():
    """A SQLAlchemy session on the application database (configured in .env)."""
    from app.database.session import SessionLocal

    return SessionLocal()


def notebook_user(db, email: str | None = None):
    """The FinRAG user whose uploaded documents the notebook reads.

    Set FINRAG_NOTEBOOK_USER to your login email; otherwise the account with the most
    processed documents is used. Documents are always read through this owner, like the API does.
    """
    from sqlalchemy import func

    from app.models import Document, User

    email = email or os.environ.get("FINRAG_NOTEBOOK_USER")
    if email:
        return db.query(User).filter(func.lower(User.email) == email.lower()).one()
    row = (db.query(User, func.count(Document.id)).join(Document, Document.owner_id == User.id)
           .filter(Document.status == "processed").group_by(User.id).order_by(func.count(Document.id).desc()).first())
    if row is None:
        raise LookupError("No user has processed documents yet. Upload documents in the FinRAG app first.")
    return row[0]


def shorten(text: str, n: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"
