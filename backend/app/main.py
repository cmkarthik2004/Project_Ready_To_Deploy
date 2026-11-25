from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import analytics, auth, chat, dashboard, documents, evaluation, reports, system
from app.api.deps import limiter
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
log = logging.getLogger("finrag.api")
settings = get_settings()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.run_worker_in_api:
        from app.worker import start_thread

        start_thread()
        log.info("embedded worker thread started")
    yield


app = FastAPI(title="FinRAG API", version="1.0.0", lifespan=lifespan,
              description="Universal financial document intelligence: upload PDF/DOCX/XLSX/XLS/CSV, ask grounded questions, analyse metrics.",
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    ref = uuid.uuid4().hex[:12]
    log.exception("unhandled error ref=%s path=%s", ref, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Internal server error (reference {ref}). Details are in the server log."})


for r in (auth.router, documents.router, analytics.router, dashboard.router, chat.router, reports.router, evaluation.router, system.router):
    app.include_router(r, prefix="/api")
