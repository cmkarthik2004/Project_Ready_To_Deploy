# NVIDIA Integration — what is implemented, what was verified, what needs a GPU

**Development hardware:** 4 vCPU x86-64, 15 GB RAM, **no NVIDIA GPU** (`nvidia-smi` absent,
`torch.cuda.is_available() == False`). Nothing in this project claims GPU acceleration that was not
observed. The AI Model & RAG Status page reports GPU state from live checks (`torch.cuda` and
`nvidia-smi`) on the server where FinRAG runs.

| Technology | Status in FinRAG | Verified here? |
|---|---|---|
| **CUDA detection** | `GET /api/status` → `gpu` block (torch CUDA build, device names/memory, `nvidia-smi` output) | ✅ Verified it reports *no GPU* correctly on this CPU host |
| **GPU embeddings / reranking** | `rag/embeddings.py` selects `cuda` automatically when available | ⚠️ Code path only; CPU path verified |
| **LoRA fine-tuning on GPU** | `train_lora.py` switches to bf16 on CUDA, records the device used in `finrag_manifest.json` | ⚠️ GPU path not run; **CPU training was run and is reported in FINE_TUNING.md** |
| **NVIDIA NIM (hosted API)** | Any OpenAI-compatible endpoint can be registered in Settings → Language model endpoints (e.g. base URL `https://integrate.api.nvidia.com/v1`, `api_key_env=NVIDIA_API_KEY`) and activated; the Test button sends a real request | ⚠️ Network access to the NIM API host was verified (HTTP 200 on `/v1/models`); **no API key was available, so no NIM inference was run** |
| **NVIDIA NIM (self-hosted container)** | `docker compose --profile nim up` service with GPU reservation; point `LLM_BASE_URL` at `http://nim:8000/v1` | ❌ Needs NVIDIA GPU + NGC key |
| **TensorRT-LLM** | Its server (`trtllm-serve`) exposes an OpenAI-compatible API, so FinRAG uses it exactly like NIM (register the endpoint) | ❌ Needs NVIDIA GPU; not run |
| **NeMo** | Not used in code. NeMo (NeMo-RL / NeMo AutoModel) could replace the PEFT/TRL trainer for multi-GPU LoRA; the dataset format (`train.jsonl`, prompt/completion) is framework-neutral | ❌ Documented option only |
| **Docker** | `docker-compose.yml` (CPU stack) and `backend/Dockerfile.gpu` (CUDA 12.8 + cu128 PyTorch) | ⚠️ Compose file validated with `docker compose config`; images not built here (Docker Hub anonymous pull limit hit). GPU image untested |

## Running FinRAG on an NVIDIA GPU host

Requirements: NVIDIA driver ≥ 570 (CUDA 12.8), NVIDIA Container Toolkit, ≥ 16 GB GPU memory for an
8B NIM model (≥ 6 GB is enough for embeddings + LoRA on Qwen3-0.6B/1.7B).

1. Verify the GPU is visible to containers: `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`.
2. Use the GPU backend image: in `docker-compose.yml` set `build: { context: ./backend, dockerfile: Dockerfile.gpu }`
   for `api` and `worker`, and add `deploy.resources.reservations.devices` as in the `nim` service.
3. LLM options:
   * **NIM container**: `export NGC_API_KEY=…; docker compose --profile nim up -d nim`, then set
     `LLM_BASE_URL=http://nim:8000/v1` and `LLM_MODEL=<model id from GET /v1/models>`.
   * **Hosted NIM**: add the endpoint in Settings (base URL `https://integrate.api.nvidia.com/v1`, model
     id e.g. `meta/llama-3.1-8b-instruct`, `api_key_env=NVIDIA_API_KEY`), put the key in `.env`, restart, *Test*, *Activate*.
   * **TensorRT-LLM**: `trtllm-serve <hf-model> --port 8000` on the GPU host, then register it the same way.
4. Check **AI Model & RAG Status**: `cuda_available: true`, device list populated, LLM reachable.
5. Fine-tuning on GPU: `pip install -r requirements-finetune.txt`, then
   `python -m app.fine_tuning.train_lora --model Qwen/Qwen3-1.7B --data ../data/training_data --out app/fine_tuning/output/run-gpu`
   — the manifest will record `device: cuda:<name>`.

## Why the CPU path uses llama.cpp + GGUF
Qwen3-4B in bf16 needs ~8 GB RAM and runs very slowly on 4 CPU cores with PyTorch. The 4-bit GGUF
(2.5 GB, SHA-256 verified against the Hugging Face LFS hash) served by llama.cpp is the practical
CPU option. Measured on this host with the native llama.cpp server: ~20–25 prompt tokens/s; RAG answers
in the final evaluation run took 46–69 s (median 55 s). A GPU endpoint (NIM/TensorRT-LLM/vLLM) is the
intended production configuration.

## Measurements from notebook 14 (2026-11-24, this CPU-only host)
| Measurement | Result |
|---|---|
| GPU / CUDA / `nvidia-smi` / TensorRT-LLM / NeMo / vLLM | none present → all GPU cells skipped |
| CPU float32 matmul (2048², 4 threads) | 499.6 GFLOP/s |
| BGE-small embedding throughput | 11.8 long chunks/s (CPU) |
| Qwen3-4B weights (4.02 B params) | bf16 8.0 GB · int8 4.0 GB · int4 2.0 GB; actual Q4_K_M GGUF 2.50 GB |
| KV cache fp16 (36 layers, 8 KV heads, head dim 128) | 0.60 GB @4k · 1.21 GB @8k · 4.83 GB @32k tokens |
| llama.cpp server (CPU) | prompt 82.9 tok/s (672-token prompt) · generation 8.0 tok/s |
| Hosted NIM catalogue | reachable (HTTP 200, 32 models listed); inference not run — no `NVIDIA_API_KEY` |

