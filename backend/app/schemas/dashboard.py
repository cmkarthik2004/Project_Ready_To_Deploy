"""Request bodies for the dashboard API."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class DashboardFilters(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    organisations: list[str] = Field(default_factory=list, max_length=100)
    fiscal_years: list[int] = Field(default_factory=list, max_length=50)
    basis: Literal["consolidated", "standalone", "not_stated"] | None = None

    def as_dict(self) -> dict:
        return {"document_ids": [str(x) for x in self.document_ids], "organisations": self.organisations,
                "fiscal_years": self.fiscal_years, "basis": self.basis}


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    filters: DashboardFilters = Field(default_factory=DashboardFilters)
    layout: dict = Field(default_factory=dict)  # e.g. {"hidden_charts": [...]} — presentation only, never data


class DashboardAsk(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    filters: DashboardFilters = Field(default_factory=DashboardFilters)
    chart_id: str | None = Field(default=None, max_length=200)
    selected_x: str | None = Field(default=None, max_length=40)
    session_id: uuid.UUID | None = None
