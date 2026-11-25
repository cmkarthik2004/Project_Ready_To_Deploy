from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class ModelConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=60)
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,79}$")
    params: dict = Field(default_factory=dict)


class RoleIn(BaseModel):
    role: str
    is_active: bool = True
