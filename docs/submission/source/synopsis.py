import sys
sys.path.insert(0, "/tmp/claude-0/sp/papers")
from docbuild import FIG, TITLE, Doc, references, university_cover

d = Doc(size=12)
university_cover(d, "PROJECT SYNOPSIS")
d.p("PROJECT SYNOPSIS", bold=True, align="center", size=14, after=4)
d.p(TITLE, bold=True, align="center", size=16, after=14)

d.h("1. Introduction", 1)
d.p("Financial information is published in many shapes: annual reports as digital or scanned PDF files, statements and "
    "schedules in Excel workbooks, ledgers and exports in CSV, and notes and disclosures in Word documents. Analysts spend a "
    "large share of their time locating figures, checking that they reconcile, aligning reporting periods and units, and "
    "building the same charts again for every company. General-purpose AI chatbots can summarise documents, but they are "
    "known to produce fluent answers containing numbers that do not appear in the source, to perform arithmetic incorrectly, "
    "and to cite nothing a reviewer can check [3].")
d.p("**FinRAG** is a working platform that turns uploaded financial documents into verified, structured data and an "
    "automatically generated interactive dashboard, and lets the user discuss that dashboard with an AI assistant whose every "
    "number is traceable to a printed value or to a deterministic calculation. It combines Retrieval-Augmented Generation (RAG) "
    "[1], [2] for text and disclosures with a relational store of financial facts for analytics.")

d.h("2. Problem Statement", 1)
d.p("Given an arbitrary set of financial documents in mixed formats, with no predefined company, template or year, the system "
    "must (a) extract text, tables and financial values with their exact source location; (b) identify the metric, period, basis "
    "(consolidated or standalone), unit and currency of each value; (c) validate values against accounting identities; (d) store "
    "original files, extracted facts and searchable chunks consistently; (e) generate meaningful KPIs and charts from whatever "
    "reliable data exists; and (f) answer questions with citations, without inventing figures, without letting the language "
    "model do arithmetic, and while keeping each user's data private.")

d.h("3. Objectives", 1)
d.bullets([
    "Build format-specific extraction for digital and scanned PDF, DOCX, XLSX, XLS and CSV that preserves page, table, sheet, "
    "cell and row references.",
    "Map printed labels to a canonical set of financial metrics without treating similar terms (e.g. EBIT and operating profit, "
    "profit after tax and profit for the year) as interchangeable.",
    "Validate extracted values with accounting identities (balance sheet, income statement, cash roll-forward, borrowings) and "
    "distinguish reported, calculated, inferred and failed values.",
    "Generate an interactive financial dashboard automatically, adapting to the metrics and periods actually available.",
    "Provide a dashboard-aware AI assistant that cites dashboard data, extracted values and document passages, computes "
    "calculations and what-if scenarios in Python, and withholds unsupported answers.",
    "Run entirely on local, open models on CPU hardware, with user-level isolation, audit logging and tests.",
])

d.h("4. Scope", 1)
d.p("In scope: upload and validation of the five formats; OCR of scanned pages; metadata detection; metric extraction and "
    "validation; PostgreSQL and Qdrant storage; RAG question answering; ratio and growth calculations; the automatic dashboard; "
    "the dashboard assistant; exports; authentication and role-based access; evaluation tooling; LoRA fine-tuning experiments. "
    "Out of scope: investment advice, forecasting beyond what documents state, currency conversion, and GPU deployment (designed "
    "for, but not available during development).")

d.h("5. Proposed System", 1)
d.figure(FIG + "architecture.png", "System architecture of FinRAG", 15.5)
d.p("A FastAPI service accepts uploads, validates file signatures and structure, stores originals under random names and "
    "queues a processing job. A background worker parses each file with a format-specific parser, applies OCR where a page has "
    "no text layer [12], detects metadata, extracts and validates financial values, stores them with their source references, "
    "and indexes format-aware chunks in a vector database. A dashboard service selects one trustworthy value per organisation, "
    "basis, metric and fiscal year, computes KPIs and ratios in Python, and chooses chart types from the shape of the data. The "
    "assistant answers from numbered sources and a verifier checks every citation and number before the answer is shown.")

