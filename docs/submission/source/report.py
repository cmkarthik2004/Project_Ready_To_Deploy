import sys
sys.path.insert(0, "/tmp/claude-0/sp/papers")
from docbuild import FIG, SHOTS, TITLE, Doc, references, university_cover

d = Doc(size=12, line=1.3)

# ------------------------------------------------------------------ cover
university_cover(d, "PROJECT REPORT")

# ------------------------------------------------------------------ abstract + toc
d.h("Abstract", 1)
ABSTRACT = open("/tmp/claude-0/sp/papers/abstract.txt").read().strip()
d.p(ABSTRACT)
d.page_break()
import json, os
d.p("Table of Contents", bold=True, size=16, after=8)
TOCF = "/tmp/claude-0/sp/papers/report_toc.json"
d.toc_static(json.load(open(TOCF)) if os.path.exists(TOCF) else [])
d.page_break()

# ------------------------------------------------------------------ 1
d.h("1. Introduction", 1)
d.h("1.1 Background", 2)
d.p("Companies publish their financial performance in annual reports, quarterly results, investor presentations and "
    "supporting spreadsheets. The same figure can appear in a digital PDF statement, a scanned highlights page, an Excel "
    "workbook with several linked sheets and a Word note to the accounts. Before any analysis, an analyst must locate the "
    "figures, establish which reporting period, basis (consolidated or standalone), unit (thousand, million, crore) and "
    "currency they refer to, check that they reconcile, and only then compute ratios and build charts.")
d.p("Large language models (LLMs) make it tempting to ask questions of these documents directly. In practice, ungrounded "
    "generation produces plausible but unsupported statements [3], and arithmetic performed by the model is unreliable. "
    "Retrieval-Augmented Generation (RAG) [1], [2] reduces this risk by supplying retrieved passages, but text retrieval alone "
    "does not understand table structure, does not reconcile figures and cannot build a time series across documents.")
d.h("1.2 Motivation", 2)
d.p("The motivation for FinRAG is to give analysts the convenience of an AI assistant without giving up the traceability "
    "required in finance: every value on screen should lead back to the page, cell or row where it was printed, every "
    "calculation should be reproducible, and the system should say clearly when the evidence is insufficient.")
d.h("1.3 Problem Statement", 2)
d.p("Design and implement a system that accepts arbitrary financial documents in PDF (digital and scanned), DOCX, XLSX, XLS "
    "and CSV formats, extracts and validates financial data with full provenance, stores it as structured facts and searchable "
    "chunks, automatically generates an interactive analytics dashboard from the available data, and allows the user to discuss "
    "the documents and the dashboard with an AI assistant that never fabricates figures and never performs arithmetic itself.")
d.h("1.4 Objectives", 2)
d.bullets([
    "Format-specific extraction with page, table, sheet, cell-range and row references.",
    "Canonical metric mapping that keeps the original label and never merges distinct measures.",
    "Deterministic validation by accounting identities, with explicit statuses (validated, unvalidated, needs review, failed "
    "validation) and human verification.",
    "Consistent storage of originals, facts, chunks, vectors, validation results, dashboards and conversations, with safe "
    "deletion and reprocessing.",
    "An automatically generated, interactive dashboard that adapts to whatever reliable data is present.",
    "A dashboard-aware assistant with verified citations, Python calculations and clearly labelled hypothetical scenarios.",
    "Local, open-model operation on CPU hardware; security, testing and documentation suitable for deployment.",
])
d.h("1.5 Organisation of the Report", 2)
d.p("Chapter 2 surveys related work. Chapter 3 analyses requirements. Chapter 4 presents the system design, and Chapter 5 its "
    "implementation. Chapter 6 describes testing and evaluation, Chapter 7 the results with screenshots of the working system, "
    "Chapter 8 security, Chapter 9 deployment, and Chapter 10 limitations and future work. Chapter 11 concludes.")

