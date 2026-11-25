# FinRAG — Financial Document Intelligence

FinRAG is a **universal financial document intelligence platform**. You upload your own financial
documents — **PDF, Word (.docx), Excel (.xlsx, .xls) or CSV** — and FinRAG:

1. validates the file (real format check, size and safety limits),
2. extracts text and tables while keeping **exact source locations** (PDF page and printed page,
   Word section/table/row, Excel sheet + cell, CSV row),
3. detects the organisation, reporting period, financial year, category, currency and units —
   or says **"Not detected" / "Uncertain"** instead of guessing,
4. extracts financial metrics deterministically and checks them with **accounting identities**,
5. indexes the content in **Qdrant** for retrieval-augmented question answering,
6. answers questions with **citations**, verifies every number in the answer against the cited
   sources, and refuses when evidence is insufficient,
7. computes ratios in **Python** (never by the LLM) and compares documents with explicit
   compatibility warnings,
8. builds an **automatic interactive financial dashboard** from whatever reliable figures the documents
   contain (KPIs, trends, composition, cash reconciliation, margins, growth heatmap), counting a figure
   repeated across reports only once, and
9. lets you **discuss the dashboard with the AI assistant**: answers cite the dashboard data, the
   documents and Python calculations; "what if" questions are computed in Python and labelled as
   hypothetical.

There is **no predefined company list, sample dataset or fixed financial year**. A fresh installation
shows empty states until you upload documents. Nothing in the UI is hard-coded or simulated.

> Built as a learning project for RAG, document intelligence and LLM fine-tuning; the
> documentation explains *why* each component exists. Start with `docs/ARCHITECTURE.md`.

## Contents
| Path | What it is |
|---|---|
| `backend/app/` | **Production code** (`.py`): FastAPI API, worker, parsers, OCR, RAG, LLM client, analytics, fine-tuning, evaluation |
| `backend/tests/` | Automated tests (82) |
| `backend/scripts/` | Live end-to-end audit, acceptance-file generator and acceptance run |
| `notebooks/` | **14 learning notebooks** that import the production code (see `docs/NOTEBOOK_GUIDE.md`) |
| `frontend/` | Next.js 16 app (13 pages, including the automatic Financial Dashboard) |
| `docs/` | Architecture, security, deployment, NVIDIA, evaluation, fine-tuning, demo, progress checklist |
| `deployment/` | Backup / restore scripts |
| `docker-compose.yml` | Full stack: PostgreSQL, Qdrant, llama.cpp LLM, API, worker, web (+ optional NVIDIA NIM profile) |
| `data/` | Runtime storage for uploads and training data (git-ignored; empty in the repository) |

## Learning with FinRAG
FinRAG is also a hands-on course. The production logic lives only in `backend/app/`; the notebooks import it
and experiment with real documents, with real, executed outputs:

| | | |
|---|---|---|
| 01 Python & financial data | 06 Financial extraction | 11 RAG evaluation |
| 02 PDF processing | 07 Financial validation | 12 Financial analytics |
| 03 DOCX processing | 08 Embeddings | 13 LoRA fine-tuning |
| 04 Excel & CSV | 09 Qdrant vector search | 14 NVIDIA GPU experiments |
| 05 OCR experiments | 10 RAG pipeline | |

Start with `docs/LEARNING_ROADMAP.md` (beginner → RAG → fine-tuning → NVIDIA) and `docs/NOTEBOOK_GUIDE.md`
(setup, order, which production module each notebook exercises).
```bash
cd backend && pip install -r requirements-notebooks.txt
python -m ipykernel install --user --name finrag --display-name "FinRAG (backend venv)"
cd ../notebooks && jupyter lab
```

## Dashboard
**Financial Dashboard** (automatic KPIs and charts, filters, drill-down to the printed value, CSV/Markdown export,
saved views, AI assistant) · Processing Overview · Upload Documents · Document Library · AI Financial Chat · Document Analysis ·
Financial Analytics · Compare Documents · Financial Ratios · AI Model & RAG Status · Evaluation ·
Reports · Settings. Every number on every page comes from a backend API backed by PostgreSQL/Qdrant.

## Technology (exact versions verified in development)
| Area | Stack |
|---|---|
| Frontend | Next.js 16.4.6, React 19.3.1, TypeScript 5.9.3, Tailwind CSS 4.3.5, Recharts 3.11.0 |
| Backend | Python 3.13, FastAPI 0.165.0, Pydantic 2.14.4, SQLAlchemy 2.1.9, Alembic 1.20.1, psycopg 3.3.9 |
| Documents | PyMuPDF 2.1 (+ Tesseract 5.3.4 OCR), python-docx 1.2.0, openpyxl 3.1.5, pandas 3.1.1, xlrd 2.0.2; Docling 2.152.0 optional (separate venv) |
| RAG | BAAI/bge-small-en-v1.5 (sentence-transformers 6.3.0), Qdrant 1.20.0 (client 1.20.0), cross-encoder/ms-marco-MiniLM-L6-v2, PostgreSQL full-text search |
| LLM | Qwen3-4B Q4_K_M GGUF on llama.cpp (CPU); any OpenAI-compatible endpoint (NVIDIA NIM, vLLM, TensorRT-LLM) |
| Fine-tuning | PyTorch 2.15 (CPU build used here), Transformers 5.24.0, PEFT 0.22.0, TRL 1.18.2, Qwen3-0.6B base |
| Database | PostgreSQL 16 |
| Security | Argon2id (pwdlib), JWT (PyJWT) httpOnly cookies, RBAC, slowapi rate limits, audit log |

