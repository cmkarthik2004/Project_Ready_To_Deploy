# FinRAG demonstration workflow

Use **your own** financial documents (an annual report PDF, a budget spreadsheet, an expense CSV, a
Word financial report…). FinRAG contains no sample data; every screen below is filled only by what
you upload.

1. **Start the stack** (`docker compose up -d --build`, or the development commands in the README) and
   open http://localhost:3000.
2. **Register.** The first account becomes `admin`. The **Overview** shows the genuine empty state:
   "No documents uploaded yet."
3. **Upload Documents** → drag several files of different formats onto the drop zone → *Upload and
   process*. Each file shows *accepted* or the exact rejection reason (wrong type, corrupted,
   password-protected PDF, macro-enabled workbook, duplicate…), then its live processing status.
4. **Document Library** → filter by format/status; download the original; reprocess; delete
   (removes the file, extracted data and vectors).
5. **Document Analysis** → pick a document:
   * detected metadata with method, confidence and evidence snippet; fields that could not be
     detected say so; *Correct metadata* to fix any field (recorded as user-corrected);
   * financial statements identified (type, consolidated/standalone, unit, columns, location);
   * extracted values: metric, value **as printed**, unit, column/period, basis, exact source
     location, validation status with notes; *verify* ✓ or *reject* ✗ a value (audited);
   * accounting checks that were run (left side, right side, difference, result);
   * tables, indexed chunks and the processing log with per-stage timings.
6. **AI Financial Chat** → select one or several documents (or none = all) and ask, for example:
   *What is the total revenue in this document?*, *Summarise the balance sheet.*, *Calculate the
   profit margin using the available figures.*, *What are the major financial risks mentioned?*,
   *Compare the financial information in these two files.* Each answer shows its status, cited
   sources (file + page / section / sheet+cell / row) with the evidence text, any Python calculations,
   and warnings if the model wrote a number that is not in the cited sources. Questions the documents
   cannot answer return "Sufficient evidence was not found".
7. **Financial Analytics** → choose metrics found in your documents; trend charts appear only when a
   metric has at least two periods in the same document/basis/unit. All values are listed in a table.
8. **Compare Documents** → select two or more files; read the compatibility warnings (currency, unit,
   basis, period type, organisation, possible restatements) before the side-by-side table and chart.
9. **Financial Ratios** → computed in Python with formula, inputs, source locations and validation
   status; tick "also show ratios that could not be computed" to see what inputs are missing.
10. **Reports** → generate a report (optionally with a cited AI summary) and download it as Markdown.
    The report ends with limitations and missing information.
11. **Evaluation** → run *Extraction consistency* immediately; upload a gold JSONL (see
    `docs/EVALUATION.md`) to measure extraction accuracy or RAG answer/citation/retrieval quality.
12. **AI Model & RAG Status** → live state of the LLM endpoint, Qdrant collection, embedding model,
    database, processing jobs, OCR and GPU (only reported if actually detected).
13. **Settings** → limits; (admin) register an NVIDIA NIM / vLLM / TensorRT-LLM endpoint, *Test* it,
    *Activate* it; manage user roles; read the audit log.
