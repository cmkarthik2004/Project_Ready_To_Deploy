"""Application configuration.

All settings come from environment variables (or a local `.env` file that is
never committed). Nothing secret has a usable default: the app refuses to start
in production mode with the development JWT secret.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    environment: str = Field("development", description="development | test | production")
    app_name: str = "FinRAG"

    # --- Security -----------------------------------------------------------
    jwt_secret: str = DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 8
    cookie_secure: bool = False  # set True behind HTTPS
    allow_registration: bool = True
    default_role: str = "analyst"  # role given to self-registered users (first user becomes admin)
    cors_origins: list[str] = ["http://localhost:3000"]
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"
    rate_limit_chat: str = "20/minute"

    # --- Storage --------------------------------------------------------------
    database_url: str = "postgresql+psycopg://finrag:finrag@localhost:5432/finrag"
    upload_dir: Path = PROJECT_DIR / "data" / "uploads"
    max_upload_mb: int = 50
    max_files_per_request: int = 20
    max_pdf_pages: int = 2000
    max_zip_uncompressed_mb: int = 300  # DOCX/XLSX are ZIP containers: zip-bomb guard
    max_sheet_cells: int = 2_000_000

    # --- Vector store ------------------------------------------------------------
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "finrag_chunks"

    # --- Models ------------------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "
    reranker_model: str | None = "cross-encoder/ms-marco-MiniLM-L6-v2"
    retrieval_top_k: int = 24
    context_top_n: int = 5  # passages sent to the LLM (CPU prompt processing is the bottleneck)
    context_chars_per_passage: int = 1100
    max_metric_facts: int = 10
    max_calc_facts: int = 6

    # OpenAI-compatible chat endpoint: local llama.cpp server, NVIDIA NIM, vLLM, ...
    llm_provider_name: str = "llama.cpp (local)"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "qwen3-4b-q4_k_m"
    llm_api_key: str | None = None
    llm_timeout_s: float = 600.0
    llm_max_tokens: int = 700
    llm_temperature: float = 0.1
    llm_disable_thinking: bool = True  # Qwen3: append /no_think

    # --- OCR -------------------------------------------------------------------
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_min_chars: int = 25  # a page with fewer extractable chars and an image is OCR'd
    pdf_table_engine: str = "pymupdf"  # pymupdf | docling (optional, heavy)

    # --- Worker ------------------------------------------------------------------
    worker_poll_seconds: float = 2.0
    run_worker_in_api: bool = False

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret == DEV_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of >= 32 chars in production")
        return self


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
