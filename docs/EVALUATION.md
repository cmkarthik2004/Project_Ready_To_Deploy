# Evaluation

FinRAG shows evaluation numbers **only after an evaluation has actually been executed**. Every run is
stored in the `evaluation_runs` table with its method, dataset, model information and per-item
details, and appears on the **Evaluation** page. Runs are started from that page or with
`POST /api/evaluations`.

## Evaluation types

| Kind | Needs | Measures |
|---|---|---|
| `extraction` | nothing (selected documents) | Internal consistency: accounting identities over the extracted values, per check type; validation-status distribution; share of values covered by a check. **Not** agreement with a human gold standard. |
| `extraction_gold` | gold JSONL | Extracted value equals the expected value (Decimal comparison) for each gold item. |
| `rag` | gold JSONL | Answer accuracy (all expected numbers in the answer), citation correctness (a cited source contains the expected numbers), retrieval hit rate (expected page/sheet/row among retrieved evidence), faithfulness (no unsupported numbers), insufficient-evidence rate, latency (mean / p50 / max). |
| `finetune` | produced by `app.fine_tuning.evaluate_lora` | Base vs. LoRA on held-out rows: JSON validity, metric-key accuracy, exact value accuracy, abstention accuracy, latency. |

### Gold file formats (one JSON object per line)
```jsonc
// extraction_gold
{"document_filename": "my-report.pdf", "metric_key": "total_assets", "period_contains": "2025",
 "expected_value": "1950121", "basis": "consolidated"}          // or "document_id": "<uuid>"
// rag
{"question": "What were total assets at year end?", "document_filenames": ["my-report.pdf"],
 "expected_numbers": ["19,50,121"], "expected_location": {"page": 99}}   // or {"sheet": "..."} / {"row": 12}
```
Create gold items from your own documents by reading the value and its location in the original
file. The gold files used below are in `docs/evaluation/`.

## Results measured in development

**Documents used:** genuine, publicly available annual reports downloaded from the issuer's official
investor-relations website (Integrated Annual Reports FY2023-24 and FY2024-25, 159 and 146 PDF pages),
plus DOCX/XLSX/XLS/CSV files *transcribed* from two statement pages of the FY2024-25 report by
`tests/fixtures/build_derived_fixtures.py`, and a one-page financial-highlights PDF. They were used
only as test inputs in a development database — they are not shipped with FinRAG and are not
referenced by application code. Hardware: 4 vCPU, 15 GB RAM, no GPU.

### 1. Extraction consistency (`extraction`, 11 documents, 770 canonical values)

| Check | Run | Passed | Pass rate |
|---|---:|---:|---:|
| Total assets = Total equity and liabilities | 8 | 8 | 100% |
| Total assets = Total equity + Total liabilities | 8 | 8 | 100% |
| Total assets = Current + Non-current assets | 10 | 10 | 100% |
| Total liabilities = Current + Non-current liabilities | 10 | 10 | 100% |
| Total equity = Share capital + Other equity (+ NCI) | 10 | 10 | 100% |
| Total income = Revenue from operations + Other income | 16 | 16 | 100% |
| Net profit = Owners + NCI | 4 | 4 | 100% |
| PBT = Total income − Total expenses (soft) | 16 | 15 | 93.8% |
| PAT = PBT − Current tax − Deferred tax (soft) | 4 | 2 | 50.0% |
| **All accounting identities** | **87** | **84** | **96.5%** |
| Spreadsheet "Total row = sum of rows above" (heuristic) | 36 | 15 | 41.7% |

Validation status of the 770 canonical values: 233 validated, 260 unvalidated (no identity applies,
e.g. inventories, EPS), 270 needs review, 7 failed validation, 0 verified (no human review was
performed). Most `needs_review` values come from highlights tables that print two currencies/units
under one year header (sub-columns), which FinRAG deliberately does not resolve by guessing. The two
soft PAT mismatches are on such tables. The column-total heuristic fails on income statements where a
"Total" row is not the plain sum of the rows above (e.g. gross revenue, less GST, net revenue); it is
reported for transparency and does not demote values.

### 2. Extraction vs. gold values (`extraction_gold`, 15 items, FY2024-25 report)
**15 / 15 correct (100%)**, found rate 100%. Items: consolidated total assets, equity, liabilities,
revenue from operations, net profit, PBT, basic EPS, current and non-current borrowings, cash,
finance costs, total income; standalone revenue, other income, total income. Caveat: the metric
counts an item correct if the expected value is among the extracted candidates for that
metric/period/basis; for finance costs two candidates existed (24,269 on the statement of profit and
loss and 20,414 from another table), so the measure is slightly lenient for that item. 15 items is a
small sample; treat this as a smoke test, not a benchmark.

