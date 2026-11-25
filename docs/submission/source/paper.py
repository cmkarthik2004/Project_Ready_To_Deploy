import sys
sys.path.insert(0, "/tmp/claude-0/sp/papers")
from docbuild import FIG, TITLE, Doc, references

d = Doc(size=10, margins_cm=1.9, line=1.05)
d.p(TITLE, bold=True, align="center", size=18, after=10)
d.p("Research paper · November 2026", italic=True, align="center", size=10, after=10)
abstract = open("/tmp/claude-0/sp/papers/abstract.txt").read().strip()
d.p("**Abstract—**" + abstract, size=9.5)
d.p("**Index Terms—**retrieval-augmented generation, financial document analysis, information extraction, hallucination "
    "mitigation, verification, OCR, LoRA, analytics dashboards.", size=9.5, after=8)
d.columns(2)

d.h("I. Introduction", 2)
d.p("Financial statements are among the most consequential documents an organisation publishes, yet the same figure may be "
    "printed in a digital PDF, a scanned highlights page, a workbook with linked sheets and a Word note. Question-answering "
    "systems built on large language models (LLMs) promise faster analysis but introduce two risks that are unacceptable in "
    "finance: unsupported statements [3] and unreliable arithmetic [4], [5]. Retrieval-augmented generation (RAG) [1], [2] "
    "grounds answers in retrieved passages, but passage retrieval alone does not reconcile figures, align periods or build a "
    "multi-year view.")
d.p("We present FinRAG, an implemented platform that treats financial analysis as a data problem first and a language "
    "problem second. Our contributions are: (1) a format-aware extraction pipeline that keeps provenance for every value; "
    "(2) deterministic validation and a fact model that separates reported, inferred and calculated values; (3) a "
    "cross-document fact selection that prevents double counting and drives an automatically planned dashboard; (4) a "
    "verified conversational layer with typed sources and Python-computed scenarios; and (5) an evaluation on genuine annual "
    "reports and labelled synthetic edge cases, including the failures that shaped the design.")

d.h("II. Related Work", 2)
d.p("RAG was introduced by Lewis et al. [1]; Gao et al. [2] survey modular extensions such as hybrid retrieval, reranking and "
    "post-generation checks. Lexical ranking (BM25 [10]) and dense embeddings [8], [14] are complementary, and cross-encoders "
    "improve top-k precision [9]. Ji et al. [3] review hallucination, and RAGAS [11] proposes faithfulness metrics. FinQA [4] "
    "and TAT-QA [5] show that financial QA needs hybrid table–text reasoning and that numerical errors are common. Tesseract "
    "[12] is the OCR engine used for scanned pages. LoRA [6] and QLoRA [7] enable parameter-efficient adaptation of open models "
    "such as Qwen3 [13]. FinRAG differs from these lines of work by integrating extraction with provenance, accounting "
    "validation, cross-document de-duplication, automatic visual analytics and mechanically verified dialogue in one system.")

d.h("III. System Architecture", 2)
d.figure(FIG + "architecture.png", "FinRAG architecture.", 8.3)
d.p("A FastAPI service validates uploads and queues jobs in PostgreSQL; a worker parses, extracts, validates, chunks and "
    "embeds each document; facts are stored relationally and chunks in Qdrant. A dashboard service and a RAG pipeline feed a "
    "local Qwen3-4B model served by llama.cpp. Every query is filtered by owner, for every role.")

d.h("IV. Methods", 2)
d.h("A. Format-aware extraction", 3)
d.p("PDF pages are processed from word geometry: lines ending in amounts become table rows, and amounts are assigned to the "
    "nearest period column; column headers are carried to a continuation page only if its amounts align with them. Pages "
    "without a text layer are OCR'd and their values flagged for review. Workbooks are read with both formulas and cached "
    "values; several tables per sheet, merged and two-row headers, percentage and currency formats, total rows and "
    "cross-sheet references are recovered, and cells that merely reference another cell are treated as copies. CSV parsing "
    "detects encoding, a consistently used delimiter and decimal commas, and reports column types, missing values and "
    "duplicate rows.")
