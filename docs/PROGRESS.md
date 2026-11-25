# Project progress checklist

Legend: ✅ implemented and verified by running it · ⚠️ implemented, partially verified (reason given) ·
❌ not done / blocked (reason given). "Verified" means it was executed in the development
environment (4 vCPU, 15 GB RAM, no GPU) — see the evidence column.

## Environment (inspected first)
| Item | Value |
|---|---|
| OS / CPU / RAM / disk | Linux x86-64, 4 vCPU, 15 GB RAM, 61 GB free |
| GPU | none (`nvidia-smi` absent, `torch.cuda.is_available() == False`) |
| Python / Node / Git / Docker | 3.13.18 / 22.23.5 / 2.43.0 / 29.10.0 |
| PostgreSQL / Qdrant / Tesseract | 16.15 / 1.20.0 (binary release) / 5.3.4 |

## Universal document upload & processing
| Requirement | Status | Evidence |
|---|---|---|
| Upload PDF, DOCX, XLSX, XLS, CSV; multiple files per request | ✅ | `test_upload_validation_and_multi_upload`; 8 files of 4 formats uploaded in one request; E2E browser test |
| Magic-byte validation, size limit, corrupted / encrypted / macro / zip-bomb / `/Launch` rejection | ✅ | `test_numbers_and_validation.py` (11 tests) |
| PDF text + tables + page numbers (+ printed page labels, two-page spreads) | ✅ | real 146- and 159-page reports; `test_real_pdf_statement_values_and_identities` |
| OCR for scanned pages | ✅ | `test_pdf_ocr_or_reported` (image-only page OCR'd with Tesseract) |
| DOCX headings / paragraphs / tables with section paths | ✅ | `test_docx_headings_tables_locations` |
| Excel sheet names, cell coordinates, headers, formulas (uncached formulas reported) | ✅ | `test_xlsx_cells_formulas_and_uncached` |
| CSV row references; record-layout totals computed in Python | ✅ | `test_csv_rows_and_record_summaries` |
| Docling | ⚠️ | Optional engine in a separate venv (dependency conflict documented); runner code present; not exercised end-to-end in tests |
| Metadata detection (organisation, period, FY, category, currency, units) with evidence; "Not detected"/"Uncertain"; user correction | ✅ | real reports: organisation, period, FY, category, unit detected; currency correctly *uncertain* (font-encoded ₹); `test_processing_metadata_metrics_and_isolation` |
| Chunking, BGE embeddings, Qdrant storage, delete removes vectors | ✅ | 748/797 chunks indexed per report; `test_delete_removes_vectors` |

## RAG
| Requirement | Status | Evidence |
|---|---|---|
| Document- and collection-level filtering, tenant isolation | ✅ | Qdrant filter on owner+documents, SQL re-check; isolation test |
| Hybrid retrieval + reranking | ✅ | dense (Qdrant) + PostgreSQL FTS + cross-encoder |
| Citations: filename + page / section / sheet+cell / row | ✅ | real answers cite "page 100 (printed p. 196)" |
| Insufficient-evidence handling; uncited answers withheld; unsupported numbers flagged | ✅ | `test_rag_verifier_rejects_uncited_and_flags_unsupported`; real answer flagged LLM arithmetic |
| Prompt-injection defences | ✅ | sources as data, token stripping, ingestion flag (`test_chunk_injection_flag`) |
| Calculations by Python, not the LLM | ✅ | real answer: consolidated net profit margin 8.2957% from [C1] |

## Financial intelligence
| Requirement | Status | Evidence |
|---|---|---|
| Automatic metric detection (≈45 canonical metrics + spreadsheet line items) with provenance | ✅ | 333 / 287 values from the two reports; gold check 15/15 |
| Validation (identities, signs, conflicts, duplicates, column totals); human verify/reject | ✅ | 96.5% identity pass rate; `test_validation_pass_fail_and_never_verified` |
| Ratios only when inputs exist; formula + inputs + sources; zero/negative handling | ✅ | `test_ratios_*`, `test_ratio_zero_denominator_and_invalid_input`, year-alignment test |
| Compare documents with currency/unit/basis/period/organisation/restatement warnings | ✅ | two real reports compared; derived XLSX vs CSV unit warning test |
| Reports (overview, performance, trends, ratios, comparison, AI summary, limitations), Markdown export | ✅ | `test_processing_metadata_metrics_and_isolation` (report + markdown) |

## Dashboard (Next.js)
| Requirement | Status | Evidence |
|---|---|---|
| 12 pages, real API data, empty/loading/error states, light/dark, responsive | ✅ | production build; Playwright screenshots; `e2e/smoke.mjs` passed (empty states, upload, live status, counts, no console errors) |

## NVIDIA / fine-tuning / evaluation
| Requirement | Status | Evidence |
|---|---|---|
| CUDA detection in status API | ✅ | reports no GPU on this host |
| NIM / TensorRT-LLM via OpenAI-compatible endpoint registry | ⚠️ | implemented and testable from Settings; NIM host reachable; **no API key → no NIM inference run** |
| NIM container profile, CUDA Dockerfile | ⚠️ | written; not run (no GPU) |
| NeMo | ❌ | documented alternative only (`docs/NVIDIA.md`) |
| LoRA dataset from validated real extractions, document-level split | ✅ | 49 train / 127 test examples |
| LoRA training | ✅ (CPU) | Qwen3-0.6B, 3 epochs, 583 s on CPU; manifest records device = CPU |
| Base vs LoRA held-out comparison | ✅ | 127 held-out rows: base 0.0% vs LoRA 69.3% fully correct (caveats in `docs/FINE_TUNING.md`) |
| Evaluation dashboard with real runs only | ✅ | extraction, extraction_gold (15/15), rag (4 runs; final 8/8, see caveats), finetune runs stored and displayed |

## Security, deployment, docs
| Requirement | Status | Evidence |
|---|---|---|
| Argon2id, JWT httpOnly cookies, RBAC, rate limits, audit log, secure errors, headers | ✅ | auth/RBAC tests; `docs/SECURITY.md` |
| Secrets only in env; `.env` git-ignored | ✅ | `.gitignore`, `.env.example` without values |
| Dependency checks | ✅ | `npm audit --omit=dev`: 0 vulnerabilities; `pip-audit -r requirements.txt`: no known vulnerabilities |
| Alembic migrations | ✅ | 2 migrations; test DB is created through them |
| Dockerfiles, compose, health checks, backups | ⚠️ | **both images built and run**: web image (runtime proxy verified with a bogus and a real backend), API image (non-root, Tesseract 5.5, migrations on start, `/api/health/ready` OK). Full `docker compose up` not run here (Docker Hub pull limits; the stack ran natively via `deployment/dev-services.sh`). Backup scripts syntax-checked, not run against a live compose stack |

## Issues found and fixed during development (selection)
* Docling's dependencies broke `transformers` (huggingface_hub<2, mismatched torchvision) → Docling isolated in its own venv.
* Two-page PDF spreads interleaved facing pages → split into left/right regions with printed page labels.
* PyMuPDF table finder produced fragmented cells on text-aligned statements → quality gate + line-based parser.
* Currency mis-detected as USD from prose (₹ font-encoded) → currency from table unit lines only, else *uncertain*.
* RAG prompts of 7k tokens took 5 min on CPU → compact context; native llama.cpp server.
* llama-cpp-python server grew to 9 GB, then llama-server's default 8 GiB prompt cache → OOM kills → native server with `--cache-ram 1024 -np 1` (peak 4.6 GB over a full evaluation).
* Next.js rewrites baked the backend URL at build time (broken in containers) → runtime proxy route.
* Ratios could not pair a year's profit with that year's balance sheet → fiscal-year alignment.
* RAG answered a consolidated question with a standalone figure → running headers kept in chunk context + basis guard.
* `growth()` constructor arguments in the wrong order → caught by the API tests.

## Test results (latest recorded run, end of development)
* Backend (after the 2026-11-24 restructuring): `python -m pytest -q` → **63 passed** (earlier: 52), including the real-LLM
  RAG test and the genuine-document accuracy tests.
* Frontend: `tsc --noEmit` clean; `next build` succeeds (14 pages + API proxy route).
* Browser E2E: `node e2e/smoke.mjs` → 10/10 steps passed (empty states, upload, live processing status,
  database-backed counts, no console errors), run with an XLSX and with a CSV.
* Docker: `finrag-web` and `finrag-api` images built and started successfully.
* Dependency audits: `npm audit --omit=dev` 0 vulnerabilities; `pip-audit -r requirements.txt` no known vulnerabilities.

## Not done / blocked
* **Push to GitHub** was refused: this session's GitHub integration has no access to the repository
  (see the final report). The work is committed locally on branch `claude/amazing-noether-631dkv`.
* GPU paths (CUDA training/inference, NIM container, TensorRT-LLM) — no GPU available.
* Hosted NVIDIA NIM inference — no API key provided.
* TCS/Infosys documents could not be downloaded (their sites returned HTTP 403 to automated
  requests); FinRAG no longer depends on any specific company, so this does not affect the product.

## 2026-11-24 — restructuring into production code + learning notebooks
See `docs/RESTRUCTURING_REPORT.md` for the audit, file-by-file changes, six defects found and fixed, and verification
(63 tests, E2E 10/10, all five formats, RAG regression run 5 8/8, 14 notebooks executed and validated, Docker image rebuilt).


## 2026-11-24 — end-to-end data flow audit
See `docs/END_TO_END_DATA_FLOW_AUDIT.md`: the 23 stages from browser upload to the displayed answer, with file/function,
input/output, storage, error handling and tests for each; 11 findings fixed (F1–F11), including an admin cross-user bypass,
stale data on failed jobs when Qdrant is down, a duplicate-upload race (now a unique index, migration `a3c91d2e7f10`),
calculations on unvalidated inputs, fabricated citations shown with a warning, and a Chat page crash in current Chromium.
Results: live audit 69/69 (`backend/scripts/e2e_data_flow_audit.py`, six new uploads in five formats incl. OCR), browser E2E
with a chat step passed, backend 66 passed, frontend type check and build clean, notebooks 10 and 12 re-executed.

## 2026-11-24 — financial intelligence platform (product vision)
Audit and roadmap: `docs/PRODUCT_GAP_ANALYSIS.md`. Implemented structure-aware extraction (Excel tables/merged headers/
formats/links, CSV profiling and locale handling, multi-page PDF tables), fact provenance and new reconciliation checks, the
automatic dashboard (service, API, `/dashboard` page with 10 chart types, filters, drill-down, exports, saved views) and the
dashboard-aware assistant (`[D#]` dashboard facts, `[H#]` Python scenarios). Results: backend 83 passed; acceptance run
48/48 (`docs/ACCEPTANCE_TESTS.md`, genuine reports + synthetic edge cases, real model on CPU); browser smoke test with chat passed;
screenshots in `docs/screenshots/`.
