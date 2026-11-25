# FinRAG Architecture

FinRAG is a **universal** financial document intelligence platform: users upload their own
PDF, Word, Excel or CSV files; FinRAG detects what is in them, extracts and validates financial
values, indexes the content for retrieval-augmented question answering, and analyses the data.
There is **no predefined company list, dataset or financial-year requirement** — an empty
installation shows empty states until a user uploads documents.

```
 Browser ──► Next.js (web, :3000) ──/api/* rewrite──► FastAPI (api, :8000) ──► PostgreSQL
                                                          │   ▲                 (documents, metrics, chats, audit…)
                                                          │   │
                                         processing_jobs ─┘   │   ┌──► Qdrant (vectors + owner/document payload)
                                                              │   │
                                         worker (python -m app.worker)
                                           parse → metadata → metrics → validate → chunk → embed → index
                                                              │
                         OpenAI-compatible LLM endpoint ◄─────┘   (llama.cpp CPU · NVIDIA NIM · vLLM · TensorRT-LLM)
```

## 1. Components

| Component | Technology | Role |
|---|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts 3 | 12-page dashboard; proxies `/api/*` to the backend so the httpOnly auth cookie stays same-origin |
| API | FastAPI 0.165, Pydantic 2, SQLAlchemy 2.1, Alembic | REST API, auth/RBAC, uploads, analytics, RAG |
| Worker | same codebase (`app.worker`) | Claims jobs with `SELECT … FOR UPDATE SKIP LOCKED`; runs the processing pipeline |
| Relational DB | PostgreSQL 16 | All structured data, provenance, audit log |
| Vector DB | Qdrant 1.20 | 384-d BGE vectors, cosine; payload `owner_id`, `document_id` (indexed) |
| Embeddings | BAAI/bge-small-en-v1.5 (sentence-transformers) | Passage + query embeddings (query instruction prefix as recommended by BGE) |
| Reranker | cross-encoder/ms-marco-MiniLM-L6-v2 | Reranks hybrid retrieval candidates |
| LLM | Qwen3-4B (Q4_K_M GGUF) on llama.cpp server, CPU | Answer generation under citation rules; swappable for NVIDIA NIM etc. |
| OCR | Tesseract 5 via PyMuPDF | Image-only PDF pages |

### Backend module map (after the restructuring — see docs/RESTRUCTURING_REPORT.md)
```
backend/app/
  main.py                     FastAPI app, middleware, error handlers
  worker.py                   background job worker (python -m app.worker)
  core/                       config (settings from .env), security (Argon2, JWT, roles), logging
  database/session.py         SQLAlchemy engine/session      models/entities.py   ORM tables
  schemas/                    Pydantic request models (one module per router)
  api/                        HTTP routers only: auth, documents, analytics, chat, reports, evaluation, system, deps
  document_processing/
    validation.py             upload validation (magic bytes, size, PDF/ZIP safety)
    parsers/                  pdf_parser, docx_parser, excel_parser (.xlsx/.xls), csv_parser, tabular, docling_*
    ocr_service.py            Tesseract OCR via PyMuPDF
    elements.py               Element / Location data model      metadata.py   organisation, period, currency, unit, category
    chunking.py               chunks + injection flag            ingestion.py  parse → … → index orchestration
  financial_analytics/
    numbers.py  metric_extractor.py  validation.py  ratios.py
    service.py (load/group metrics, compute ratios)  comparison.py  reporting.py
  rag/
    embeddings.py  reranker.py  vector_store.py  retriever.py  facts.py  prompts.py  verification.py  rag_pipeline.py
  llm/client.py               OpenAI-compatible client (llama.cpp, NVIDIA NIM, vLLM, TensorRT-LLM)
  evaluation/runner.py        extraction / gold / RAG evaluations
  fine_tuning/                build_dataset.py  train_lora.py  evaluate_lora.py
notebooks/                    14 learning notebooks + finrag_nb.py helper (import the real app package)
```

### Why some choices differ from the original brief

