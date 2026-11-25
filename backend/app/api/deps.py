from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import PERMISSIONS, decode_access_token
from app.database.session import get_db
from app.models import AuditLog, User

COOKIE_NAME = "finrag_token"
limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().rate_limit_default])


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = _token(request)
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(tok)
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return user


def require(permission: str):
    def dep(user: User = Depends(current_user)) -> User:
        if permission not in PERMISSIONS.get(user.role, set()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role '{user.role}' does not allow '{permission}'")
        return user

    return dep


def audit(db: Session, request: Request | None, user: User | None, action: str, resource_type: str | None = None,
          resource_id: str | None = None, **details) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, resource_type=resource_type, resource_id=resource_id,
                    ip=(request.client.host if request and request.client else None), details=details))
    db.commit()
