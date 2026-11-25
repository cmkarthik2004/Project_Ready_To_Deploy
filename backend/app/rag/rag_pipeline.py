"""RAG orchestration: question -> grounded, cited, verified answer.

    resolve documents  (retriever.resolve_documents)
    retrieve passages   (retriever.retrieve: hybrid search, basis guard, rerank)   -> [S#]
    structured facts    (facts.metric_facts, facts.calculation_facts)              -> [M#], [C#]
    prompt              (prompts.SYSTEM_PROMPT, prompts.build_user_prompt)
    generate            (llm.client.chat on the active OpenAI-compatible endpoint)
    verify              (verification.verify_answer)

Each step lives in its own module so it can be studied and tested separately
(see notebooks/10_rag_pipeline.ipynb).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.llm import client as llm
from app.rag import facts, retriever
from app.rag.prompts import SYSTEM_PROMPT, build_user_prompt
from app.rag.verification import verify_answer


@dataclass
class RagAnswer:
    answer: str
    status: str
    citations: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    calculations: list[dict] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    model: str | None = None
    latency_ms: int = 0
    timings: dict = field(default_factory=dict)


def build_sources(db: Session, owner_id: uuid.UUID, question: str, docs, timings: dict) -> tuple[list[dict], list[dict]]:
    """All numbered sources for a question: passages [S#] + metric facts [M#] + calculations [C#]."""
    sources = retriever.passage_sources(retriever.retrieve(db, owner_id, question, docs, timings))
    sources += facts.metric_facts(db, owner_id, question, docs)
    calc_sources, calcs = facts.calculation_facts(db, owner_id, question, docs)
    return sources + calc_sources, calcs


def build_messages(question: str, sources: list[dict], history: list[dict] | None = None) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-2:]:
        messages.append({"role": h["role"], "content": h["content"][:600]})
    messages.append({"role": "user", "content": build_user_prompt(question, sources)})
    return messages


def answer_question(db: Session, owner_id: uuid.UUID, question: str, document_ids: list[uuid.UUID] | None,
                    history: list[dict] | None = None) -> RagAnswer:
    t0 = time.time()
    timings: dict = {}
    docs = retriever.resolve_documents(db, owner_id, document_ids)
    if not docs:
        return RagAnswer("No processed documents are available for this question. Upload a document (or select processed documents) first.",
                         "insufficient_evidence", verification={"reason": "no processed documents in scope"})
    sources, calcs = build_sources(db, owner_id, question, docs, timings)
    if not sources:
        return RagAnswer("I could not find any passage in the selected documents that relates to this question.", "insufficient_evidence",
                         verification={"reason": "no retrieval candidates"}, latency_ms=int((time.time() - t0) * 1000), timings=timings)

    ep = llm.active_endpoint(db)
    t = time.time()
    try:
        out = llm.chat(build_messages(question, sources, history), ep)
    except llm.LLMError as exc:
        return RagAnswer(f"The language model is not available, so no answer was generated. ({exc})", "error",
                         evidence=evidence_view(sources), calculations=calcs, verification={"reason": "llm_error", "error": str(exc)},
                         latency_ms=int((time.time() - t0) * 1000), timings=timings)
    timings["llm_ms"] = int((time.time() - t) * 1000)
    timings["prompt_tokens"] = out["usage"].get("prompt_tokens")
    timings["completion_tokens"] = out["usage"].get("completion_tokens")

    v = verify_answer(out["content"], sources, question)
    return RagAnswer(v.answer, v.status, v.citations, evidence_view(sources), calcs, v.verification,
                     out.get("model") or ep.model, int((time.time() - t0) * 1000), timings)


def evidence_view(sources: list[dict]) -> list[dict]:
    return [{k: v for k, v in x.items() if k != "text"} | {"text": x["text"][:1500]} for x in sources]


def answer_dashboard_question(db: Session, owner_id: uuid.UUID, question: str, filters: dict, chart_id: str | None,
                              history: list[dict] | None = None) -> tuple[RagAnswer, bool]:
    """Answer a question about the user's dashboard. Returns (answer, used_scenario)."""
    from app.financial_analytics.dashboard import build_dashboard
    from app.rag.dashboard_context import DASHBOARD_RULES, dashboard_sources, scenario_sources

    t0 = time.time()
    timings: dict = {}
    d = build_dashboard(db, owner_id, filters)
    if not d["kpis"] and not d["charts"]:
        return RagAnswer("There is no dashboard data for the current filters, so there is nothing to discuss yet.", "insufficient_evidence",
                         verification={"reason": "empty dashboard"}), False
    want = set(filters.get("document_ids") or [])
    orgs = set(filters.get("organisations") or [])
    doc_ids = [uuid.UUID(x["id"]) for x in d["available"]["documents"]
               if (not want or x["id"] in want) and (not orgs or x["entity"] in orgs)]
    sources = dashboard_sources(d, question, chart_id)
    scen = scenario_sources(d, question)
    sources += scen
    docs = retriever.resolve_documents(db, owner_id, doc_ids)
    if docs:
        rag, calcs = build_sources(db, owner_id, question, docs, timings)
        by_kind: dict[str, int] = {}
        for x in rag:  # keep the prompt within the model's context window
            k = x["sid"][0]
            by_kind[k] = by_kind.get(k, 0) + 1
            if by_kind[k] <= {"S": 4, "M": 6, "C": 4}.get(k, 4):
                sources.append(x)
    else:
        calcs = []
    ep = llm.active_endpoint(db)
    messages = build_messages(question, sources, history)
    messages[0]["content"] = SYSTEM_PROMPT + DASHBOARD_RULES
    t = time.time()
    try:
        out = llm.chat(messages, ep)
    except llm.LLMError as exc:
        return RagAnswer(f"The language model is not available, so no answer was generated. ({exc})", "error",
                         evidence=evidence_view(sources), verification={"reason": "llm_error", "error": str(exc)},
                         latency_ms=int((time.time() - t0) * 1000), timings=timings), bool(scen)
    timings["llm_ms"] = int((time.time() - t) * 1000)
    timings["prompt_tokens"] = out["usage"].get("prompt_tokens")
    timings["completion_tokens"] = out["usage"].get("completion_tokens")
    v = verify_answer(out["content"], sources, question)
    return RagAnswer(v.answer, v.status, v.citations, evidence_view(sources), calcs, v.verification,
                     out.get("model") or ep.model, int((time.time() - t0) * 1000), timings), bool(scen)