# ------------------------------------------------------------------ 2
d.h("2. Literature Survey", 1)
d.h("2.1 Retrieval-Augmented Generation", 2)
d.p("Lewis et al. [1] introduced RAG, combining a parametric generator with a non-parametric retriever over a document index "
    "so that generated text can be grounded in retrieved passages. Gao et al. [2] survey the subsequent evolution into "
    "advanced and modular RAG, including query rewriting, hybrid retrieval, reranking and post-retrieval verification. FinRAG "
    "follows the modular approach: hybrid dense and lexical retrieval, reranking, structured facts added to the context, and a "
    "deterministic post-generation verifier.")
d.h("2.2 Retrieval and Ranking", 2)
d.p("Lexical ranking functions such as BM25 [10] remain strong for exact terms such as line-item names, while dense "
    "sentence embeddings [14] capture paraphrases. BGE embeddings [8] provide compact general-purpose dense representations. "
    "Cross-encoder rerankers, introduced for passage ranking by Nogueira and Cho [9], score query–passage pairs jointly and "
    "improve the precision of the top results. FinRAG uses PostgreSQL full-text search, BGE-small vectors in Qdrant and a "
    "MiniLM cross-encoder.")
d.h("2.3 Hallucination and Faithfulness", 2)
d.p("Ji et al. [3] categorise hallucinations into intrinsic and extrinsic errors and discuss mitigation through grounding "
    "and verification. RAGAS [11] proposes reference-free metrics such as faithfulness and context relevance. FinRAG measures "
    "faithfulness deterministically for numbers: each number in an answer must occur in a source the answer cites.")
d.h("2.4 Financial Question Answering", 2)
d.p("FinQA [4] and TAT-QA [5] show that questions over financial reports require combining tables and text and performing "
    "numerical reasoning, and that models make frequent arithmetic and table-reading mistakes. FinRAG therefore separates "
    "reading (extraction with provenance) from arithmetic (Python with Decimal precision) and from language generation.")
d.h("2.5 Document Processing and OCR", 2)
d.p("Scanned financial statements require optical character recognition. Tesseract [12] is a widely used open-source OCR "
    "engine. FinRAG applies it only to pages without a usable text layer and marks every OCR value for review.")
d.h("2.6 Parameter-Efficient Fine-Tuning", 2)
d.p("LoRA [6] adapts large models by training low-rank update matrices while freezing the original weights; QLoRA [7] extends "
    "this to quantised models. FinRAG uses LoRA to study whether a small open model (Qwen3 [13]) can learn the narrow task of "
    "turning a printed table row into canonical JSON.")
d.h("2.7 Gap Addressed", 2)
d.p("Existing approaches typically address either question answering over text or structured extraction. FinRAG combines "
    "both in one system with provenance, validation, cross-document de-duplication, an automatic dashboard and a conversational "
    "layer whose claims are mechanically checked.")

