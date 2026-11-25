from __future__ import annotations

from pydantic import BaseModel, Field


class MetadataPatch(BaseModel):
    organisation: str | None = Field(default=None, max_length=300)
    reporting_period: str | None = Field(default=None, max_length=120)
    fiscal_year: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=60)
    currency: str | None = Field(default=None, max_length=10)
    unit: str | None = Field(default=None, max_length=30)
    clear: list[str] = []
