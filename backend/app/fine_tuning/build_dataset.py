"""Build a LoRA instruction dataset from VALIDATED extractions of real documents.

Task: given one table row exactly as it appears in a financial document,
return canonical JSON:
    {"metric": "<canonical key or null>", "values": [{"period": "...", "value": "..."}]}

Sources of examples (all from the user's own processed documents):
* positive: rows whose canonical metric values have validation_status
  'validated' (passed an accounting identity) or 'verified' (human-confirmed);
* abstention: spreadsheet/Word line items that do not map to a canonical
  metric -> {"metric": null, "values": []}, so the model learns not to force a
  mapping.

Rows are split by DOCUMENT (--test-docs) so evaluation uses documents the
model never saw; inputs that also occur in the test documents are removed
from training to avoid leakage. Each example records its provenance
(document, filename, location).

Usage:
    python -m app.fine_tuning.build_dataset --test-docs <uuid>[,<uuid>] [--exclude-docs ...] --out data/training_data
"""
from __future__ import annotations

import argparse
import json
import random
import uuid
from collections import defaultdict
from pathlib import Path

from app.database.session import SessionLocal
from app.document_processing.elements import describe_location
from app.financial_analytics.metric_extractor import matches_any_pattern
from app.financial_analytics.numbers import parse_number
from app.models import Document, DocumentTable, FinancialMetric

INSTRUCTION = ("You extract financial data. Map the table row to one canonical metric key and list every value with its "
               "column/period exactly as printed. Use null for the metric if the row is not one of the canonical metrics. "
               "Answer with JSON only.")
TRUSTED = ("validated", "verified")


def _row_key(m: FinancialMetric) -> tuple:
    loc = m.source.location
    return (m.document_id, loc.get("page"), loc.get("half"), loc.get("sheet"), loc.get("table_index"), loc.get("row"),
            (loc.get("bbox") or [None, None])[1], m.raw_label)


def build(test_docs: set[uuid.UUID], exclude: set[uuid.UUID], seed: int = 7) -> tuple[list[dict], list[dict]]:
    rows: dict[tuple, dict] = {}
    with SessionLocal() as db:
        docs = {d.id: d for d in db.query(Document).filter(Document.status == "processed").all()}
        q = db.query(FinancialMetric).filter(FinancialMetric.is_duplicate.is_(False))
        for m in q.all():
            if m.document_id in exclude or m.document_id not in docs:
                continue
            positive = m.metric_key != "line_item" and m.validation_status in TRUSTED
            negative = m.metric_key == "line_item"
            if not (positive or negative):
                continue
            k = _row_key(m)
            r = rows.setdefault(k, {"document_id": str(m.document_id), "filename": docs[m.document_id].original_filename,
                                    "location": describe_location(m.source.location), "input": m.source.snippet.split("\n")[-1][:600],
                                    "metric": m.metric_key if positive else None, "values": [], "metric_ids": []})
            if positive and r["metric"] is None:
                continue
            if positive:
                r["values"].append({"period": m.period_label, "value": m.raw_value})
            r["metric_ids"].append(str(m.id))
        # Abstention rows from stored PDF tables: labels that match NO canonical pattern at all.
        for t in db.query(DocumentTable).all():
            if t.document_id in exclude or t.document_id not in docs or docs[t.document_id].file_format != "pdf":
                continue
            heads = t.header[1:] if t.header and t.header[0] == "Particulars" else t.header
            for row in t.rows:
                if not row or not row[0] or matches_any_pattern(row[0]) or len(row) - 1 != len(heads):
                    continue
                if not all(parse_number(v) is not None for v in row[1:]):
                    continue
                text = row[0] + " | " + " | ".join(f"{h}: {v}" for h, v in zip(heads, row[1:]))
                k = (t.document_id, "table", t.table_index, row[0], tuple(row[1:]))
                rows.setdefault(k, {"document_id": str(t.document_id), "filename": docs[t.document_id].original_filename,
                                    "location": describe_location(t.location), "input": text[:600], "metric": None, "values": [], "metric_ids": []})
    train, test = [], []
    for r in rows.values():
        ex = {**r, "instruction": INSTRUCTION,
              "output": json.dumps({"metric": r["metric"], "values": r["values"] if r["metric"] else []}, ensure_ascii=False)}
        (test if uuid.UUID(r["document_id"]) in test_docs else train).append(ex)
    test_inputs = {e["input"] for e in test}
    train = [e for e in train if e["input"] not in test_inputs]  # leakage guard
    # keep abstention examples to at most 1/3 of each split
    rnd = random.Random(seed)
    for split in (train, test):
        pos = [e for e in split if e["metric"]]
        neg = [e for e in split if not e["metric"]]
        rnd.shuffle(neg)
        split[:] = pos + neg[: max(1, len(pos) // 2)]
        rnd.shuffle(split)
    return train, test


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-docs", required=True)
    ap.add_argument("--exclude-docs", default="")
    ap.add_argument("--out", default="../data/training_data")
    a = ap.parse_args()
    test_docs = {uuid.UUID(x) for x in a.test_docs.split(",") if x}
    exclude = {uuid.UUID(x) for x in a.exclude_docs.split(",") if x}
    train, test = build(test_docs, exclude)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("train", train), ("test", test)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for e in data:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    stats = {s: {"examples": len(d), "positive": sum(1 for e in d if e["metric"]), "abstain": sum(1 for e in d if not e["metric"]),
                 "documents": sorted({e["filename"] for e in d}), "metrics": dict(sorted(defaultdict(int, {}).items()))}
             for s, d in (("train", train), ("test", test))}
    for s, d in (("train", train), ("test", test)):
        c: dict[str, int] = defaultdict(int)
        for e in d:
            c[e["metric"] or "null"] += 1
        stats[s]["metrics"] = dict(sorted(c.items()))
    (out / "dataset_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "metrics"} for k, v in stats.items()}, indent=2))


if __name__ == "__main__":
    main()
