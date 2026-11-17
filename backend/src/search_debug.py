"""Diagnostyka wyszukiwania („Sprawdź wyszukiwanie” w panelu bazy wiedzy).

Odtwarza etapy czatu dla jednego pytania – przepisanie zapytania, wyszukiwanie hybrydowe
(gęste + słowa, fuzja RRF), rerank – i pokazuje, na którym etapie fragment odpada. Opcjonalnie
ocenia wszystkie fragmenty wskazanego dokumentu, także te spoza puli kandydatów.
"""

from typing import Any

from . import llm
from .config import settings
from .graph.nodes import REWRITE_SYSTEM, merge_candidates, parse_rewrite_output
from .vector_store import DENSE, SPARSE, reranker, select_relevant, vector_store

WIDE_LIMIT = 50  # szersza pula – miejsce fragmentu także poza kandydatami czatu


async def rewrite(question: str, user_id: int) -> tuple[str, dict[str, str]]:
    completion = await llm.chat_complete(
        [
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": f"Historia:\n(brak)\n\nPytanie: {question}"},
        ],
        user_id=user_id,
        operation="search_test",
        temperature=0.0,
        max_tokens=300,
    )
    parsed = parse_rewrite_output(completion.text, question)
    return parsed["query"], parsed["filters"]


def _rank(ids: list[str]) -> dict[str, int]:
    return {point_id: i for i, point_id in enumerate(ids, start=1)}


def focus_verdict(rows: list[dict[str, Any]], document_id: int, title: str) -> dict[str, Any]:
    """Podsumowanie dla wskazanego dokumentu: czy trafia do źródeł, a jeśli nie – dlaczego."""
    mine = [r for r in rows if r["document_id"] == document_id]
    base = {"document_id": document_id, "title": title, "chunks": len(mine)}
    if not mine:
        return {
            **base,
            "best_score": None,
            "verdict": "Dokument nie ma fragmentów w indeksie – kliknij „Indeksuj ponownie”.",
        }
    best = max(mine, key=lambda r: r["score"])
    candidates = [r for r in mine if r["candidate"]]
    summary = {**base, "best_score": best["score"]}
    if any(r["selected"] for r in mine):
        n = sum(r["selected"] for r in mine)
        return {**summary, "verdict": f"Dokument trafia do źródeł odpowiedzi ({n} fragm.)."}
    if candidates:
        return {
            **summary,
            "verdict": (
                f"Fragmenty są wśród kandydatów ({len(candidates)}), ale reranker ocenił je niżej "
                f"niż wybrane źródła (najlepszy: {best['score']:.3f}). Pytanie i treść dokumentu "
                "mogą mówić o czymś innym."
            ),
        }

    def place(value: int | None) -> str:
        return str(value) if value else f"poza {WIDE_LIMIT}"

    would = best["score"] >= settings.rerank_min_score
    return {
        **summary,
        "verdict": (
            f"Żaden fragment nie wszedł do {settings.retrieval_top_k} kandydatów wyszukiwania. "
            f"Najlepszy fragment: miejsce {place(best['dense_rank'])} w wyszukiwaniu znaczeniowym, "
            f"{place(best['sparse_rank'])} w wyszukiwaniu po słowach. Reranker oceniłby go na "
            f"{best['score']:.3f}"
            + (
                " – gdyby był kandydatem, mógłby trafić do źródeł (problem leży w wyszukiwaniu)."
                if would
                else " – poniżej progu, więc i tak by nie trafił (treść nie pasuje do pytania)."
            )
        ),
    }


async def diagnose(
    question: str, user_id: int, document_id: int | None = None, document_title: str = ""
) -> dict[str, Any]:
    query, filters = await rewrite(question, user_id)
    vectors, _ = await llm.embed([query], user_id=user_id, operation="embedding_query")
    dense = vectors[0]

    # Kandydaci dokładnie jak w czacie (retrieve): bez filtra + wzmocnienie filtrem.
    candidates = await vector_store.hybrid_search(query, dense, filters=None, user_id=user_id)
    if filters:
        filtered = await vector_store.hybrid_search(query, dense, filters=filters, user_id=user_id)
        candidates = merge_candidates(filtered, candidates)
    candidate_ids = {d["id"] for d in candidates}

    wide = await vector_store.hybrid_search(
        query, dense, filters=None, user_id=user_id, limit=WIDE_LIMIT
    )
    fusion = _rank([d["id"] for d in wide])
    dense_rank = _rank(
        await vector_store.single_ranking(
            query, dense, using=DENSE, user_id=user_id, limit=WIDE_LIMIT
        )
    )
    sparse_rank = _rank(
        await vector_store.single_ranking(
            query, dense, using=SPARSE, user_id=user_id, limit=WIDE_LIMIT
        )
    )
    pool = merge_candidates(candidates, wide)
    if document_id is not None:
        pool = merge_candidates(pool, await vector_store.document_chunks(document_id))

    scored = await reranker.score(query, pool)
    in_pool = [d for d in scored if d["id"] in candidate_ids]
    selected_ids = {d["id"] for d in select_relevant(in_pool, settings.rerank_top_n)}
    rows = [
        {
            "id": d["id"],
            "title": d.get("title", ""),
            "document_id": d.get("kb_document_id"),
            "snippet": str(d.get("text", ""))[:240],
            "score": round(float(d["score"]), 4),
            "dense_rank": dense_rank.get(d["id"]),
            "sparse_rank": sparse_rank.get(d["id"]),
            "fusion_rank": fusion.get(d["id"]),
            "candidate": d["id"] in candidate_ids,
            "selected": d["id"] in selected_ids,
        }
        for d in scored
    ]
    return {
        "question": question,
        "rewritten_query": query,
        "filters": filters,
        "top_k": settings.retrieval_top_k,
        "top_n": settings.rerank_top_n,
        "min_score": settings.rerank_min_score,
        "rows": rows,
        "focus": None if document_id is None else focus_verdict(rows, document_id, document_title),
    }