# ------------------------------------------------------------------ 3
d.h("3. Requirements Analysis", 1)
d.h("3.1 Functional Requirements", 2)
d.table(["ID", "Requirement"], [
    ["FR1", "Upload one or many files (PDF, DOCX, XLSX, XLS, CSV); validate type, structure and size; reject duplicates."],
    ["FR2", "Extract text, headings, tables, numbers, dates, units and currencies with source references."],
    ["FR3", "Detect organisation, reporting period, fiscal year, basis, unit and currency, or report “Not detected”."],
    ["FR4", "Map values to canonical metrics, keep printed labels, and validate with accounting identities."],
    ["FR5", "Store originals, facts, tables, chunks and vectors; support reprocessing and deletion."],
    ["FR6", "Answer questions with citations; refuse when evidence is insufficient."],
    ["FR7", "Compute ratios, margins and growth deterministically from trusted inputs."],
    ["FR8", "Generate an interactive dashboard with KPIs, charts, filters, drill-down and exports."],
    ["FR9", "Discuss the dashboard with an AI assistant, including hypothetical scenarios."],
    ["FR10", "Authentication, roles (viewer, analyst, admin), audit log, saved dashboards and conversation history."],
], caption="Functional requirements", widths=[1.6, 14])
d.h("3.2 Non-Functional Requirements", 2)
d.table(["Quality", "Requirement"], [
    ["Correctness", "No fabricated values; arithmetic only in Python; every displayed value traceable to its source."],
    ["Security", "User-level isolation for every role; parameterised queries; secrets in environment variables; prompt-injection handling."],
    ["Reliability", "Idempotent processing, safe retry, consistent deletion across files, database and vector store."],
    ["Performance", "Operates on 4 CPU cores and 16 GB RAM; prompts within an 8,192-token context window."],
    ["Usability", "Responsive interface, light and dark themes, colour-blind-safe palette, table views for charts."],
    ["Maintainability", "Typed code, migrations, automated tests, documentation and learning notebooks."],
], caption="Non-functional requirements", widths=[3, 13])
d.h("3.3 Hardware and Software", 2)
d.p("Development and all measurements used a Linux machine with 4 virtual CPUs, about 16 GB of RAM and no GPU. Software: "
    "Python 3.13, Node.js 22, PostgreSQL 16, Qdrant 1.20, Tesseract OCR, llama.cpp; LibreOffice was used only to generate test "
    "workbooks with cached formula values.")

# ------------------------------------------------------------------ 4
d.h("4. System Design", 1)
d.h("4.1 Architecture", 2)
d.figure(FIG + "architecture.png", "Overall architecture", 15.5)
d.p("The browser talks to a Next.js server that proxies API calls to FastAPI. Uploads are stored as files and recorded in "
    "PostgreSQL together with a processing job. A worker claims jobs with row-level locking (SELECT … FOR UPDATE SKIP LOCKED) "
    "so several workers can run safely. Facts and chunks go to PostgreSQL, vectors to Qdrant. The analytics service, the RAG "
    "pipeline and the local LLM serve the dashboard and the assistant.")
d.h("4.2 Ingestion Pipeline", 2)
d.figure(FIG + "pipeline.png", "Document ingestion stages", 16)
d.p("Each stage is logged with its duration. If any stage fails, derived rows are deleted and committed independently of the "
    "vector store, counts are reset, and the error is recorded, so a failed document never carries stale or partial data. "
    "Reprocessing deletes and rebuilds all derived data, which makes it idempotent.")
d.h("4.3 Data Model", 2)
d.table(["Table", "Purpose"], [
    ["users, audit_logs", "Accounts, roles and an audit trail of security-relevant actions"],
    ["documents, processing_jobs", "Uploaded files (hash, format, detected metadata, parser structure) and their jobs"],
    ["document_tables, document_chunks", "Extracted tables and format-aware text chunks (embedded in Qdrant)"],
    ["financial_statements, financial_metrics", "Structured facts: printed label and value, normalised value, unit, currency, period, fiscal year, basis, origin, validation status"],
    ["source_references", "Exact location of each fact: page/bbox, sheet/cell, table/row, CSV row"],
    ["financial_calculations", "Persisted ratio results with formula and inputs"],
    ["organisations, collections", "Detected organisations and user-defined document groups"],
    ["dashboards", "Saved dashboard filters and layout (data recomputed on load)"],
    ["chat_sessions, chat_messages", "Conversations with citations, evidence and verification record"],
    ["model_configurations, evaluation_runs", "Configurable model endpoints and stored evaluation results"],
], caption="Main database tables (17 in total)", widths=[5.5, 10.5])
d.p("Raw information (printed label and value, location, snippet) is stored separately from normalised information "
    "(canonical metric key, Decimal value, normalised value). Calculated values are never written into the facts table, and "
    "source values are never overwritten by inferred or calculated values.")
