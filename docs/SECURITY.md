# FinRAG Security

This document lists the controls that are **implemented and tested** and the operational steps a
deployer must take. Items marked *operator* are configuration responsibilities.

## Authentication and sessions
* Passwords hashed with **Argon2id** (`pwdlib`). Policy: ≥10 characters, upper + lower case, digit
  (`core/security.py`; tested).
* Sessions are **JWT (HS256)** access tokens with expiry (`exp`), issued-at and a unique `jti`,
  delivered as an **httpOnly, SameSite=Strict** cookie (`Secure` when `COOKIE_SECURE=true`). A Bearer
  header is also accepted for API clients.
* The app refuses to start in `production` with the development JWT secret or a secret shorter than 32
  characters.
* The first registered account becomes `admin`; set `ALLOW_REGISTRATION=false` afterwards if sign-up
  should be closed (*operator*).

## Authorisation (RBAC)
| Role | Permissions |
|---|---|
| admin | read, upload, delete, verify, evaluate, admin (users, model endpoints, audit log) |
| analyst | read, upload, delete, verify, evaluate |
| viewer | read |

Every route declares its permission (`api/deps.py::require`). Roles are read from the database on
every request, so a role change applies immediately. **Tenant isolation**: every query filters by the
document owner, and every Qdrant search filters on `owner_id` and the resolved document IDs; results
are re-checked against SQL (tested: another user gets 404 and an empty library). Ownership applies to
**every role, including admin**: the admin permission covers user management, model endpoints and the audit
log, not other users' documents, metric reviews, chat sessions or evaluation runs. The live audit
(`docs/END_TO_END_DATA_FLOW_AUDIT.md`) probes 10 direct routes plus list/analytics/chat/evaluation/vector-search
paths as a second user; all return 404 or nothing.

## Input and file validation (`document_processing/validation.py`)
* Extension allow-list: `.pdf .docx .xlsx .xls .csv`; size limit (`MAX_UPLOAD_MB`, default 50);
  max files per request.
* **Content signature must match the extension** (PDF header, OOXML ZIP with required part, OLE2 for
  XLS, text without NUL bytes for CSV).
* PDF: must open, not encrypted, page limit; `/Launch` actions rejected; JavaScript and embedded files
  produce warnings (FinRAG never executes PDF content, it only extracts text).
* DOCX/XLSX: zip-bomb guards (total uncompressed size, compression ratio), path-traversal member names
  rejected, VBA macro projects rejected, embedded objects / external links reported and not opened.
* Filenames are sanitised; files are stored under random UUID names with mode 0640, outside any web
  root. Downloads are served with `Content-Security-Policy: sandbox` and `nosniff`.
* Duplicate uploads (same SHA-256 for the same user) are rejected.
* All request bodies are validated by Pydantic models with length limits.

## Injection defences
* **SQL**: SQLAlchemy ORM / bound parameters everywhere (the full-text query uses bound parameters).
* **Prompt injection**: document text is placed inside `<source>` tags declared as data; chat-template
  control tokens are stripped; instruction-like text is flagged at ingestion and labelled in the
  prompt; answers are verified post-hoc (citations must exist; numbers must appear in cited sources)
  and uncited answers are withheld.

## Transport, headers, CORS, rate limiting
* Security headers from API and web server: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` (API), `Permissions-Policy` (web).
* CORS restricted to `CORS_ORIGINS`; the browser normally talks only to the Next.js origin, which
  proxies `/api`.
* Rate limits (slowapi): default 120/min, auth 10/min, chat 20/min per client IP (configurable).
* Terminate TLS in front of the stack (nginx/Caddy/cloud LB) and set `COOKIE_SECURE=true` (*operator*).
* In docker compose the API binds to `127.0.0.1` only; only the web container is exposed.

## Error handling and logging
* Unhandled exceptions return a generic message with a reference ID; details go to the structured
  (JSON) server log only.
* **Audit log** (`audit_logs`): registrations, logins and failed logins, uploads and rejections,
  deletions, metadata corrections, metric verification/rejection, reprocessing, chat questions,
  report generation, model endpoint changes, role changes. Admins can view it in Settings.

## Secrets
* All secrets come from environment variables / `.env` (git-ignored; `.env.example` contains no
  values). LLM API keys are referenced by environment-variable name in `model_configurations`; the key
  itself is never stored in the database or returned by the API.

## Secrets audit and notebooks
* Audit on 2026-11-24: `.env` has never been committed; no secret-like literals exist in any revision of the repository.
  No credential rotation was required.
* Notebooks never read or print secrets directly: they use `notebooks/finrag_nb.py`, whose `safe_settings()` drops
  `jwt_secret`, `database_url`, `llm_api_key` and `qdrant_api_key`; the NVIDIA key is only tested for presence.
* Before committing notebooks, every cell's source and output is scanned for the actual secret values in `.env` and for
  database connection strings (see `docs/DEVELOPMENT_GUIDE.md`). The scan of all 14 notebooks found none.

## Backups (*operator*)
`deployment/backup.sh` dumps PostgreSQL (`pg_dump -Fc`), snapshots the Qdrant collection and copies
uploaded files, writing SHA-256 checksums; `deployment/restore.sh` verifies checksums and restores.
Schedule it (cron/systemd timer) and store copies off-host, encrypted.

## Dependency security
* Python and npm dependencies are pinned to exact versions (`requirements*.txt`, `package-lock.json`).
* Checks run during development: `npm audit --omit=dev` → 0 vulnerabilities; `pip-audit` results are
  recorded in `docs/PROGRESS.md`. Re-run both before each release (*operator*).
