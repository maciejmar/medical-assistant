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
    "Na podstawie pytania lekarza logopedy (krótkiej historii rozmowy i ewentualnego kontekstu "
    "pacjenta) przepisz je na samodzielne, precyzyjne zapytanie wyszukiwawcze po polsku: rozwiń "
    "skróty i zaimki (np. „u tego pacjenta” zastąp rozpoznaniem z kontekstu), dodaj kluczowe "
    "terminy medyczne i kody ICD z kontekstu pacjenta. Ustal opcjonalne filtry: category ∈ "
    '["disorder","icd","technique","diagnostics"] oraz audience ∈ ["children","adults"] – '
    "tylko gdy pytanie jednoznacznie tego dotyczy, w przeciwnym razie null. Znaczniki w nawiasach "
    "kwadratowych (np. [IMIĘ PACJENTA], [TELEFON]) to zanonimizowane dane – nie umieszczaj ich w "
    "zapytaniu. Zwróć WYŁĄCZNIE "
    'obiekt JSON: {"query": "...", "filters": {"category": null, "audience": null}}'
)

ANSWER_SYSTEM = (
    "Jesteś asystentem lekarza logopedy. Odpowiadasz po polsku, rzeczowo i zwięźle, językiem "
    "zawodowym. Opieraj się na dostarczonych fragmentach bazy wiedzy i ZAWSZE wskazuj źródła: "
    "każde merytoryczne stwierdzenie opatrz odnośnikiem w formie [1], [2] do fragmentu, z którego "
    "pochodzi. Nie zmyślaj faktów, dawek ani kodów; jeśli źródła nie wystarczają, powiedz to "
    "wprost i oznacz, które części odpowiedzi wykraczają poza źródła. Jesteś narzędziem "
    "wspierającym – ostateczne decyzje kliniczne należą do lekarza. Gdy wskazane jest "
    "skierowanie do innego specjalisty, zaznacz to. Wykorzystaj wszystkie podane cechy pacjenta "
    "(wiek, płeć, rozpoznanie, opis). Dane osobowe są zanonimizowane: znaczniki takie jak "
    "[IMIĘ PACJENTA], [IMIĘ PACJENTKI], [NAZWISKO], [PESEL], [TELEFON], [ADRES] traktuj jak "
    "zwykłe odniesienia (płeć wynika ze znacznika imienia); nie komentuj anonimizacji, nie proś "
    "o te dane i nie powtarzaj znaczników bez potrzeby."
)

LOW_RELEVANCE_NOTE = (
    "Dostarczone fragmenty są tylko luźno związane z pytaniem. Cytuj je tam, gdzie pasują, i "
    "wyraźnie zaznacz, że baza wiedzy nie zawiera fragmentów ściśle odpowiadających pytaniu."
)

NO_CONTEXT_NOTE = (
    "Nie znaleziono w bazie wiedzy fragmentów pasujących do pytania. Odpowiedz ostrożnie na "
    "podstawie ogólnej wiedzy i zaznacz, że odpowiedź nie pochodzi z bazy źródeł."
)


def clinical_terms(patient_context: str | None) -> str:
    """Rozpoznanie i kod ICD z kontekstu pacjenta – dopisywane do zapytania wyszukiwawczego."""
    if not patient_context:
        return ""
    prefixes = ("Kod ICD:", "Rozpoznanie:")
    return " ".join(
        line.split(":", 1)[1].strip()
        for line in patient_context.splitlines()
        if line.startswith(prefixes)
    )


def parse_rewrite_output(raw: str, question: str) -> dict[str, Any]:
    """Odporny parser odpowiedzi modelu; w razie niepowodzenia zwraca oryginalne pytanie."""
    fallback = {"query": question, "filters": {}}
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
    raw_filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    filters: dict[str, str] = {}
    if raw_filters.get("category") in ALLOWED_CATEGORIES:
        filters["category"] = raw_filters["category"]
    if raw_filters.get("audience") in ALLOWED_AUDIENCES:
        filters["audience"] = raw_filters["audience"]
    return {"query": query, "filters": filters}


def _stage(name: str) -> None:
    get_stream_writer()({"type": "status", "stage": name})


def with_clinical_terms(query: str, patient_context: str | None) -> str:
    """Dokleja rozpoznanie/ICD pacjenta, jeśli model przepisujący ich nie uwzględnił."""
    terms = clinical_terms(patient_context)
    if not terms or terms.lower() in query.lower():
        return query
    return f"{query} {terms}"


async def rewrite_query(state: ChatState) -> dict[str, Any]:
    _stage("rewrite")
    history = state.get("history", [])[-4:]
    transcript = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history)
    patient_context = state.get("patient_context")
    user_prompt = f"Historia:\n{transcript or '(brak)'}\n\n"
    if patient_context:
        user_prompt += f"Kontekst pacjenta:\n{patient_context}\n\n"
    user_prompt += f"Pytanie: {state['question']}"
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
        return {
            "rewritten_query": with_clinical_terms(state["question"], patient_context),
            "filters": {},
        }

    parsed = parse_rewrite_output(completion.text, state["question"])
    return {
        "rewritten_query": with_clinical_terms(parsed["query"], patient_context),
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
    total = usage.as_dict()
    if not docs and query != state["question"]:
        fallback = with_clinical_terms(state["question"], state.get("patient_context"))
        vectors, extra = await llm.embed(
            [fallback], user_id=state["user_id"], operation="embedding_query"
        )
        docs = await vector_store.hybrid_search(fallback, vectors[0], filters=None)
        total = merge_usage(total, extra.as_dict())
    return {"candidates": docs, "usage": total}


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
                    "low_relevance": bool(d.get("low_relevance")),
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
        if any(d.get("low_relevance") for d in state["documents"]):
            system += " " + LOW_RELEVANCE_NOTE
    else:
        system += " " + NO_CONTEXT_NOTE

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