d.h("4.4 Question Answering Flow", 2)
d.figure(FIG + "qa_flow.png", "Question answering with verification", 15.5)
d.p("Sources are numbered by kind: [S] document passages, [M] extracted values, [C] Python calculations, [D] dashboard data "
    "and [H] hypothetical scenarios. The model must cite them inline. The verifier then decides whether the answer is shown as "
    "answered, shown with warnings listing unsupported numbers, or withheld.")

# ------------------------------------------------------------------ 5
d.h("5. Implementation", 1)
d.h("5.1 Upload and Validation", 2)
d.p("Files are checked against an extension allow-list and their magic bytes. PDFs must open, must not be encrypted, must stay "
    "within a page limit and must not contain launch actions; OOXML files are checked for required parts, macros and "
    "zip-bomb ratios; CSV files must decode as text without NUL bytes. Originals are stored under random names, and a unique "
    "index on (owner, SHA-256) rejects duplicates even when two uploads arrive at the same time.")
d.h("5.2 Format-Specific Extraction", 2)
d.table(["Format", "Strategy"], [
    ["PDF (digital)", "Word geometry from PyMuPDF; ruled-table detection; text-aligned tables whose amounts are assigned to the nearest period column; two-page spreads split; running headers kept as context; column headers carried to continuation pages when the columns align."],
    ["PDF (scanned)", "Tesseract OCR on pages without a text layer; OCR values flagged for review."],
    ["XLSX", "Every sheet; formulas and cached values; several tables per sheet; merged group headers and two-row headers; percentage and currency formats; total rows; cross-sheet references recorded and link cells treated as copies."],
    ["XLS", "Values via xlrd (formulas unavailable in the legacy format, reported)."],
    ["CSV", "Encoding detection, consistent-delimiter detection, decimal comma, comment lines, ragged rows; column profile, missing values and duplicate rows; Python-computed totals for record tables."],
    ["DOCX", "Headings, paragraphs and tables with table and row references."],
], caption="Extraction strategies", widths=[3, 13])
d.h("5.3 Metric Mapping and Validation", 2)
d.p("A catalogue of 54 canonical metrics defines ordered label patterns and, where needed, section rules (for example, "
    "a bare “Borrowings” row is current or non-current depending on its section; such mappings are marked as inferred). EBIT, "
    "operating profit, profit after tax, profit for the year, cash generated from operations and net cash from operating "
    "activities are kept distinct. Validation applies identities such as total assets = equity + liabilities, profit before tax "
    "= profit after tax + tax, gross profit = revenue − cost of revenue, closing cash = opening cash + net change, and total "
    "borrowings = current + non-current borrowings. Hard failures mark values as failed validation; soft mismatches mark them "
    "for review. Only a person can mark a value verified or rejected.")
d.h("5.4 Retrieval-Augmented Generation", 2)
d.p("Questions are scoped to the user's processed documents. Dense search in Qdrant is filtered by owner and document, "
    "combined with PostgreSQL full-text search, filtered by the basis and period named in the question, and reranked. "
    "Relevant extracted values and Python calculations are added as structured facts. The local Qwen3-4B model, served by "
    "llama.cpp with an OpenAI-compatible interface, receives a system prompt that forbids arithmetic and uncited claims.")
d.h("5.5 Automatic Dashboard", 2)
d.p("The dashboard service selects one fact per organisation, basis, metric and fiscal year across all documents, preferring "
    "verified and validated values, then the most recent report (restated comparatives), then confidence. Alternatives are "
    "kept and differences flagged, so a figure repeated in two reports is never counted twice. Values are expressed in one "
    "display unit per organisation and currencies are never converted. KPIs are produced only for metrics that exist; "
    "calculated KPIs (growth, margins, debt-to-equity) use validated or verified inputs only, and the rest are listed as "
    "pending verification instead of appearing as empty cards. A chart planner chooses trends for multi-year data, "
    "composition charts only for non-negative parts that reconcile to their total, a cash-reconciliation waterfall, an "
    "expense treemap and a growth heatmap.")
