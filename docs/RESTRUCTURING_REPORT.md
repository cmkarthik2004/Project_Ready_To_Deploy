# Restructuring report: production code vs learning notebooks (2026-11-24)

## 1. Audit (before any change)
* Repository: 3 commits, clean working tree, **72 tracked files**; **41 Python modules** in `backend/` (6,540 lines),
  Next.js frontend (14 pages + components), Alembic migrations (2), tests (4 files, 52 tests), docs (9 files).
* **No Jupyter notebooks and no exploratory scripts existed** — every `.py` file was production code.
* Secrets: `.env` has never been committed (checked across all history); no secret-like literals in any
  revision. `data/uploads/` holds user uploads and is git-ignored. No rotation is needed.
* Services: PostgreSQL 16, Qdrant 1.20, llama.cpp server (Qwen3-4B Q4_K_M), API, worker, web.

### Classification
| Category | Content | Decision |
|---|---|---|
| A — production `.py` | all of `backend/app/**`, tests, Alembic, fixture builder | stays in `backend/`; reorganised where a module mixed responsibilities |
| B — learning | (none existed) | 14 new notebooks in `notebooks/` that **import** category A |

## 2. Target structure and rationale
Only purposeful moves (no renames for their own sake, no compatibility shims, one implementation per function):

| Before | After | Why |
|---|---|---|
| `rag/llm.py` | `llm/client.py` | the LLM client serves RAG, reports and Settings — not RAG-specific |
| `rag/pipeline.py` (285 lines) | `rag/retriever.py`, `rag/facts.py`, `rag/verification.py`, `rag/rag_pipeline.py` | each RAG stage importable and testable on its own (notebooks 10–11, `tests/test_rag_units.py`) |
| `rerank()` in `rag/embeddings.py` | `rag/reranker.py` | separate model and responsibility |
| `parsers/spreadsheet_parser.py` | `parsers/excel_parser.py` (.xlsx, .xls) + `parsers/csv_parser.py` | one parser module per format |
| OCR code inside `parsers/pdf_parser.py` | `document_processing/ocr_service.py` | reusable OCR service (notebook 05) |
| `document_processing/pipeline.py` | `document_processing/ingestion.py` | two different modules were both called `pipeline.py` |
| `document_processing/chunker.py` | `document_processing/chunking.py` | target naming; clearer as a noun for the stage |
| `service.compare_documents` | `financial_analytics/comparison.py` | business logic separated from data loading/grouping |
| report building in `api/reports.py` | `financial_analytics/reporting.py` (+ `ReportError`) | routers contain HTTP concerns only |
| Pydantic models inside 6 routers | `app/schemas/{analytics,auth,chat,documents,reports,system}.py` | requested layout; thinner routers |
| `service._groups` | `service.group_metrics` | now used across modules, so public |
| — | `notebooks/` (14 `.ipynb` + `finrag_nb.py`), `requirements-notebooks.txt` | learning layer |
| — | `docs/NOTEBOOK_GUIDE.md`, `LEARNING_ROADMAP.md`, `DEVELOPMENT_GUIDE.md`, this report | documentation |

Kept as they were (already cohesive): `core/`, `database/`, `models/`, `api/` (thinned), `worker.py`,
`metric_extractor.py`, `numbers.py`, `validation.py`, `ratios.py`, `service.py`, `metadata.py`, `elements.py`,
`evaluation/`, `fine_tuning/`, Alembic, Dockerfiles, compose, frontend (no frontend change was needed).
`tests/` stays under `backend/` (it tests the backend package and uses its virtualenv).

