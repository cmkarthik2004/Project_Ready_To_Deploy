# LoRA fine-tuning

## Purpose and boundaries
The fine-tuned model learns a **format and vocabulary task**: turn one financial table row, exactly as
printed, into canonical JSON

```json
{"metric": "revenue_from_operations", "values": [{"period": "2024-25", "value": "9,80,136"}]}
```
or `{"metric": null, "values": []}` when the row is not one of FinRAG's canonical metrics.

Fine-tuning is **not** a replacement for RAG or for the deterministic extractor. Company facts still
come from retrieved passages and validated database records. The adapter is a research component; it
is not wired into the production extraction path (see "Findings" for why).

## Pipeline (`backend/app/fine_tuning/`)
| Step | Command | What it does |
|---|---|---|
| 1. Dataset | `python -m app.fine_tuning.build_dataset --test-docs <ids> --out ../data/training_data` | Positive rows = canonical values with status `validated` (passed an accounting identity) or `verified` (human). Abstention rows = spreadsheet/Word line items and PDF table rows whose label matches **no** canonical pattern. Split **by document**; inputs also present in test documents are removed from training. Provenance (document, location, metric IDs) kept per example. |
| 2. Train | `python -m app.fine_tuning.train_lora --model <base> --data ../data/training_data --out app/fine_tuning/output/<run>` | PEFT LoRA (r=16, α=32, dropout 0.05, all attention + MLP projections) with TRL `SFTTrainer`, prompt/completion format, loss on the completion only. bf16 on CUDA, fp32 on CPU. Writes `finrag_manifest.json` with the device actually used. |
| 3. Evaluate | `python -m app.fine_tuning.evaluate_lora --model <base> --adapter <dir> --data ../data/training_data` | Greedy decoding of base and adapter on the held-out split; writes `eval_results.json` and an `evaluation_runs` row (kind `finetune`). |

Install: `pip install -r requirements-finetune.txt` (PEFT 0.22.0, TRL 1.18.2, datasets 5.2.0, accelerate 1.16.0).

## Run performed in development
* **Data:** two genuine public annual reports (FY2023-24 → training; FY2024-25 + DOCX/XLSX/XLS/CSV
  files transcribed from two of its statement pages → test). Train: **49** examples (33 positive,
  16 abstention). Test: **127** (85 positive, 42 abstention). The training set is small because only
  values that passed an accounting identity qualify — more human-verified values would enlarge it.
* **Base model:** Qwen/Qwen3-0.6B (606 M parameters). Trainable LoRA parameters: 10.09 M (1.7%).
* **Hardware:** CPU only (4 vCPU) — *no GPU was used or claimed*. 3 epochs, batch 4, lr 2e-4,
  max length 384: **583 s**, final training loss 0.081.

### Held-out results (127 examples, greedy decoding, CPU)
| Metric | Base (zero-shot) | LoRA |
|---|---:|---:|
| Output matches the JSON schema | 0.0% | **100.0%** |
| Metric key correct | 0.0% | 69.3% |
| All (period, value) pairs exact | 0.0% | 77.2% |
| Fully correct | 0.0% | **69.3%** |
| Fully correct — canonical-metric rows (85) | 0.0% | 77.6% |
| Correct abstention — non-canonical rows (42) | 0.0% | 52.4% |
| Mean latency per row | 16.5 s | 6.7 s |

Source: `backend/app/fine_tuning/output/lora-extract-v1/eval_results.json` (git-ignored, regenerable)
and the `finetune` run on the Evaluation page.

### Findings (read before using the adapter)
* **The baseline comparison is lopsided by design.** The base model got the same instruction but no
  list of canonical keys and no examples, so it produced free-form JSON (e.g.
  `{"metric_key": "Warehousing and Distribution Expenses", "2024-25": "12,922"}`) that fails the
  schema. The 0% shows the base model cannot do *this exact task* zero-shot — not that it lacks
  financial knowledge. A fairer baseline (few-shot prompt with the key list) was not run because of
  CPU time.
* **The adapter invents keys.** On abstention rows it often creates plausible but non-canonical keys
  (`net_cost_gratuity_funded`, `discount_rate`) instead of `null`, and it sometimes abstains on real
  metrics (`Finance Costs`). Any production use must validate predicted keys against the canonical
  list and fall back to the deterministic extractor.
* Error analysis (notebook 13): of 127 held-out rows, the adapter produced a **non-canonical key in 29** predictions,
  **abstained on 9 real metrics**, and in **0** cases had the right metric with wrong values.
* **Values are copied well** (77% exact pairs) including Indian digit grouping and parentheses,
  which is the part a small model learns quickly.
* With 49 training rows this is a demonstration of the method, not a production model.

## On a GPU
`train_lora.py` uses CUDA automatically (bf16). Larger bases (Qwen3-1.7B/4B) and more verified data
are the obvious next steps; see `docs/NVIDIA.md` for the GPU image and NeMo notes.
