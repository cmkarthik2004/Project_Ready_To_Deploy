from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class DocSelection(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    collection_id: uuid.UUID | None = None
    metric_keys: list[str] | None = None
    include_line_items: bool = False


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