## 3. File-by-file changes
**Moved / renamed** (git history preserved): `rag/llm.py → llm/client.py`; `rag/pipeline.py → rag/rag_pipeline.py`
(rewritten as orchestrator); `document_processing/pipeline.py → ingestion.py`; `chunker.py → chunking.py`.
**Deleted:** `parsers/spreadsheet_parser.py` (code moved verbatim into `excel_parser.py` / `csv_parser.py`).
**New production modules:** `llm/__init__.py`, `rag/retriever.py`, `rag/facts.py`, `rag/verification.py`,
`rag/reranker.py`, `document_processing/ocr_service.py`, `parsers/excel_parser.py`, `parsers/csv_parser.py`,
`financial_analytics/comparison.py`, `financial_analytics/reporting.py`, `schemas/*.py` (7 files).
**Modified (imports / moved code):** `api/{analytics,auth,chat,documents,evaluation,reports,system}.py`, `worker.py`,
`evaluation/runner.py`, `ingestion.py`, `pdf_parser.py`, `embeddings.py`, `service.py`.
**Modified (behaviour — bugs found while building notebooks and tests, see §4):** `rag/verification.py`, `rag/facts.py`,
`rag/prompts.py`, `financial_analytics/ratios.py`, `financial_analytics/validation.py`, `document_processing/elements.py`.
**Tests:** `test_parsers.py`, `test_api.py` (new import paths, zero-index location test); `test_analytics.py` (+2 tests);
new `test_rag_units.py` (8 tests). **Docs:** `ARCHITECTURE.md` updated; 4 new documents.
**Unchanged:** frontend, Dockerfiles, `docker-compose.yml`, Alembic migrations, `.env`, `.env.example`.

## 4. Defects found during the restructuring (all fixed; #1–#5 with new tests)
| # | Found by | Defect | Fix |
|---|---|---|---|
| 1 | new unit test | number verifier treated an invented `200` as supported by the `2` in `2030` (trailing-zero tolerance applied to integers, no right boundary) | tolerance only for decimals, with boundaries |
| 2 | notebook 10 | *"total borrowings"* answered with the non-current part only (faithful but wrong) | Python-derived `[C#]` total with its definition; prompt rule 8 |
| 3 | notebook 10 | *"expected share price in 2030"* answered with a historical figure; a prompt rule did **not** fix it | deterministic check: question years must appear in cited sources |
| 4 | notebook 12 | growth −56.6% computed from `needs_review` inputs (US$ sub-column; profit row in a balance-sheet note) | `needs_review` inputs block ratios/growth; flow item under an "As at" column → `needs_review`; growth warns on unvalidated inputs |
| 5 | API format check | `Location.to_dict()` dropped `table_index = 0` (`0 in (None, [], False)` is True), so DOCX citations lost "table 1 row N" | identity checks; test |
| 6 | notebook 11 | MRR printed `nan` | notebook fix (`pd.notna`) |
| 7 | intermittent test failure (2 of ~20 runs) | **test bug**: the duplicate-upload test built its DOCX twice; python-docx stamps a modification time, so builds straddling a second boundary differ in bytes/SHA-256 and the "duplicate" was rightly accepted. Confirmed by building twice 1.1 s apart (different hashes). Product behaviour was correct | build the bytes once and upload them twice |

Effect on stored data: all documents were reprocessed after #4 and the DOCX documents again after #5, through
the normal reprocess API.

## 5. Verification (all executed on 2026-11-24)
| Check | Result |
|---|---|
| Import every backend module (dev venv) | 65/65 import, no circular imports |
| Backend test suite | **63 passed** (was 52), 6 consecutive green runs after fix #7 |
| Frontend | `tsc --noEmit` clean; `next build` succeeds |
| Browser E2E (`e2e/smoke.mjs`) | 10/10 steps, DOCX upload |
| All 5 formats via API, fresh user | PDF (incl. production OCR path), DOCX, XLSX, XLS, CSV processed; citations: page / section+table+row / sheet+cell / row |
| RAG regression (stored run 5, same 8 gold questions) | 8/8 answers, citations and faithfulness — a regression result, not an independent benchmark |
| Notebooks | 14/14 valid nbformat, executed with kernel *FinRAG (backend venv)*, 0 error outputs, all required sections, 0 secrets / connection strings |
| Backend Docker image (rebuilt) | builds; migrations run; `/api/health/ready` ok; 63/65 modules import (the 2 LoRA scripts need `requirements-finetune.txt`, deliberately not in the CPU image) |

## 6. Hardware-dependent or incomplete
* No NVIDIA GPU: CUDA inference/training, TensorRT-LLM, NeMo and the NIM container were not run; notebook 14 skips
  those cells explicitly. Hosted NIM inference needs `NVIDIA_API_KEY` (not provided).
* LoRA was not retrained during the restructuring (notebook 13 has a `RUN_TRAINING` guard); its results are from the
  2026-11-23 CPU run.
* Docling remains an optional engine in a separate virtualenv and is not exercised by tests or notebooks.
* Full `docker compose up` was not run in this environment (the stack ran natively via `deployment/dev-services.sh`).
