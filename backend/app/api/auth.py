from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import COOKIE_NAME, audit, current_user, limiter
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, validate_password_strength, verify_password
from app.database.session import get_db
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role,
            "created_at": u.created_at.isoformat(), "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE_NAME, token, httponly=True, secure=s.cookie_secure, samesite="strict",
                    max_age=s.access_token_minutes * 60, path="/")


@router.post("/register", status_code=201)
@limiter.limit(get_settings().rate_limit_auth)
def register(request: Request, body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    n_users = db.query(func.count(User.id)).scalar()
    if not s.allow_registration and n_users > 0:
        raise HTTPException(403, "Self-registration is disabled. Ask an administrator for an account.")
    if err := validate_password_strength(body.password):
        raise HTTPException(422, err)
    email = body.email.lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    role = "admin" if n_users == 0 else s.default_role  # first account bootstraps the installation
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=role)
    db.add(u)
    db.commit()
    audit(db, request, u, "user.register", "user", str(u.id), role=role)
    _set_cookie(response, create_access_token(u.id, u.role))
    return user_out(u)


@router.post("/login")
@limiter.limit(get_settings().rate_limit_auth)
def login(request: Request, body: LoginIn, response: Response, db: Session = Depends(get_db)):
    u = db.query(User).filter(func.lower(User.email) == body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash) or not u.is_active:
        audit(db, request, None, "user.login_failed", "user", None, email=body.email.lower())
        raise HTTPException(401, "Incorrect email or password.")
    u.last_login_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    audit(db, request, u, "user.login", "user", str(u.id))
    token = create_access_token(u.id, u.role)
    _set_cookie(response, token)
    return {"user": user_out(u), "access_token": token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
