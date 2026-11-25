from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ReportIn(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    include_ai_summary: bool = False
