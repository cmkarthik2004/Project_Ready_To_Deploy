"""Password hashing (Argon2id) and JWT access tokens."""
from __future__ import annotations

import datetime as dt
import uuid

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings

_hasher = PasswordHash((Argon2Hasher(),))

ROLES = ("admin", "analyst", "viewer")
# What each role may do. Checked by `require_permission` in api/deps.py.
PERMISSIONS: dict[str, set[str]] = {
    "admin": {"read", "upload", "delete", "verify", "admin", "evaluate"},
    "analyst": {"read", "upload", "delete", "verify", "evaluate"},
    "viewer": {"read"},
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(password, hashed)
    except Exception:
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(minutes=s.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})


def validate_password_strength(password: str) -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if password.lower() == password or password.upper() == password:
        return "Password must contain both upper- and lower-case letters."
    if not any(c.isdigit() for c in password):
        return "Password must contain a digit."
    return None