d.h("B. Fact model and validation", 3)
d.p("Each fact stores the printed label and value, a Decimal value, unit, normalised value, currency, period label, fiscal "
    "year, basis, statement type, origin (reported or inferred mapping), confidence and location. A catalogue of 54 canonical "
    "metrics keeps distinct measures apart (e.g. EBIT vs. operating profit; profit after tax vs. profit for the year). "
    "Identities — assets = equity + liabilities, PBT = PAT + tax, gross profit = revenue − COGS, closing cash = opening cash + "
    "net change, borrowings total = current + non-current, and others — mark values as validated, needs review (soft "
    "mismatch) or failed validation (hard failure). Only a person can verify or reject a value.")
d.h("C. Cross-document fact selection", 3)
d.p("For analytics, FinRAG selects one fact per (organisation, basis, metric, fiscal year), preferring verified/validated "
    "values, then the most recent report, then confidence. Alternatives are retained and differing values flagged as "
    "restatements or conflicts. Values are expressed in one display unit per organisation; currencies are never converted; "
    "a document's unstated basis is inherited only when the document is unambiguous.")
d.h("D. Calculations and dashboard planning", 3)
d.p("Ratios, margins and growth are computed in Python with Decimal arithmetic and only from validated or verified inputs; "
    "otherwise they are reported as pending verification. A planner selects chart types from the data's shape: trends for "
    "two or more years, composition charts only for non-negative parts that reconcile to a printed total, a cash "
    "reconciliation waterfall, an expense treemap and a diverging growth heatmap.")
d.h("E. Verified dialogue", 3)
d.figure(FIG + "qa_flow.png", "Typed sources and verification.", 8.3)
d.p("Sources are typed: passages [S], extracted values [M], calculations [C], dashboard data [D] and hypothetical scenarios "
    "[H]. The dashboard is rebuilt on the server for each question. The verifier withholds answers without valid citations, "
    "with citations to sources that were not provided, or whose cited sources do not mention the period asked about, and "
    "lists numbers that do not occur in any cited source.")

d.h("V. Experimental Setup", 2)
d.p("All measurements used 4 vCPUs, about 16 GB RAM and no GPU; the LLM was Qwen3-4B (Q4_K_M) with an 8,192-token context. "
    "Genuine inputs were publicly available integrated annual reports of one listed company (two consecutive years, plus a "
    "later year and an image-only highlights page). Synthetic inputs, labelled as such, provided known ground truth for "
    "formats and edge cases (multi-sheet workbook with formulas, European-format CSV with duplicates and gaps, Word note, "
    "five-year summary, inconsistent statements, scanned statement).")

d.h("VI. Results", 2)
d.table(["Experiment", "Result"], [
    ["Identity checks (770 values, 11 docs)", "84/87 (96.5%)"],
    ["Gold extracted values", "15/15"],
    ["RAG accuracy, 8 questions (runs 1→5)", "75.0% → 100%"],
    ["Faithfulness (same runs)", "100%"],
    ["Retrieval hit rate / MRR", "87.5% / 0.338"],
    ["LoRA fully correct (127 rows)", "0.0% → 69.3%"],
    ["Data-flow audit (23 stages)", "69/69 checks"],
    ["Product acceptance (15 criteria)", "48/48 checks"],
    ["Largest dashboard prompt", "4,377 tokens"],
    ["Answer latency (CPU)", "34–105 s"],
], caption="Summary of measured results", widths=[5.2, 3.0], size=9)
d.table(["Identity (11 documents)", "Passed"], [
    ["Assets = equity and liabilities (two forms)", "16/16"], ["Assets = current + non-current", "10/10"],
    ["Liabilities = current + non-current", "10/10"], ["Equity = share capital + other equity", "10/10"],
    ["Total income = revenue + other income", "16/16"], ["Net profit = owners + NCI", "4/4"],
    ["PBT = income − expenses (soft)", "15/16"], ["PAT = PBT − taxes (soft)", "2/4"],
], caption="Accounting-identity checks on extracted values", widths=[6.2, 2.0], size=9)
d.p("The three soft mismatches occur on highlights tables that print two currencies or units under one year header; FinRAG "
    "marks those values for review instead of guessing which sub-column applies.")
