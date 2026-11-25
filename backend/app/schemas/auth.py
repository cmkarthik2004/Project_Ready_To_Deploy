from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)