* **LlamaIndex/LangChain are not used.** The RAG pipeline (`app/rag/`: retriever, facts, prompts, verification,
  rag_pipeline) is ~450 lines of
  explicit code. For a learning project and for financial auditability it is valuable to see every
  step (filtering, hybrid retrieval, reranking, structured facts, citation verification) without
  framework abstractions. Qdrant and the embedding models are used directly.
* **Docling is optional and isolated.** `docling-ibm-models` pins `huggingface_hub<2`, which breaks
  `transformers` 5.x used by the embedding stack (verified: installing it broke model loading).
  Docling therefore runs in its own virtualenv as a subprocess (`PDF_TABLE_ENGINE=docling`,
  `DOCLING_PYTHON=…`); PyMuPDF is the default PDF engine.
* **LLM via an OpenAI-compatible endpoint.** The same client talks to llama.cpp (CPU, used in
  development), NVIDIA NIM (hosted or container), vLLM or TensorRT-LLM servers. Admins can register
  endpoints in Settings; API keys stay in environment variables.

## 2. Universal document model

Every parser converts its input into `Element`s (`app/document_processing/elements.py`) — heading,
paragraph, table row, table, text — each with a `Location`:

| Format | Parser | Location kept |
|---|---|---|
| PDF | PyMuPDF (+ Tesseract OCR, optional Docling tables) | PDF page, printed page label, spread half (left/right), bbox, table index |
| DOCX | python-docx | heading path (Heading 1 > Heading 2 …), paragraph index, table index + row |
| XLSX | openpyxl (formulas **and** cached values) | sheet, A1 cell, row; formula text kept; uncached formulas reported, never evaluated by guess |
| XLS | pandas + xlrd | sheet, A1 cell, row (formulas not available in BIFF via xlrd — warned) |
| CSV | pandas (encoding + delimiter sniffing, read as strings) | row number (header = row 1) |

Table rows keep each value's **column header** so the period ("2024-25", "As at 31 March 2025",
"Budget", "Actual") travels with the number.

### PDF specifics learned from real documents
* **Two-page spreads**: landscape pages whose halves carry different printed page numbers are split
  into left/right regions so facing pages never interleave. Citations show both the PDF page and the
  printed page label.
* **Text-aligned statements** (no ruling lines): words are grouped into visual lines; a line with ≥2
  period tokens in separate columns is a header; numbers are assigned to the nearest header column by
  x-position; note references between label and amounts are dropped.