d.h("5.6 Dashboard-Aware Assistant", 2)
d.p("For a dashboard question the server rebuilds the dashboard from the user's filters (browser data is never trusted) and "
    "presents KPIs and chart data as [D] sources, including year-over-year changes computed in Python. Questions such as "
    "“What happens if revenue grows by 10%?” are answered by a Python scenario labelled as a hypothetical assumption [H]. "
    "Explanations of disclosures come from document passages [S]. Conversations are stored with their citations.")
d.h("5.7 LoRA Fine-Tuning", 2)
d.p("A LoRA adapter (rank 16, alpha 32) was trained on Qwen3-0.6B with PEFT and TRL to convert a printed table row into "
    "canonical JSON or abstain. Training data were taken only from values that passed an accounting identity, split by "
    "document so that test documents were never seen in training.")

# ------------------------------------------------------------------ 6
d.h("6. Testing and Evaluation", 1)
d.h("6.1 Automated Tests", 2)
d.p("The backend has 83 automated tests covering file validation, number parsing, each parser, workbook structure, CSV "
    "profiling, multi-page PDF tables, metric definitions, reconciliation checks, ratios, the dashboard service, the "
    "assistant's plumbing and verification (with a scripted model), API flows, user isolation, deletion and failure recovery. "
    "A browser end-to-end test registers a user, uploads a genuine statement, waits for processing and asks a question.")
d.h("6.2 End-to-End Data-Flow Audit", 2)
d.p("A 23-stage trace from upload to the displayed answer was audited live. Two fresh users uploaded new files in all five "
    "formats; the audit verified storage, job stages, database-to-vector consistency, citations against original files, "
    "isolation, deletion, failure and retry with the vector database stopped, and reprocessing idempotency. The final run "
    "passed 69 of 69 checks after 12 defects were fixed, including an administrator cross-user access path and stale data on "
    "failed jobs.")
d.h("6.3 Extraction and RAG Evaluation", 2)
d.table(["Measure", "Result"], [
    ["Accounting identities over 770 canonical values (11 documents)", "84 / 87 passed (96.5%)"],
    ["Gold extracted values (genuine annual report)", "15 / 15 correct"],
    ["RAG answer accuracy, 8 gold questions (runs 1, 2, 4, 5)", "75.0% → 87.5% → 100% → 100%"],
    ["Faithfulness (no unsupported numbers), same runs", "100%"],
    ["Retrieval hit rate / MRR (top-5, page-level)", "87.5% / 0.338"],
    ["Median answer latency (CPU)", "55–68 s"],
], caption="Extraction and RAG results", widths=[11, 5])
d.figure(FIG + "rag_runs.png", "RAG answer accuracy across stored regression runs", 11)
d.p("The runs are a regression check on a small gold set, not an independent benchmark: changes between runs were motivated "
    "by earlier failures. The most instructive failures were faithful but wrong answers — a number that appeared in the cited "
    "source but belonged to a different line item or basis — which led to label-aware facts and a basis guard.")
d.h("6.4 Fine-Tuning Evaluation", 2)
d.table(["Metric (127 held-out rows)", "Base", "LoRA"], [
    ["Output matches JSON schema", "0.0%", "100.0%"], ["Metric key correct", "0.0%", "69.3%"],
    ["All (period, value) pairs exact", "0.0%", "77.2%"], ["Fully correct", "0.0%", "69.3%"],
    ["Mean latency per row (CPU)", "16.5 s", "6.7 s"],
], caption="LoRA results (train 49 examples, 583 s on CPU)", widths=[9, 3, 3])
d.figure(FIG + "lora.png", "Base model vs. LoRA adapter", 11)
d.p("The zero-shot baseline did not receive the list of canonical keys, so the comparison shows the value of task adaptation "
    "rather than a lack of financial knowledge. The adapter sometimes invents non-canonical keys; it is therefore kept as a "
    "research component and not used in the production extraction path.")
