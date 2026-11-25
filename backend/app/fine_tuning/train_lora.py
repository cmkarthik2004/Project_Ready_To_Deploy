"""LoRA fine-tuning with Hugging Face Transformers + PEFT + TRL.

Runs on an NVIDIA GPU when CUDA is available (bf16), otherwise on CPU (fp32).
The device actually used is recorded in the run manifest — nothing claims GPU
training unless torch.cuda.is_available() was true during the run.

Usage:
    python -m app.fine_tuning.train_lora --model /path/or/hf-id --data ../data/training_data --out app/fine_tuning/output/run1
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer


def load_split(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def to_prompt_completion(e: dict) -> dict:
    return {"prompt": [{"role": "system", "content": e["instruction"]}, {"role": "user", "content": e["input"]}],
            "completion": [{"role": "assistant", "content": e["output"]}]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-length", type=int, default=384)
    ap.add_argument("--batch", type=int, default=4)
    a = ap.parse_args()

    cuda = torch.cuda.is_available()
    torch.manual_seed(7)
    data = Path(a.data)
    train = load_split(data / "train.jsonl")
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16 if cuda else torch.float32)
    ds = Dataset.from_list([to_prompt_completion(e) for e in train])
    lora = LoraConfig(r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr, per_device_train_batch_size=a.batch,
                    gradient_accumulation_steps=1, lr_scheduler_type="cosine", warmup_steps=2, logging_steps=5,
                    save_strategy="no", report_to=[], max_length=a.max_length, bf16=cuda, use_cpu=not cuda,
                    completion_only_loss=True, seed=7, dataloader_num_workers=0)
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok, peft_config=lora)
    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in trainer.model.parameters())
    t = time.time()
    res = trainer.train()
    secs = round(time.time() - t, 1)
    trainer.model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    manifest = {
        "base_model": a.model, "device": "cuda:" + torch.cuda.get_device_name(0) if cuda else f"cpu ({platform.processor() or platform.machine()})",
        "torch": torch.__version__, "train_examples": len(train), "epochs": a.epochs, "lr": a.lr, "lora_rank": a.rank,
        "max_length": a.max_length, "batch": a.batch, "trainable_params": trainable, "total_params": total,
        "train_seconds": secs, "train_loss": res.training_loss, "log_history": trainer.state.log_history,
    }
    Path(a.out, "finrag_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps({k: v for k, v in manifest.items() if k != "log_history"}, indent=2, default=str))


if __name__ == "__main__":
    main()
