"""Compare the base model and the LoRA-adapted model on the held-out split.

Metrics (per example, then averaged):
  json_valid       output parses as JSON with the expected keys
  metric_correct   predicted metric key == gold (null for abstention rows)
  values_exact     predicted set of (period, value) pairs == gold set
  fully_correct    metric_correct and values_exact
  abstain_correct  on abstention rows: predicted metric is null
  latency          seconds per generation

Results are written to <adapter>/eval_results.json and stored as an
`evaluation_runs` row (kind='finetune') so they appear on the Evaluation page.

Usage:
    python -m app.fine_tuning.evaluate_lora --model <base> --adapter <dir> --data ../data/training_data [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) and "metric" in d else None
    except json.JSONDecodeError:
        return None


def norm_pairs(values) -> set:
    out = set()
    for v in values or []:
        if isinstance(v, dict):
            out.add((re.sub(r"\s", "", str(v.get("period"))), re.sub(r"\s", "", str(v.get("value")))))
    return out


def score(pred: dict | None, gold: dict) -> dict:
    if pred is None:
        return {"json_valid": 0, "metric_correct": 0, "values_exact": 0, "fully_correct": 0}
    mc = int(pred.get("metric") == gold["metric"])
    ve = int(norm_pairs(pred.get("values")) == norm_pairs(gold["values"]))
    return {"json_valid": 1, "metric_correct": mc, "values_exact": ve, "fully_correct": int(mc and ve)}


def run(model, tok, examples: list[dict], device: str) -> list[dict]:
    out = []
    for e in examples:
        msgs = [{"role": "system", "content": e["instruction"]}, {"role": "user", "content": e["input"]}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False, return_dict=True).to(device)
        t = time.time()
        with torch.no_grad():
            gen = model.generate(**ids, max_new_tokens=160, do_sample=False, pad_token_id=tok.eos_token_id)
        txt = tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        gold = json.loads(e["output"])
        s = score(parse(txt), gold)
        s.update({"latency_s": round(time.time() - t, 2), "abstain_row": gold["metric"] is None, "input": e["input"], "gold": gold,
                  "prediction": txt.strip()[:400], "filename": e["filename"], "location": e["location"]})
        out.append(s)
    return out


def summary(rows: list[dict]) -> dict:
    n = len(rows) or 1
    neg = [r for r in rows if r["abstain_row"]]
    pos = [r for r in rows if not r["abstain_row"]]
    agg = {k: round(sum(r[k] for r in rows) / n, 4) for k in ("json_valid", "metric_correct", "values_exact", "fully_correct")}
    agg["positive_fully_correct"] = round(sum(r["fully_correct"] for r in pos) / len(pos), 4) if pos else None
    agg["abstain_correct"] = round(sum(r["metric_correct"] for r in neg) / len(neg), 4) if neg else None
    agg["latency_s_mean"] = round(statistics.mean(r["latency_s"] for r in rows), 2) if rows else None
    agg["examples"] = len(rows)
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-db", action="store_true")
    a = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    test = [json.loads(l) for l in Path(a.data, "test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.limit:
        test = test[: a.limit]
    tok = AutoTokenizer.from_pretrained(a.model)
    base = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.float32 if device == "cpu" else torch.bfloat16).to(device).eval()
    base_rows = run(base, tok, test, device)
    tuned = PeftModel.from_pretrained(base, a.adapter).to(device).eval()
    tuned_rows = run(tuned, tok, test, device)
    manifest = json.loads(Path(a.adapter, "finrag_manifest.json").read_text())
    stats = json.loads(Path(a.data, "dataset_stats.json").read_text()) if Path(a.data, "dataset_stats.json").exists() else {}
    result = {"evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "device": device, "base_model": a.model, "adapter": a.adapter,
              "dataset": stats, "training": {k: v for k, v in manifest.items() if k != "log_history"},
              "base": summary(base_rows), "lora": summary(tuned_rows),
              "examples": [{"input": b["input"], "gold": b["gold"], "base": b["prediction"], "lora": t["prediction"],
                            "base_correct": b["fully_correct"], "lora_correct": t["fully_correct"], "location": b["location"], "filename": b["filename"]}
                           for b, t in zip(base_rows, tuned_rows)]}
    Path(a.adapter, "eval_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({"base": result["base"], "lora": result["lora"]}, indent=2))
    if not a.no_db:
        from app.database.session import SessionLocal
        from app.models import EvaluationRun

        with SessionLocal() as db:
            db.add(EvaluationRun(
                kind="finetune", status="completed",
                method="Held-out structured-extraction evaluation: base model vs. LoRA adapter on table rows from documents not used in training. "
                       "Gold labels are extractions that passed accounting-identity validation (or human verification).",
                dataset={"test_examples": len(test), **stats}, metrics={"base": result["base"], "lora": result["lora"]},
                details=result["examples"][:300], model_info={"base_model": a.model, "adapter": a.adapter, "device": device, "training": result["training"]},
                finished_at=dt.datetime.now(dt.timezone.utc)))
            db.commit()


if __name__ == "__main__":
    main()