### 3. RAG (`rag`, 8 gold questions on the FY2024-25 report)
Gold file: `docs/evaluation/gold_rag_public_annual_report.jsonl` (each expected number and page was
checked in the PDF text). LLM: Qwen3-4B Q4_K_M on llama.cpp, CPU. All four runs are stored.

| Run | Change before the run | Answer acc. | Citation corr. | Retrieval hit | Faithfulness | Errors | Median latency |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | — | 75.0% | 75.0% | 100% | 100% | 0 | 68 s |
| 2 | metric facts show the printed row label and are ranked by label match; prompt rule "Profit for the year ≠ Profit after tax" | 87.5% | 87.5% | 100% | 100% | 0 | 59 s |
| 3 | basis guard + running page headers kept in chunk context | *invalid* | — | — | — | **7** | — |
| 4 | llama.cpp prompt cache capped (`--cache-ram 1024`, `-np 1`) | **100%** | **100%** | 100% | 100% | 0 | 55 s |
| 5 | code restructuring + derived-total facts, forecast prompt rule, question-year check, needs-review blocking (2026-11-24 04:14 UTC) | 100% | 100% | 100% | 100% | 0 | 64 s* |

\* run 5 shared the CPU with other tests, so its latency is not comparable with run 4.

What the failures taught us (and why each fix is generic, not tuned to this report):
* **Run 1** — both wrong answers were *faithful* (the number existed in the cited source) but answered
  a different line item: "Profit for the year" → 80,787 (*Profit after tax* before the share of
  associates) and consolidated cash → 82,471 (the *standalone* figure). Faithfulness ≠ correctness.
* **Run 2** fixed the line-item confusion; the cash answer still came from a standalone notes page.
  Cause: the "STANDALONE FINANCIAL STATEMENTS" running header had been pushed out of the chunk's
  context by repeated unit lines, so nothing told the model the passage was standalone. Fix: keep each
  page's first heading in context, de-duplicate context lines, and drop passages whose headers state
  the *other* basis when the question names one.
* **Run 3** is not a quality measurement: the llama.cpp server was killed by the kernel OOM killer
  after the first question (its default 8 GiB host-RAM prompt cache). FinRAG returned explicit
  "language model is not available" errors for the other 7 questions — no fabricated answers. Fix: cap
  the cache; peak server memory during run 4 was 4.6 GB.
* **Important caveat:** runs 2–5 reuse the same 8 questions after changes motivated by earlier
  failures, so the 8/8 of runs 4–5 is a regression check on a very small set, not an independent benchmark.
  Build a larger gold set from your own documents for a real measurement.

Latency is dominated by CPU prompt processing (~20–25 tokens/s for a 3–4k-token prompt); a GPU
endpoint (NIM / vLLM / TensorRT-LLM) is the intended production setup.

### 4. Retrieval-only measurement (notebook 11, 2026-11-24 04:13 UTC — new, not stored as a run)
Production retriever, same 8 gold questions, top-5 passages, "relevant" = passage on the expected PDF page:
context recall / hit rate **87.5%**, MRR **0.338**, mean context precision **20%**, mean retrieval latency 1.8 s (CPU).
The one miss (current borrowings) was still answered correctly because the extracted value arrives as an `[M#]` fact —
which is exactly why FinRAG does not rely on passage retrieval alone. Low context precision is expected with this strict
page-level definition (the same figures appear in notes and highlights pages too).

### 5. Failures found by the learning notebooks (not part of the gold set)
Notebook 10 found two faithful-but-wrong behaviours on new questions — "total borrowings" answered with the non-current
part, and "expected share price in 2030" answered with a historical figure — and notebook 12 found a growth rate computed
from `needs_review` inputs. All were fixed generically (`docs/RESTRUCTURING_REPORT.md` §4); notebook 10 records the
original answers. These questions are anecdotes, not a benchmark: an independent gold set is still the next step.

### 6. LoRA fine-tuning (`finetune`)
See `docs/FINE_TUNING.md`: base 0.0% vs LoRA 69.3% fully-correct on 127 held-out rows, with the
caveats documented there.
