# Project submission text

## Project Title

FinRAG: AI-Powered Financial Data Analytics Using RAG and Dashboard Generation

## Project Abstract

Financial information is spread across PDF annual reports (digital and scanned), Excel workbooks, CSV exports and Word notes, and analysts spend considerable effort locating figures, reconciling them and building the same analyses repeatedly. General-purpose AI chatbots can summarise such documents but may produce numbers that do not appear in the source, perform arithmetic incorrectly and give answers that cannot be audited. This project presents FinRAG, a working platform that combines retrieval-augmented generation with a structured store of validated financial facts. Format-specific parsers extract text, tables and values while preserving page, sheet, cell and row references; a canonical metric catalogue maps printed labels without merging distinct measures; and deterministic accounting identities validate the extracted values. From these facts, FinRAG automatically generates an interactive dashboard of KPIs and charts chosen from the data that is actually available, counting figures repeated across reports only once. A dashboard-aware AI assistant answers questions using numbered sources — document passages, extracted values, dashboard data and Python calculations — and a verifier checks that every citation exists and every number occurs in a cited source, withholding unsupported answers. All arithmetic, including what-if scenarios, is done in Python. The system runs on local open models (Qwen3-4B via llama.cpp) on a 4-CPU machine without a GPU. On genuine annual reports and labelled synthetic edge cases, it passed 96.5% of accounting-identity checks, extracted 15 of 15 gold values, answered all 8 gold questions correctly with no unsupported numbers after iterative fixes, and passed 48 of 48 product acceptance checks.

## Files to upload

| Form field | File |
|---|---|
| Project Synopsis | FinRAG_Project_Synopsis.pdf |
| Project Report | FinRAG_Project_Report.pdf |
| Research Paper | FinRAG_Research_Paper.pdf |

Editable Word versions (.docx) are alongside. All results quoted are measured values from docs/EVALUATION.md, docs/FINE_TUNING.md, docs/END_TO_END_DATA_FLOW_AUDIT.md and docs/ACCEPTANCE_TESTS.md.
