# Notebook guide

The `notebooks/` folder is FinRAG's **learning layer**. The application's logic lives only in
`backend/app/` (production `.py` modules); every notebook *imports* that code and experiments with it.
Nothing is copied, so what you learn is exactly what the application does.

```
notebooks/
  finrag_nb.py                      helper: puts backend/ on the path, safe (secret-free) settings, document folder, DB session
  01_python_financial_data.ipynb    … 14_nvidia_gpu_experiments.ipynb
```

## Setup (once)
```bash
cd backend && . .venv/bin/activate
pip install -r requirements-notebooks.txt          # + requirements-finetune.txt for notebook 13
python -m ipykernel install --user --name finrag --display-name "FinRAG (backend venv)"
cd ../notebooks && jupyter lab                     # or VS Code; choose the kernel "FinRAG (backend venv)"
```
* **Documents**: FinRAG ships none. Put your own financial files in a folder and set
  `FINRAG_NOTEBOOK_DOCS=/that/folder` (default `/opt/finrag_testdocs`). The saved outputs were produced
  with the public documents listed in `docs/evaluation/README.md`; change the filename variables at the
  top of a notebook to use yours.
* **Services**: notebooks 07 and 08–12 read the application database (and Qdrant); 10 and 14 also call
  the LLM endpoint. Start them with `deployment/dev-services.sh` (or docker compose) and upload documents
  in the app first. `FINRAG_NOTEBOOK_USER=<your login email>` selects whose documents are read.
* **Secrets**: notebooks never print settings directly; use `nb.safe_settings()`. Keys live in `.env` only.

## Order and dependencies

| # | Notebook | Production code it exercises | Needs services? | Typical run time (CPU, saved run) |
|---|---|---|---|---|
| 01 | Python & financial data | `elements.py`, `numbers.py`, `metric_extractor.METRICS` | no | seconds |
| 02 | PDF processing | `parsers/pdf_parser.py` | no | ~20 s |
| 03 | DOCX processing | `parsers/docx_parser.py`, `validation.py` | no | seconds |
| 04 | Excel & CSV | `parsers/excel_parser.py`, `csv_parser.py`, `tabular.py` | no | seconds |
| 05 | OCR | `ocr_service.py`, `pdf_parser.py` | no (Tesseract data) | ~20 s |
| 06 | Financial extraction | `metric_extractor.py` + gold file | no | seconds |
| 07 | Financial validation | `financial_analytics/validation.py`, stored metadata | PostgreSQL | seconds |
| 08 | Embeddings | `rag/embeddings.py` | PostgreSQL (chunks) | ~75 s |
| 09 | Qdrant | `rag/vector_store.py` | PostgreSQL, Qdrant | ~15 s |
| 10 | RAG pipeline | `rag/retriever.py`, `reranker.py`, `facts.py`, `prompts.py`, `verification.py`, `rag_pipeline.py`, `llm/client.py` | all + LLM | ~1.5–2 min |
| 11 | RAG evaluation | `evaluation/runner.py` results, `retriever.py` | PostgreSQL, Qdrant | ~20 s |
| 12 | Financial analytics | `ratios.py`, `service.py`, `comparison.py` | PostgreSQL | seconds |
| 13 | LoRA fine-tuning | `fine_tuning/*` (dataset, config, adapter) | no (model files) | ~2–4 min; training itself is guarded |
| 14 | NVIDIA experiments | `/api/status` checks, `embeddings.device()`, `llm/client.py` | LLM for §5 | ~1 min; GPU cells skip without a GPU |

Suggested paths:
* **Document intelligence**: 01 → 02 → 03 → 04 → 05 → 06 → 07
* **RAG**: 01 → 02 → 08 → 09 → 10 → 11
* **Analytics**: 06 → 07 → 12
* **Models & deployment**: 08 → 10 → 13 → 14

## How notebooks map to the running application
| In the app | Learn it in |
|---|---|
| Upload page validation messages | 03 §1, `validation.py` |
| Document Analysis → metadata, statements, values, checks | 02, 06, 07 |
| AI Financial Chat answers, citations, warnings | 10 |
| Evaluation page | 11, 13 |
| Financial Ratios / Analytics / Compare | 12 |
| AI Model & RAG Status | 08, 09, 14 |

## About the saved outputs
All outputs were produced by actually executing the notebooks (kernel *FinRAG (backend venv)*) on a
4-vCPU, 15 GB RAM machine **without an NVIDIA GPU**, on 2026-11-24. Where an experiment changed the
production code (notebooks 10 and 12 found real failures), the notebook records what happened in the
first run and what was fixed. Re-running on your machine and documents will give different numbers —
that is the point.

## Common problems
| Problem | Fix |
|---|---|
| `ModuleNotFoundError: app` / `finrag_nb` | Start Jupyter in `notebooks/` and select the FinRAG kernel |
| `FileNotFoundError` from `nb.doc_path` | Set `FINRAG_NOTEBOOK_DOCS` or edit the filename variable |
| `LookupError: No user has processed documents` | Upload documents in the app, or set `FINRAG_NOTEBOOK_USER` |
| Connection refused (DB/Qdrant/LLM) | `deployment/dev-services.sh`, then check `/api/health/ready` |