d.h("6.5 Product Acceptance Testing", 2)
d.p("Fifteen acceptance criteria were tested live by a fresh user uploading nine files: three genuine documents (two "
    "consecutive integrated annual reports and an image-only highlights page) and six clearly labelled synthetic files with "
    "known ground truth (a multi-sheet workbook in USD million with formulas, a semicolon-delimited Windows-1252 CSV with "
    "decimal commas, duplicates and a missing amount, a Word note, a five-year CSV in INR crore, a deliberately inconsistent "
    "workbook and a scanned statement). The final run passed 48 of 48 checks; earlier runs (43/47 and 46/47) exposed issues "
    "that were fixed.")
d.table(["#", "Criterion", "Evidence (final run)"], [
    ["1", "Correct figures", "Every ground-truth value in the workbook extracted exactly once; genuine revenue 9,80,136 crore and total assets 19,50,121 crore; OCR values correct"],
    ["2", "Source references", "All sampled values found at their cited page/cell/row in the original files"],
    ["3", "Financial years", "“2024-25”, “As at 31 March 2031” and “FY2031” mapped correctly"],
    ["4", "Units and currencies", "USD, EUR and INR; million, crore and thousand; normalised values correct; decimal commas"],
    ["5", "Ratios", "Net margin 16.6008%, growth 10.0000%, gross margin 39.9209%, debt-to-equity 0.4952 from validated inputs"],
    ["6", "Reconciliation errors", "Unbalanced balance sheet and broken cash roll-forward detected and marked failed"],
    ["7–8", "Dashboard and charts", "KPIs and 8 chart families generated automatically; waterfall 150 → 190 reconciles"],
    ["9–10", "Missing data", "Dashboards built without optional metrics; no KPI for absent metrics; failed values never shown"],
    ["11–12", "Dashboard conversation", "Chart and calculation questions answered with citations; scenario 1,391.5 labelled hypothetical; future-period question withheld"],
    ["13", "No double counting", "Repeated comparatives across two genuine reports and across workbook and Word note counted once"],
    ["14", "Deletion", "Deleting a document removed its vectors and its data from the dashboard"],
    ["15", "Hardware limits", "Largest prompt 4,377 tokens of 8,192; answers 34–105 s on 4 CPUs"],
], caption="Acceptance results", widths=[1.2, 3.5, 11.3], size=11)

# ------------------------------------------------------------------ 7
d.h("7. Results and Screenshots", 1)
d.p("The following screenshots show the working system after the final acceptance run.")
d.figure(SHOTS + "dashboard_light.jpg", "Automatically generated dashboard for one organisation (light theme)", 15.5)
d.figure(SHOTS + "drilldown_kpi.jpg", "Drill-down from a calculated KPI to its formula and the cell of each input", 15.5)
d.figure(SHOTS + "assistant_chart_question.jpg", "Assistant explaining a chart with citations to workbook cells and dashboard data", 15.5)
d.figure(SHOTS + "dashboard_dark.jpg", "Dark theme with a separately validated colour palette", 15.5)
d.figure(SHOTS + "dashboard_genuine_reports.jpg", "Dashboard built from two genuine annual reports", 15.5)
d.h("7.1 Discussion", 2)
d.p("Three observations stand out. First, faithfulness is not correctness: a model can cite a source that really contains "
    "the number it quotes and still answer the wrong question, so line-item labels, basis and period must be part of the "
    "retrieved facts. Second, separating arithmetic from language generation removes an entire class of errors and makes "
    "every calculation auditable. Third, testing with real documents repeatedly found defects that unit tests on synthetic "
    "inputs did not, such as CSV rows silently dropped after a title line and unit statements that were not recognised.")

