from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SessionIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    collection_id: uuid.UUID | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    collection_id: uuid.UUID | None = None
