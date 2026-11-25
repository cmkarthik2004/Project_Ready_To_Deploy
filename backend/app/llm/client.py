"""Client for any OpenAI-compatible chat-completions endpoint.

The same code talks to:
* a local llama.cpp server (llama-cpp-python[server]) running Qwen3 GGUF on CPU,
* NVIDIA NIM (hosted at integrate.api.nvidia.com or a self-hosted NIM container),
* vLLM / TGI / TensorRT-LLM servers exposing the OpenAI API.

The active endpoint comes from the `model_configurations` table (admin can
switch it) or, if none is active, from environment settings. API keys are read
from environment variables only and are never stored in the database.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings


@dataclass
class LLMEndpoint:
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str | None
    disable_thinking: bool = True


class LLMError(RuntimeError):
    pass


def endpoint_from_settings() -> LLMEndpoint:
    s = get_settings()
    return LLMEndpoint("default (environment)", s.llm_provider_name, s.llm_base_url.rstrip("/"), s.llm_model, s.llm_api_key, s.llm_disable_thinking)


def active_endpoint(db=None) -> LLMEndpoint:
    if db is not None:
        from app.models import ModelConfiguration

        cfg = db.query(ModelConfiguration).filter_by(kind="llm", is_active=True).first()
        if cfg:
            key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
            return LLMEndpoint(cfg.name, cfg.provider, cfg.base_url.rstrip("/"), cfg.model_name, key,
                               bool(cfg.params.get("disable_thinking", "qwen3" in cfg.model_name.lower())))
    return endpoint_from_settings()


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def chat(messages: list[dict], ep: LLMEndpoint, max_tokens: int | None = None, temperature: float | None = None) -> dict:
    s = get_settings()
    msgs = [dict(m) for m in messages]
    if ep.disable_thinking and msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += " /no_think"
    headers = {"Content-Type": "application/json"}
    if ep.api_key:
        headers["Authorization"] = f"Bearer {ep.api_key}"
    body = {"model": ep.model, "messages": msgs, "max_tokens": max_tokens or s.llm_max_tokens,
            "temperature": s.llm_temperature if temperature is None else temperature}
    t = time.time()
    try:
        r = httpx.post(f"{ep.base_url}/chat/completions", json=body, headers=headers, timeout=s.llm_timeout_s)
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM endpoint '{ep.name}' unreachable at {ep.base_url}: {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"LLM endpoint '{ep.name}' returned HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    content = _THINK_RE.sub("", content).strip()
    return {"content": content, "usage": data.get("usage", {}), "latency_ms": int((time.time() - t) * 1000), "model": data.get("model", ep.model)}


def status(ep: LLMEndpoint) -> dict:
    headers = {"Authorization": f"Bearer {ep.api_key}"} if ep.api_key else {}
    out = {"name": ep.name, "provider": ep.provider, "base_url": ep.base_url, "model": ep.model, "api_key_configured": bool(ep.api_key)}
    try:
        r = httpx.get(f"{ep.base_url}/models", headers=headers, timeout=5)
        out["reachable"] = r.status_code == 200
        out["http_status"] = r.status_code
        if r.status_code == 200:
            ids = [m.get("id") for m in r.json().get("data", [])]
            out["served_models"] = ids[:20]
            out["model_available"] = ep.model in ids if ids else None
    except httpx.HTTPError as exc:
        out["reachable"] = False
        out["error"] = str(exc)[:200]
    return out