## Quick start (Docker)
```bash
cp .env.example .env        # set JWT_SECRET, POSTGRES_PASSWORD, CORS_ORIGINS, COOKIE_SECURE
mkdir -p models && curl -L -o models/Qwen3-4B-Q4_K_M.gguf \
  https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf
docker compose up -d --build
```
Open http://localhost:3000 and register — the first account becomes the administrator.
Full instructions, bare-metal setup, TLS, backups and upgrades: **`docs/DEPLOYMENT.md`**.

## Local development
```bash
# services: PostgreSQL 16 and Qdrant 1.20 running locally (see docs/DEPLOYMENT.md)
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
cp ../.env.example ../.env && alembic upgrade head
# LLM: native llama.cpp server on :8080 (see docs/DEPLOYMENT.md), or point LLM_BASE_URL at NIM/vLLM
uvicorn app.main:app --port 8000 &   python -m app.worker &
cd ../frontend && npm ci && npm run dev
```
API documentation (OpenAPI): http://localhost:8000/api/docs

## How a question is answered
1. Retrieve from **your selected documents only** (Qdrant vectors + PostgreSQL full-text), rerank.
2. Add structured facts: extracted values ([M#]) and Python-computed ratios ([C#]) relevant to the
   question, filtered by any basis/period the question names.
3. The LLM must cite sources inline, copy numbers exactly, never compute, and reply
   `INSUFFICIENT_EVIDENCE` when the sources do not support an answer.
4. FinRAG verifies the answer: numbers that do not appear in the cited sources are flagged
   (`answered_with_warnings`); answers without valid citations, answers citing a source that was not
   provided, and answers whose cited sources do not mention the period asked about are withheld.

## Data integrity rules (enforced in code)
* No fabricated data: empty states when nothing is uploaded; missing metadata → "Not detected".
* Every extracted value keeps its raw label, raw printed value, unit, column/period, basis and exact
  source location; normalised values are only computed when the unit is known.
* Automated checks can mark values `validated`/`failed_validation`/`needs_review`; only a person can
  mark them `verified` or `rejected` (audited).
* Ratios and derived totals are computed in Python only when all inputs exist for the same document,
  basis, unit and period **and** every input is `validated` (accounting check) or `verified` (by a
  person); otherwise the result is `needs_verification` and names the inputs to verify.
* Comparisons warn about different currencies, units, bases, period types, organisations and
  restatements.

## Testing
```bash
cd backend && python -m pytest -q
```
The suite (82 tests) uses an isolated test database and Qdrant collection. Unit tests use small,
clearly marked synthetic inputs to exercise code paths; tests that check extraction accuracy use a
genuine public annual report placed in `FINRAG_TEST_DOCS` (skipped if absent). See
`docs/PROGRESS.md` for the latest recorded run.

## Evaluation and fine-tuning
* `docs/EVALUATION.md` — methods, gold-file formats and the results actually measured (with regression vs
  independent caveats).
* `docs/FINE_TUNING.md` — LoRA pipeline and the measured base-vs-LoRA comparison.
* `docs/NVIDIA.md` — CUDA/NIM/TensorRT-LLM/NeMo status: what is implemented vs. verified.
  **No GPU was available during development; nothing claims GPU acceleration.**

## Documentation
`docs/ARCHITECTURE.md` · `docs/DEVELOPMENT_GUIDE.md` · `docs/NOTEBOOK_GUIDE.md` · `docs/LEARNING_ROADMAP.md` ·
`docs/SECURITY.md` · `docs/DEPLOYMENT.md` · `docs/NVIDIA.md` · `docs/EVALUATION.md` · `docs/FINE_TUNING.md` ·
`docs/DEMO.md` · `docs/PROGRESS.md` · `docs/RESTRUCTURING_REPORT.md` ·
`docs/END_TO_END_DATA_FLOW_AUDIT.md` (23-stage trace, live audit results, outstanding issues) ·
`docs/PRODUCT_GAP_ANALYSIS.md` (product vision audit, roadmap and status) · `docs/ACCEPTANCE_TESTS.md` (15 acceptance criteria, live results, screenshots)

## Known limitations
* CPU inference: a RAG answer takes about a minute with the local 4-bit 4B model (median 55 s on
  4 vCPU); use a GPU endpoint for interactive latency.
* PDF tables that rely on complex multi-level headers (e.g. paired currency sub-columns) are
  extracted but flagged `needs_review` rather than guessed.
* Currency symbols that a PDF encodes with a private font (e.g. ₹ rendered as "C") cannot be read;
  the currency is marked "uncertain" and the user is asked to confirm it.
* The LoRA dataset is limited to values that passed accounting checks, so it is small unless users
  verify more values.