d.p("RAG accuracy rose from 75.0% (run 1) to 87.5% (run 2) and 100% (runs 4 and 5); run 3 was invalid because the model "
    "server was terminated by the operating system's out-of-memory killer, and FinRAG returned explicit errors rather than "
    "answers. Because later runs reuse the same eight questions, they are a regression check, not an independent benchmark.")
d.figure(FIG + "lora.png", "LoRA vs. base model on held-out rows.", 8.3)
d.p("The LoRA adapter (rank 16, 10.09 M trainable parameters, 49 training examples, 583 s on CPU) produced schema-valid output "
    "for every row and fully correct output for 69.3%, but sometimes invented non-canonical keys; it is therefore not used in "
    "the production path. In the acceptance run, the dashboard assistant answered chart, calculation and explanation "
    "questions with valid citations, labelled a 10% revenue scenario (1,391.5) as hypothetical, and withheld an answer about a "
    "period absent from the documents. Repeated comparative figures across two genuine reports were counted once.")

d.table(["Acceptance criterion", "Outcome"], [
    ["Correct figures (ground truth, genuine, OCR)", "pass"], ["Source references reopened in originals", "pass"],
    ["Fiscal-year mapping", "pass"], ["Units and currencies (USD, EUR, INR)", "pass"],
    ["Ratios vs. independent arithmetic", "pass"], ["Reconciliation errors detected", "pass"],
    ["Dashboard and chart selection", "pass"], ["No blocking on missing metrics", "pass"],
    ["No fabricated values", "pass"], ["Chart and calculation questions", "pass"],
    ["No double counting across documents", "pass"], ["Consistent deletion", "pass"],
    ["Context and hardware limits", "pass"],
], caption="Product acceptance (final run, 48/48 checks)", widths=[6.2, 2.0], size=9)

d.h("VII. Discussion", 2)
d.p("**Faithful is not correct.** The first RAG failures quoted numbers that did exist in the cited source but belonged to a "
    "different line item (profit after tax instead of profit for the year) or basis (standalone instead of consolidated). "
    "Supplying labelled facts and filtering by basis fixed them; faithfulness metrics alone would not have detected them. "
    "**Arithmetic belongs outside the model.** When a derived total was withheld, the model added two figures itself and "
    "cited a source that did not exist; the verifier now withholds such answers, and the missing calculation is stated "
    "explicitly. **Real documents find real bugs.** Acceptance testing exposed defects that unit tests missed: CSV rows "
    "silently dropped after a title line, unrecognised unit statements, link cells counted as new figures, and a verifier "
    "false positive (15 vs. 15.0000).")

d.h("VIII. Limitations", 2)
d.p("Evaluation sets are small and drawn from a limited set of genuine documents; CPU latency is high; a 4-billion-parameter "
    "model occasionally reasons clumsily, which number-and-citation verification does not catch; and calculations wait for "
    "validated or human-verified inputs, which leaves some ratios pending. GPU serving was designed but not measured.")

d.h("IX. Conclusion", 2)
d.p("FinRAG shows that combining provenance-preserving extraction, deterministic validation and arithmetic, cross-document "
    "de-duplication and mechanically verified dialogue yields an AI-assisted financial analysis system whose outputs can be "
    "audited, while running on open models and commodity hardware. Future work includes a larger independent benchmark, GPU "
    "deployment and human-verified data to improve the fine-tuned extractor.")

d.h("References", 2)
references(d)
d.footer_page_numbers()
d.save("/tmp/claude-0/sp/papers/out/FinRAG_Research_Paper.docx")
print("paper ok")