d.h("6. Methodology / Modules", 1)
d.table(["Module", "Method"], [
    ["Upload & validation", "Extension allow-list, magic-byte checks, PDF/OOXML structure and macro checks, size and page limits, SHA-256 duplicate detection with a unique index."],
    ["Extraction", "PyMuPDF word geometry and table finder (PDF), Tesseract OCR, python-docx, openpyxl (formulas and cached values, merged cells, number formats), xlrd, csv/pandas with delimiter, encoding and decimal-comma detection."],
    ["Metric mapping", "Canonical metric catalogue with ordered label patterns and section-context rules; each value keeps its printed label and value."],
    ["Validation", "Deterministic accounting identities with tolerances; hard failures vs. soft mismatches; human verify/reject recorded in an audit log."],
    ["Retrieval (RAG)", "Hybrid dense (BGE embeddings [8]) and PostgreSQL full-text search, basis guard, cross-encoder reranking [9], structured value and calculation facts."],
    ["Analytics & dashboard", "Decimal arithmetic for ratios and growth on validated inputs only; cross-document de-duplication; chart planner (bar, line, area, pie, donut, waterfall, heatmap, treemap)."],
    ["Verification", "Cited source must exist; every number must occur in a cited source; the question's year must appear in cited sources; otherwise warn or withhold."],
    ["Fine-tuning", "LoRA [6] adapter for table-row-to-JSON extraction, evaluated against the base model on held-out documents."],
], caption="Modules and methods", widths=[4, 12])

d.h("7. Technology Stack", 1)
d.table(["Layer", "Technology"], [
    ["Backend", "Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic"],
    ["Storage", "PostgreSQL 16 (relational facts, JSONB metadata), Qdrant 1.20 (vectors), file storage"],
    ["Document processing", "PyMuPDF, Tesseract OCR, python-docx, openpyxl, xlrd, pandas"],
    ["AI models", "BGE-small-en-v1.5 embeddings (384-d), MiniLM cross-encoder reranker, Qwen3-4B (Q4_K_M) via llama.cpp [13]"],
    ["Fine-tuning", "PEFT LoRA, TRL, Qwen3-0.6B base"],
    ["Frontend", "Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts 3"],
    ["Deployment", "Docker Compose; optional NVIDIA NIM / GPU profile"],
], caption="Technology stack", widths=[4, 12])

d.h("8. Hardware and Software Requirements", 1)
d.bullets(["Development and evaluation hardware: 4 virtual CPUs, about 16 GB RAM, no GPU.",
           "Software: Linux, Python 3.13, Node.js 22, PostgreSQL 16, Qdrant, Tesseract, LibreOffice (test-file generation only).",
           "Client: any modern web browser."])

d.h("9. Outcomes Achieved", 1)
d.p("All results below were measured on the implemented system; synthetic test files are labelled as such and genuine "
    "documents are public annual reports.")
d.bullets([
    "Extraction consistency: 84 of 87 accounting-identity checks passed (96.5%) over 770 canonical values in 11 documents; 15 of 15 gold values correct on a genuine annual report.",
    "RAG on 8 gold questions: answer accuracy improved from 75.0% to 100% across stored regression runs, with 100% faithfulness (no unsupported numbers); retrieval hit rate 87.5%.",
    "LoRA fine-tuning on CPU: fully correct row-to-JSON outputs rose from 0.0% (base, zero-shot) to 69.3% on 127 held-out rows.",
    "End-to-end data-flow audit of 23 stages: 69 of 69 live checks; 12 defects found and fixed, including a cross-user access bypass.",
    "Product acceptance run against 15 criteria with genuine and synthetic documents and the real model: 48 of 48 checks passed.",
    "83 automated backend tests and a browser end-to-end test pass.",
])

d.h("10. Limitations and Future Work", 1)
d.bullets([
    "CPU inference takes about 1–2 minutes per answer; a GPU endpoint is the intended production setup.",
    "The 4-billion-parameter model occasionally reasons clumsily; verification checks numbers and citations, not reasoning.",
    "Evaluation sets are small; a larger independent gold set is the next step.",
    "Future work: GPU serving, more human-verified training data for the LoRA adapter, additional languages and reporting standards.",
])

d.h("References", 1)
references(d)
d.footer_page_numbers()
d.save("/tmp/claude-0/sp/papers/out/FinRAG_Project_Synopsis.docx")
print("synopsis ok")