* **Row groups**: label-only lines inside a statement ("Current Liabilities", "Net Profit Attributable
  to:") are tracked so "Borrowings" under current vs. non-current liabilities map to different metrics.
* **Ruled tables** use `page.find_tables()`, only on pages with numbers and ruling lines (speed), and
  only if the result passes a quality gate (no merged multi-line or fragmented cells).
* **Font-encoded currency symbols** (e.g. ₹ rendered as "C") are not guessed: the currency becomes
  `uncertain` and the user is asked to confirm.

### Spreadsheet / CSV specifics
* Wide layouts (line items × periods) and long layouts (records such as transactions) are detected.
* For record layouts, FinRAG computes column totals and per-category sums **in Python** and indexes
  them as clearly labelled "[Computed by FinRAG]" text, so "which expense category is highest?" is
  answered from arithmetic done by code, not by the LLM.

## 3. Processing pipeline (`app/document_processing/ingestion.py`)

`parse → detect_metadata → extract_and_validate → persist → chunk → embed → index`. Each stage is
timed and logged into `processing_jobs.log`. A document becomes `processed` only after vectors are
written to Qdrant; any exception marks it `failed` with the real error message.

### Metadata detection (`metadata.py`)
Organisation (legal-entity suffix patterns, auditor names penalised), reporting period ("year/period
ended <date>"), fiscal year (derived deterministically from a year-end date or from FY tokens),
category (keyword scoring), currency (from table unit statements/headers only; prose mentions make it
`uncertain`), units (crore/lakh/million/billion/thousand). Each field stores value, status
(`detected`, `not_detected`, `uncertain`, `user_corrected`), method, confidence and evidence
(snippet + location). Users can correct any field; corrections survive re-processing.

## 4. Financial intelligence

* **Metric extraction** (`financial_analytics/metric_extractor.py`): ~45 canonical metric definitions
  matched on normalised labels. Similar-sounding items stay distinct (revenue from operations ≠ total
  revenue ≠ net sales; profit after tax ≠ profit for the year). Spreadsheet/Word rows that are not
  canonical are kept as `line_item`s (budget lines, expense categories). Each value keeps raw label,
  raw printed value, Decimal value, unit + multiplier, normalised value (only when the unit is known),
  currency, column/period label, period end date (only if printed), statement type, basis
  (consolidated/standalone/not detected — from the title or a running page header), location,
  method and confidence.
* **Validation** (`validation.py`): accounting identities evaluated per basis/column (assets =
  equity + liabilities; assets = current + non-current; total income = revenue + other income; net
  profit = owners + NCI; PBT = income − expenses; …), sign checks, conflicting values within the same
  table, duplicates, and "Total" rows vs. the sum of rows above in spreadsheets. Automation can set
  `validated`, `failed_validation`, `needs_review` or leave `unvalidated`; **only a person** can set
  `verified` or `rejected` (audited).
* **Ratios** (`ratios.py`): Python `Decimal` arithmetic. A ratio is computed only when all inputs exist
  for the same document, basis, unit and column, and none failed validation. Each result stores the
  formula, inputs with their sources and validation status, and warnings (e.g. closing vs. average
  equity, derived operating profit, debt definition excluding leases).
* **Comparison** (`financial_analytics/comparison.py`): side-by-side values per document/basis/unit/period
  with warnings for differing currencies, units, bases, point-in-time vs. period columns, different
  or undetected organisations, and restatements (same organisation/period/metric, different value).

## 5. RAG pipeline (`app/rag/rag_pipeline.py` orchestrating `retriever.py`, `reranker.py`, `facts.py`, `prompts.py`, `verification.py`)

1. **Scope**: only the requesting user's processed documents, optionally narrowed to selected
   documents or a collection (Qdrant filter on `owner_id` + `document_id`, re-checked in SQL).
2. **Hybrid retrieval**: Qdrant dense search (BGE, query instruction) + PostgreSQL full-text search
   (GIN index), top 24 each.
3. **Rerank** with the cross-encoder; keep the top 5 passages (CPU prompt budget).
4. **Structured facts**: extracted metric values relevant to the question ([M#]) and, for calculation
   questions, Python-computed ratios ([C#]) — both filtered by any basis ("consolidated") or period
   ("2024-25") the question mentions.
5. **Generation** with a system prompt that requires inline citations, forbids arithmetic and unit
   conversion, requires attribution per document, defines an exact `INSUFFICIENT_EVIDENCE` reply, and
   declares source text to be data. Chat-template tokens are stripped from sources; chunks with
   instruction-like text are flagged at ingestion.
6. **Verification** (`verification.py`): citations must reference provided sources; every multi-digit
   number in the answer must occur in a cited source; every year named in the question must appear in
   a cited source (blocks e.g. forecasts answered with historical figures). Answers with no valid
   citation or a missing period are replaced by an insufficient-evidence message (raw output kept for
   audit). Unsupported numbers → status `answered_with_warnings`, shown prominently in the UI.
   When a question asks for a total that is not printed (e.g. total borrowings), a Python-derived
   `[C#]` fact with its definition is supplied so the model never adds numbers itself.

## 6. Data model (PostgreSQL)

`users`, `organisations`, `collections` (+ `collection_documents`), `documents`, `processing_jobs`,
`document_tables`, `document_chunks`, `source_references`, `financial_statements`,
`financial_metrics`, `financial_calculations`, `chat_sessions`, `chat_messages`,
`model_configurations`, `evaluation_runs`, `audit_logs`. Every financial metric references a
`source_references` row (document + exact location + snippet). Schema changes go through Alembic
migrations (`backend/alembic/versions`).

## 7. Fine-tuning (`app/fine_tuning`)

LoRA (PEFT + TRL) on a small instruction model for structured extraction of a table row into
canonical JSON. Training data is built only from values that passed validation or were human
verified, split by document, with leakage removal. Fine-tuning does not replace RAG: answers about
company facts still come from retrieved passages and stored, validated records. See
`docs/FINE_TUNING.md` for the measured results.