# ------------------------------------------------------------------ 8
d.h("8. Security", 1)
d.bullets([
    "Authentication with Argon2id password hashing and JWT access tokens; roles viewer, analyst and admin; every query filtered by owner, for every role.",
    "Vector searches filtered by owner and document; every hit re-checked against the database.",
    "Upload validation against malicious documents; size, page and cell limits; random stored names.",
    "Document text presented to the model as quoted data; instruction-like text flagged; chat-template tokens stripped.",
    "Secrets only in environment variables; parameterised queries through SQLAlchemy; rate limits; security headers.",
    "Audit log of logins, uploads, deletions, corrections, verifications, exports and questions; backup and restore scripts.",
    "Internal services bound to localhost in the Docker deployment; only the web front end is exposed.",
])

# ------------------------------------------------------------------ 9
d.h("9. Deployment", 1)
d.p("The system is packaged with Docker Compose: PostgreSQL, Qdrant, the llama.cpp model server, the API, the worker and the "
    "web front end. Database schema changes are managed with Alembic migrations. An optional profile targets NVIDIA NIM for "
    "GPU inference; GPU paths were designed but not measured, because no GPU was available.")

# ------------------------------------------------------------------ 10
d.h("10. Limitations and Future Work", 1)
d.bullets([
    "Latency: about 1–2 minutes per answer on CPU; GPU serving is the intended production configuration.",
    "Model reasoning: the 4-billion-parameter model can repeat itself or compare values clumsily; verification checks numbers and citations, not reasoning.",
    "Evaluation size: gold sets are small; an independent and larger benchmark is the next step.",
    "Calculations wait for validated or human-verified inputs, so some ratios are pending until a user verifies values.",
    "Future work: GPU deployment, more human-verified data for the LoRA adapter, additional reporting standards and languages, and scheduled ingestion from data sources.",
])

# ------------------------------------------------------------------ 11
d.h("11. Conclusion", 1)
d.p("FinRAG demonstrates that an AI-assisted financial analysis platform can be both convenient and verifiable. By combining "
    "format-aware extraction with provenance, deterministic validation and arithmetic, a de-duplicated fact store, an "
    "automatically planned dashboard and a conversational layer whose citations and numbers are mechanically checked, the "
    "system turns heterogeneous financial documents into analysis a reviewer can trust and audit. All components run on "
    "local, open models and commodity CPU hardware, and the results reported here were measured on the implemented system.")

d.h("References", 1)
references(d)

d.h("Appendix A: Main API Endpoints", 1)
d.table(["Method and path", "Purpose"], [
    ["POST /api/auth/register, /login", "Create an account, sign in"],
    ["POST /api/documents", "Upload one or more files"],
    ["GET /api/documents/{id}, /chunks, /tables, /metrics, /file", "Document details, extracted content, original file"],
    ["PATCH /api/documents/{id}/metadata", "Correct detected metadata (audited)"],
    ["POST /api/documents/{id}/reprocess; DELETE /api/documents/{id}", "Reprocess or delete consistently"],
    ["POST /api/metrics/{id}/verify, /reject", "Human verification"],
    ["POST /api/dashboard/build, /dashboard/export.md", "Automatic dashboard and export"],
    ["GET/POST/PUT/DELETE /api/dashboards", "Saved dashboard views"],
    ["POST /api/dashboard/chat", "Dashboard-aware assistant"],
    ["POST /api/chat/sessions/{id}/messages", "Document question answering"],
    ["POST /api/analytics/ratios, /compare, /series", "Ratios, comparison and series"],
    ["POST /api/evaluations", "Run evaluations"],
], caption="Selected endpoints (58 in total)", widths=[7.5, 8.5], size=11)

d.footer_page_numbers()
d.save("/tmp/claude-0/sp/papers/out/FinRAG_Project_Report.docx")
json.dump([[lv, t] for lv, t in d.headings if lv <= 2], open("/tmp/claude-0/sp/papers/report_headings.json", "w"))
print("report ok")
