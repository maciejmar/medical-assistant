"""Węzły grafu RAG: przepisanie zapytania → wyszukiwanie → rerank → generacja → raport zużycia.

Każde wywołanie vLLM przechodzi przez src.llm, które zapisuje metryki w tabeli token_usage,
a węzły dodatkowo agregują zużycie w stanie grafu i przekazują je do klienta przez stream.
"""

import json
import logging
import re
from typing import Any

from langgraph.config import get_stream_writer

from .. import llm
from ..config import settings
from ..vector_store import ALLOWED_AUDIENCES, ALLOWED_CATEGORIES, reranker, vector_store
from .state import ChatState, merge_usage

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = (
    "Jesteś modułem optymalizacji zapytań w systemie wyszukiwania wiedzy logopedycznej. "
    "Na podstawie pytania lekarza logopedy (i krótkiej historii rozmowy) przepisz je na "
    "samodzielne, precyzyjne zapytanie wyszukiwawcze po polsku: rozwiń skróty i zaimki, dodaj "
    "kluczowe terminy medyczne i ewentualne kody ICD. Oceń, czy potrzebne jest przeszukanie bazy "
    "wiedzy (false tylko dla powitań i podziękowań). Ustal opcjonalne filtry: category ∈ "
    '["disorder","icd","technique","diagnostics"] oraz audience ∈ ["children","adults"] – '
    "tylko gdy pytanie jednoznacznie tego dotyczy, w przeciwnym razie null. Zwróć WYŁĄCZNIE "
    'obiekt JSON: {"query": "...", "needs_retrieval": true, "filters": {"category": null, '
    '"audience": null}}'
)

ANSWER_SYSTEM = (
    "Jesteś asystentem lekarza logopedy. Odpowiadasz po polsku, rzeczowo i zwięźle, językiem "
    "zawodowym. Opieraj się na dostarczonych fragmentach bazy wiedzy i przywołuj je w tekście w "
    "formie [1], [2]. Nie zmyślaj faktów, dawek ani kodów; jeśli źródła nie wystarczają, powiedz "
    "to wprost. Jesteś narzędziem wspierającym – ostateczne decyzje kliniczne należą do lekarza. "
    "Gdy wskazane jest skierowanie do innego specjalisty, zaznacz to."
)

NO_CONTEXT_NOTE = (
    "Nie znaleziono w bazie wiedzy fragmentów pasujących do pytania. Odpowiedz ostrożnie na "
    "podstawie ogólnej wiedzy i zaznacz, że odpowiedź nie pochodzi z bazy źródeł."
)

CHITCHAT_NOTE = (
    "To wiadomość towarzyska lub organizacyjna – odpowiedz krótko, bez cytowania źródeł."
)


def parse_rewrite_output(raw: str, question: str) -> dict[str, Any]:
    """Odporny parser odpowiedzi modelu; w razie niepowodzenia zwraca oryginalne pytanie."""
    fallback = {"query": question, "needs_retrieval": True, "filters": {}}
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return fallback
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback
    if not isinstance(data, dict):
        return fallback

    query = data.get("query")
    query = query.strip() if isinstance(query, str) and query.strip() else question
    needs = data.get("needs_retrieval")
    raw_filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    filters: dict[str, str] = {}
    if raw_filters.get("category") in ALLOWED_CATEGORIES:
        filters["category"] = raw_filters["category"]
    if raw_filters.get("audience") in ALLOWED_AUDIENCES:
        filters["audience"] = raw_filters["audience"]
    return {
        "query": query,
        "needs_retrieval": needs if isinstance(needs, bool) else True,
        "filters": filters,
    }


def _stage(name: str) -> None:
    get_stream_writer()({"type": "status", "stage": name})


