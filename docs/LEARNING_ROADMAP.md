# Learning roadmap: from Python to RAG, fine-tuning and NVIDIA deployment

A suggested path through FinRAG for a beginner. Each stage lists **goals**, **what to study in FinRAG**
(notebooks and source files), a **hands-on milestone**, and how to know you are ready to move on.
Expect roughly 2–4 focused sessions per stage.

## Stage 1 — Python and data foundations
* Goals: functions, dataclasses, dicts/lists, pandas, `Decimal`, reading CSV/Excel, handling missing values.
* Study: notebook **01**; `backend/app/document_processing/elements.py`, `financial_analytics/numbers.py`.
* Milestone: load one of your own financial spreadsheets, parse every amount with `parse_number`, and list the cells that are not numbers.
* Ready when: you can explain why `-` must not become `0` and why `(15,124)` is negative.

## Stage 2 — Document intelligence
* Goals: how PDFs, DOCX and spreadsheets store content; coordinates; tables; OCR; source locations.
* Study: notebooks **02, 03, 04, 05**; `parsers/`, `ocr_service.py`, `chunking.py`, `ingestion.py`.
* Milestone: upload one PDF, one DOCX and one spreadsheet of your own; in Document Analysis, check that three values each cite the right page / section / cell.
* Ready when: you can explain how FinRAG attaches a period header to a number and what the OCR flag changes.

## Stage 3 — Financial extraction and validation
* Goals: canonical metrics, label matching, row groups, accounting identities, validation statuses, human verification.
* Study: notebooks **06, 07**; `metric_extractor.py`, `validation.py`.
* Milestone: add one new canonical metric with a unit test; verify or reject three `needs_review` values in the app.
* Ready when: you can predict which identity will fail if a given value is misread.

## Stage 4 — Embeddings and vector search
* Goals: tokenisation, embeddings, cosine similarity, HNSW, payload filters, tenant isolation.
* Study: notebooks **08, 09**; `rag/embeddings.py`, `rag/vector_store.py`.
* Milestone: measure how often dense search alone finds the right page for 10 questions about your document.
* Ready when: you can explain why embeddings alone cannot guarantee the right number or basis.

## Stage 5 — Retrieval-augmented generation
* Goals: hybrid retrieval, reranking, prompt construction, structured facts, LLM APIs, citation and number verification, prompt injection.
* Study: notebook **10**; `rag/retriever.py`, `reranker.py`, `facts.py`, `prompts.py`, `verification.py`, `rag_pipeline.py`, `llm/client.py`.
* Milestone: find a question where FinRAG answers wrongly but *faithfully* (as notebook 10 did), and design a generic fix with a test.
* Ready when: you can trace one answer from question to every cited page and explain each verification field.

## Stage 6 — Evaluation
* Goals: retrieval metrics (recall, MRR, context precision), answer metrics, faithfulness, latency; regression vs independent evaluation.
* Study: notebook **11**; `evaluation/runner.py`; `docs/EVALUATION.md`.
* Milestone: write an independent gold set (≥30 questions) for documents you have not used before and run it once.
* Ready when: you can say exactly what your numbers do and do not prove.

## Stage 7 — Financial analytics
* Goals: ratios, growth, period alignment, comparability, visualisation.
* Study: notebook **12**; `ratios.py`, `service.py`, `comparison.py`, `reporting.py`.
* Milestone: add a ratio (e.g. asset turnover) with tests and see it in the Financial Ratios page.
* Ready when: you can explain why FinRAG refuses to compute a ratio from `needs_review` inputs.

## Stage 8 — Fine-tuning
* Goals: SFT, LoRA, PEFT/TRL configuration, held-out evaluation, overfitting, why fine-tuning does not replace RAG.
* Study: notebook **13**; `fine_tuning/`; `docs/FINE_TUNING.md`.
* Milestone: build a fair few-shot baseline and compare it with the LoRA adapter on the held-out set.
* Ready when: you can interpret a training-loss curve against held-out accuracy.

## Stage 9 — NVIDIA and deployment
* Goals: CUDA detection, GPU memory planning, quantisation, NIM / TensorRT-LLM / NeMo roles, Docker, health checks, backups.
* Study: notebook **14**; `docs/NVIDIA.md`, `docs/DEPLOYMENT.md`, `docker-compose.yml`, `backend/Dockerfile.gpu`.
* Milestone: on a GPU machine (cloud or local), run notebook 14, register a NIM or TensorRT-LLM endpoint in Settings, and compare answer latency with the CPU model.
* Ready when: you can size a GPU for a given model and context length.

## Capstone ideas
1. Support a new document type (e.g. PowerPoint) end to end: validation, parser, tests, notebook.
2. Replace the cross-encoder reranker and measure the effect with an independent gold set.
3. Fine-tune a larger model on GPU with more human-verified data and evaluate it fairly.
