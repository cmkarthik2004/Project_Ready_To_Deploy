# Development guide

## Principles
1. **Production logic lives in `backend/app/` only.** Notebooks import it; they never contain a second
   implementation. If a notebook experiment becomes a feature, move the code into a module, add tests,
   and make the notebook import it.
2. **One authoritative implementation per function.** No duplicate helpers, no compatibility shims.
3. **No fabricated data.** Tests use clearly marked synthetic *parser inputs* or genuine public documents;
   the application ships no documents and shows empty states until users upload.
4. **Traceability first.** Every new extraction path must produce a `Location`; every number shown must be
   traceable to a source or to a Python calculation with its inputs.
5. **Determinism where it matters.** Arithmetic in Python (`Decimal`), never in the LLM.

## Layout and layering
```
api/  (HTTP only)  ──►  schemas/ (request models)
  │
  ├──► document_processing/  ──► parsers/, ocr_service, metadata, chunking, ingestion
  ├──► financial_analytics/  ──► numbers, metric_extractor, validation, ratios, service, comparison, reporting
  ├──► rag/                  ──► embeddings, reranker, vector_store, retriever, facts, prompts, verification, rag_pipeline
  ├──► llm/client.py
  └──► evaluation/, fine_tuning/
core/ (config, security, logging), database/, models/ are used by all layers.
```
Rules: routers contain no business logic (validate input → call a module → shape the response → audit);
modules raise domain errors (e.g. `ReportError`) that routers translate to HTTP; nothing imports from
`api/` except `main.py`.

## Running locally
```bash
deployment/dev-services.sh            # PostgreSQL, Qdrant, llama-server, API, worker, web
cd backend && .venv/bin/python -m pytest -q
cd frontend && npx tsc --noEmit && npx next build
NODE_PATH=$(npm root -g) node e2e/smoke.mjs http://127.0.0.1:3000 <a real document>
```
Logs: `/tmp/finrag_logs/*.log` (JSON lines from the API and worker).

## Common tasks
### Add a document format
1. Validation: signature and safety checks in `document_processing/validation.py` (+ tests).
2. Parser: `parsers/<format>_parser.py` returning a `ParsedDocument` whose elements carry `Location`s.
3. Register it in `ingestion.parser_for` and extend `elements.describe_location` if the location type is new.
4. Tests in `tests/test_parsers.py`; a section in the matching notebook.

### Add a canonical metric
Add a `MetricDef` to `metric_extractor.METRICS` (specific patterns before general ones; use `group_topic` /
`group_required` for ambiguous labels), then a test in `tests/test_analytics.py`. If an accounting
identity involves it, add an `IdentityCheck` in `validation.py`.

### Add a ratio
Add it to `ratios.compute_point_ratios` (or `growth`) using `_ratio(...)` so missing inputs, blocking
statuses (failed / rejected / needs review) and zero denominators are handled uniformly; document the
formula; add a test.

### Change RAG behaviour
Retrieval → `rag/retriever.py`; structured facts → `rag/facts.py`; prompt rules → `rag/prompts.py`;
checks → `rag/verification.py`. Add a unit test in `tests/test_rag_units.py`, then re-run the RAG
evaluation **and say in `docs/EVALUATION.md` that it reuses the same gold set** if it does.

### Add or update a notebook
Keep the structure (objectives, prerequisites, concept, why in FinRAG, workflow, steps, interpretation,
troubleshooting, exercises, summary, further learning). Import production code via `finrag_nb.py`, never
print secrets, execute the notebook before committing, and write the interpretation **after** reading the
real outputs.

## Database changes
Edit `models/entities.py`, then
`cd backend && .venv/bin/alembic revision --autogenerate -m "<what>"`, review the generated migration,
`alembic upgrade head`. The test suite builds its schema through the migrations.

## Before committing
* `python -m pytest -q` green; `pyflakes app tests` clean.
* Frontend: `tsc --noEmit` and `next build`.
* No secrets: `.env` is git-ignored; notebooks contain no keys or connection strings
  (check: `grep -l "postgresql+psycopg://" notebooks/*.ipynb` must print nothing).
* Docs updated (architecture, notebook guide, evaluation) when behaviour changes.