async def rewrite_query(state: ChatState) -> dict[str, Any]:
    _stage("rewrite")
    history = state.get("history", [])[-4:]
    transcript = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history)
    user_prompt = f"Historia:\n{transcript or '(brak)'}\n\nPytanie: {state['question']}"
    try:
        completion = await llm.chat_complete(
            [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            user_id=state["user_id"],
            operation="query_rewriting",
            temperature=0.0,
            max_tokens=300,
        )
    except Exception:
        logger.exception("Przepisywanie zapytania nie powiodło się – używam oryginału")
        return {"rewritten_query": state["question"], "needs_retrieval": True, "filters": {}}

    parsed = parse_rewrite_output(completion.text, state["question"])
    return {
        "rewritten_query": parsed["query"],
        "needs_retrieval": parsed["needs_retrieval"],
        "filters": parsed["filters"],
        "usage": completion.usage.as_dict(),
    }


async def retrieve(state: ChatState) -> dict[str, Any]:
    _stage("retrieve")
    query = state["rewritten_query"]
    vectors, usage = await llm.embed([query], user_id=state["user_id"], operation="embedding_query")
    filters = state.get("filters") or {}
    docs = await vector_store.hybrid_search(query, vectors[0], filters=filters)
    if not docs and filters:
        docs = await vector_store.hybrid_search(query, vectors[0], filters=None)
    return {"candidates": docs, "usage": usage.as_dict()}


async def rerank(state: ChatState) -> dict[str, Any]:
    _stage("rerank")
    docs = await reranker.rerank(state["rewritten_query"], state.get("candidates", []))
    get_stream_writer()(
        {
            "type": "sources",
            "sources": [
                {
                    "index": i,
                    "title": d["title"],
                    "category": d["category"],
                    "audience": d["audience"],
                    "icd10": d.get("icd10", ""),
                    "icd11": d.get("icd11", ""),
                    "snippet": d["text"][:320],
                    "score": round(float(d.get("score", 0.0)), 4),
                }
                for i, d in enumerate(docs, start=1)
            ],
        }
    )
    return {"documents": docs}


def build_answer_messages(state: ChatState, grounded: bool) -> list[dict[str, str]]:
    system = ANSWER_SYSTEM
    parts: list[str] = []
    if grounded:
        blocks = [
            f"[{i}] {d['title']} (ICD-10: {d.get('icd10') or '—'}, "
            f"ICD-11: {d.get('icd11') or '—'})\n{d['text']}"
            for i, d in enumerate(state["documents"], start=1)
        ]
        parts.append("Fragmenty bazy wiedzy:\n" + "\n\n".join(blocks))
    elif state.get("needs_retrieval", True):
        system += " " + NO_CONTEXT_NOTE
    else:
        system += " " + CHITCHAT_NOTE

    if state.get("patient_context"):
        parts.append("Kontekst pacjenta (zanonimizowany):\n" + state["patient_context"])
    parts.append("Pytanie lekarza: " + state["question"])

    messages = [{"role": "system", "content": system}]
    messages.extend(state.get("history", [])[-settings.history_window :])
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


async def _stream_answer(state: ChatState, grounded: bool) -> dict[str, Any]:
    _stage("generate")
    writer = get_stream_writer()
    pieces: list[str] = []
    usage = llm.Usage()
    async for item in llm.chat_stream(
        build_answer_messages(state, grounded), user_id=state["user_id"], operation="chat_rag"
    ):
        if isinstance(item, llm.Usage):
            usage = item
        else:
            pieces.append(item)
            writer({"type": "token", "text": item})
    return {"answer": "".join(pieces), "usage": usage.as_dict()}


async def generate(state: ChatState) -> dict[str, Any]:
    return await _stream_answer(state, grounded=True)


async def generate_without_context(state: ChatState) -> dict[str, Any]:
    if not state.get("documents"):
        get_stream_writer()({"type": "sources", "sources": []})
    return await _stream_answer(state, grounded=False)


async def report_usage(state: ChatState) -> dict[str, Any]:
    """Krok końcowy: przekazuje klientowi zagregowane zużycie tokenów z całego przebiegu grafu."""
    get_stream_writer()({"type": "usage", **merge_usage(None, state.get("usage"))})
    return {}
