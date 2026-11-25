"""SQLAlchemy ORM models (PostgreSQL).

Design rules enforced by this schema:
* Every document belongs to an owner; every query is scoped by owner.
* Every extracted financial value keeps its raw label, raw value string,
  original unit and a link to a `source_references` row (file + exact location).
* `validation_status` starts as `unvalidated`; automated checks can move it to
  `validated` / `failed_validation` / `needs_review`, but only a human action
  can set `verified` or `rejected`.
* Detected document metadata is stored per field with status
  (`detected` | `not_detected` | `user_corrected`), method and evidence.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


UUIDPK = lambda: mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)  # noqa: E731
CREATED = lambda: mapped_column(DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False)  # noqa: E731


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = UUIDPK()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = CREATED()
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Organisation(Base):
    """An organisation detected in (or assigned by a user to) uploaded documents.

    There is no predefined list: rows are created only from detection results
    or explicit user corrections.
    """

    __tablename__ = "organisations"
    __table_args__ = (UniqueConstraint("owner_id", "normalized_name"),)
    id: Mapped[uuid.UUID] = UUIDPK()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(20))  # detected | user
    created_at: Mapped[dt.datetime] = CREATED()


collection_documents = Table(
    "collection_documents",
    Base.metadata,
    Column("collection_id", UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)
    id: Mapped[uuid.UUID] = UUIDPK()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = CREATED()
    documents: Mapped[list["Document"]] = relationship(secondary=collection_documents, back_populates="collections")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_owner_sha", "owner_id", "sha256", unique=True),)
    id: Mapped[uuid.UUID] = UUIDPK()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    file_format: Mapped[str] = mapped_column(String(10))  # pdf | docx | xlsx | xls | csv
    mime_type: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|processing|processed|failed
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)

    # Structure facts (only set when measured)
    page_count: Mapped[int | None] = mapped_column(Integer)  # PDF pages
    sheet_names: Mapped[list | None] = mapped_column(JSONB)  # Excel sheets
    row_count: Mapped[int | None] = mapped_column(Integer)  # CSV rows
    element_count: Mapped[int] = mapped_column(Integer, default=0)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    metric_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_pages: Mapped[list | None] = mapped_column(JSONB)

    # Detected / corrected metadata. Each field: {value, status, method, confidence, evidence}
    doc_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Structure found by the parser: sheets, tables, merged ranges, sheet links, CSV column profile, duplicates …
    structure: Mapped[dict | None] = mapped_column(JSONB)
    # Denormalised effective values (NULL == not detected) for filtering & listing
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organisations.id", ondelete="SET NULL"))
    organisation_name: Mapped[str | None] = mapped_column(String(300))
    reporting_period: Mapped[str | None] = mapped_column(String(120))
    fiscal_year: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str | None] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(30))

    uploaded_at: Mapped[dt.datetime] = CREATED()
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    collections: Mapped[list[Collection]] = relationship(secondary=collection_documents, back_populates="documents")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[uuid.UUID] = UUIDPK()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|succeeded|failed
    stage: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list] = mapped_column(JSONB, default=list)  # [{stage, seconds, info}]
    created_at: Mapped[dt.datetime] = CREATED()
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    document: Mapped[Document] = relationship(back_populates="jobs")


class DocumentTable(Base):
    """A table found in a document, kept verbatim (cell text) with its location."""

    __tablename__ = "document_tables"
    id: Mapped[uuid.UUID] = UUIDPK()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    table_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSONB)
    header: Mapped[list] = mapped_column(JSONB, default=list)
    rows: Mapped[list] = mapped_column(JSONB, default=list)
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)
    id: Mapped[uuid.UUID] = UUIDPK()  # also the Qdrant point id
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    element_types: Mapped[list] = mapped_column(JSONB, default=list)
    location: Mapped[dict] = mapped_column(JSONB)  # see document_processing.elements.Location
    char_count: Mapped[int] = mapped_column(Integer)
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceReference(Base):
    """Exact place in an uploaded file that supports a value."""

    __tablename__ = "source_references"
    id: Mapped[uuid.UUID] = UUIDPK()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    location: Mapped[dict] = mapped_column(JSONB)
    snippet: Mapped[str] = mapped_column(Text)


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    id: Mapped[uuid.UUID] = UUIDPK()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    statement_type: Mapped[str] = mapped_column(String(40))  # balance_sheet|profit_and_loss|cash_flow|budget|other
    basis: Mapped[str | None] = mapped_column(String(20))  # consolidated|standalone|NULL(not detected)
    title: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSONB)
    currency: Mapped[str | None] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(30))
    periods: Mapped[list] = mapped_column(JSONB, default=list)


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (Index("ix_metrics_doc_key", "document_id", "metric_key"),)
    id: Mapped[uuid.UUID] = UUIDPK()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    statement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_statements.id", ondelete="SET NULL"))
    source_reference_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_references.id", ondelete="CASCADE"))
    metric_key: Mapped[str] = mapped_column(String(60))  # canonical key, e.g. revenue_from_operations
    metric_name: Mapped[str] = mapped_column(String(120))
    raw_label: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(30, 6))  # as printed (in `unit`)
    unit: Mapped[str | None] = mapped_column(String(30))  # crore | million | thousand | ... | NULL
    unit_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(40, 6))  # value * multiplier, NULL if unit unknown
    currency: Mapped[str | None] = mapped_column(String(10))
    period_label: Mapped[str | None] = mapped_column(String(120))  # header text as printed
    period_end: Mapped[dt.date | None] = mapped_column(Date)
    statement_type: Mapped[str | None] = mapped_column(String(40))
    basis: Mapped[str | None] = mapped_column(String(20))
    # reported = label matched a canonical metric directly; inferred_mapping = mapped from context (e.g. a bare
    # "Borrowings" row assigned to current/non-current by its section). Calculated values never live in this table.
    value_origin: Mapped[str] = mapped_column(String(20), default="reported")
    fiscal_year: Mapped[int | None] = mapped_column(Integer, index=True)  # FY in which the period ends (deterministic)
    is_total: Mapped[bool] = mapped_column(Boolean, default=False)  # printed total/subtotal row
    extraction_method: Mapped[str] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float)
    validation_status: Mapped[str] = mapped_column(String(24), default="unvalidated", index=True)
    validation_notes: Mapped[list] = mapped_column(JSONB, default=list)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = CREATED()
    source: Mapped[SourceReference] = relationship(lazy="joined")


class FinancialCalculation(Base):
    __tablename__ = "financial_calculations"
    id: Mapped[uuid.UUID] = UUIDPK()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    calc_key: Mapped[str] = mapped_column(String(60))
    formula: Mapped[str] = mapped_column(Text)
    period_label: Mapped[str | None] = mapped_column(String(120))
    inputs: Mapped[list] = mapped_column(JSONB)  # [{metric_id, metric_key, value, period_label, source}]
    result: Mapped[Decimal | None] = mapped_column(Numeric(30, 8))
    result_unit: Mapped[str] = mapped_column(String(20))  # percent | ratio | times
    status: Mapped[str] = mapped_column(String(30))  # ok | insufficient_data | zero_denominator | invalid_input
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[dt.datetime] = CREATED()


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[uuid.UUID] = UUIDPK()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = CREATED()
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = UUIDPK()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(30))  # answered | insufficient_evidence | error
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    verification: Mapped[dict] = mapped_column(JSONB, default=dict)
    calculations: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = CREATED()
    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ModelConfiguration(Base):
    """Model endpoints the admin can switch between. API keys are NOT stored here
    (they come from environment variables named in `api_key_env`)."""

    __tablename__ = "model_configurations"
    id: Mapped[uuid.UUID] = UUIDPK()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # llm
    provider: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str] = mapped_column(String(300))
    model_name: Mapped[str] = mapped_column(String(200))
    api_key_env: Mapped[str | None] = mapped_column(String(80))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = CREATED()


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[uuid.UUID] = UUIDPK()
    kind: Mapped[str] = mapped_column(String(40))  # extraction | rag | finetune
    status: Mapped[str] = mapped_column(String(20))  # running | completed | failed
    method: Mapped[str] = mapped_column(Text)
    dataset: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    details: Mapped[list] = mapped_column(JSONB, default=list)
    model_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[dt.datetime] = CREATED()
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Dashboard(Base):
    """A saved dashboard: filters and chart choices only. Chart data is recomputed from the facts on every load, so a
    dashboard can never show values that were deleted, rejected or corrected after it was saved."""
    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)
    id: Mapped[uuid.UUID] = UUIDPK()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    layout: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = CREATED()
    updated_at: Mapped[dt.datetime] = CREATED()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = UUIDPK()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = CREATED()
