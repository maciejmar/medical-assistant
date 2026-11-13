"""Goldset – zestaw pytań z odpowiedziami wzorcowymi do testowania jakości asystenta.

Goldset NIE trafia do bazy wiedzy (zawyżyłby wyniki) – jest przechowywany w osobnych tabelach.
Test puszcza każde pytanie przez ten sam graf RAG co czat lekarza (bez zapisu w historii rozmów),
a odpowiedź ocenia LLM-sędzia (0–5, pokryte/brakujące punkty, kolejność kroków) i podobieństwo
embeddingów do odpowiedzi wzorcowej.
"""

import asyncio
import json
import logging
import math
import re
import time
from typing import Any

from sqlmodel import col, select

from . import llm
from .config import settings
from .database import GoldsetItem, GoldsetResult, GoldsetRun, session_factory, utcnow

logger = logging.getLogger(__name__)

# Nagłówek pozycji: „7. Tytuł” (spacja po kropce). Kroki odpowiedzi „1.<TAB>Treść.” są treścią.
_HEADING = re.compile(r"^(\d{1,3})\.[  ]+(\S.*)$")

# Nagłówek odpowiedzi w stylu „ad1. Tytuł” / „Ad. 2 – Tytuł” / „ad 3)”.
_AD_HEADING = re.compile(r"^ad\.?\s*(\d{1,3})\s*[.):]?(?:\s+.*)?$", re.IGNORECASE)


def _ad_heading(line: str) -> int | None:
    match = _AD_HEADING.match(line.strip())
    return int(match.group(1)) if match else None


def _is_heading(line: str, expected: int, in_answers: bool) -> tuple[bool, str]:
    if "\t" in line:
        return False, ""
    match = _HEADING.match(line.strip())
    if not match or int(match.group(1)) != expected:
        return False, ""
    title = match.group(2).strip()
    # W części z odpowiedziami kroki kończą się kropką, a nagłówki nie.
    if in_answers and title.endswith("."):
        return False, ""
    return True, title


def _join_question(lines: list[str]) -> str:
    """Pytanie: łączy łamane wiersze (np. z PDF/Worda) w akapity."""
    paragraphs, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n".join(paragraphs).replace(" ,", ",")


def _join_answer(lines: list[str]) -> str:
    """Odpowiedź wzorcowa: zachowuje kroki w osobnych wierszach („1.<TAB>x” → „1. x”)."""
    cleaned = [re.sub(r"^(\d+)\.[ \t ]+", r"\1. ", line.rstrip()) for line in lines]
    return "\n".join(line for line in cleaned if line.strip()).strip()


def parse_goldset(text: str) -> list[dict[str, Any]]:
    """Format: najpierw pytania „1. Tytuł” + treść, potem odpowiedzi „1. Tytuł” + kroki.
    Druga seria numeracji od 1 (albo nagłówki „ad1.”, „ad2.”…) rozpoczyna odpowiedzi; tekst przed
    pierwszym nagłówkiem jest pomijany. Zwraca listę {number, title, question, reference_answer}
    do podglądu i poprawek."""
    questions: list[dict[str, Any]] = []
    answers: dict[int, list[str]] = {}
    in_answers = False
    ad_mode = False  # odpowiedzi oznaczone „adN.” – wtedy tylko takie wiersze są nagłówkami
    expected = 1
    current: list[str] | None = None
    current_number = 0

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        ad_number = _ad_heading(line) if questions else None
        if ad_number is not None and (ad_mode or not in_answers):
            in_answers = ad_mode = True
            current_number, current = ad_number, []
            answers[ad_number] = current
            continue
        if ad_mode:
            if current is not None:
                current.append(line)
            continue
        if not in_answers and questions and expected != 1:
            restart, title = _is_heading(line, 1, in_answers=True)
            if restart:
                in_answers, expected = True, 2
                current_number, current = 1, []
                answers[1] = current
                continue
        heading, title = _is_heading(line, expected, in_answers)
        if heading:
            expected += 1
            if in_answers:
                current_number = expected - 1
                current = []
                answers[current_number] = current
            else:
                current = []
                questions.append({"number": expected - 1, "title": title, "lines": current})
            continue
        if current is not None:
            current.append(line)

    items = []
    for q in questions:
        # Tytuł łamany na dwie linie: krótka pierwsza linia treści należy jeszcze do tytułu.
        body = list(q["lines"])
        title = q["title"]
        if (
            body
            and body[0].strip()
            and len(body[0].strip()) < 40
            and not body[0].strip().endswith(("?", "."))
        ):
            title = f"{title} {body.pop(0).strip()}"
        question = _join_question(body)
        if q is questions[-1] and "?" in question:
            # Wstęp przed odpowiedziami („Jasne. Uporządkuję to…”) nie należy do pytania.
            paragraphs = question.split("\n")
            last = max(i for i, p in enumerate(paragraphs) if "?" in p)
            question = "\n".join(paragraphs[: last + 1])
        items.append(
            {
                "number": q["number"],
                "title": title,
                "question": question,
                "reference_answer": _join_answer(answers.get(q["number"], [])),
            }
        )
    return items


def question_prompt(item: GoldsetItem) -> str:
    """Pytanie wysyłane do asystenta: tytuł przypadku + treść (jak napisałby lekarz)."""
    return f"{item.title}\n{item.question}".strip()


JUDGE_SYSTEM = (
    "Jesteś ekspertem logopedii oceniającym odpowiedź asystenta AI na pytanie lekarza. Porównaj "
    "odpowiedź z odpowiedzią wzorcową przygotowaną przez specjalistę. Oceń merytoryczną zgodność: "
    "czy odpowiedź zawiera kluczowe kroki i zalecenia wzorca, czy zachowuje właściwą kolejność "
    "postępowania (najpierw diagnostyka/przyczyna, potem funkcje, na końcu automatyzacja itp.), "
    "czy nie zawiera błędów lub zaleceń sprzecznych z wzorcem. Dodatkowe poprawne informacje nie "
    "obniżają oceny; pominięcia kluczowych kroków i błędy – tak. Skala: 5 – pełna zgodność; 4 – "
    "drobne braki; 3 – połowa kluczowych punktów lub zła kolejność; 2 – większość braków; "
    "1 – marginalna zgodność; 0 – odpowiedź błędna lub nie na temat. Zasady: najpierw wypisz "
    "kolejno punkty odpowiedzi wzorcowej i każdy przypisz DOKŁADNIE do jednej listy – covered "
    "albo missing (ten sam punkt nie może być w obu); w covered i missing umieszczaj tylko punkty "
    "WZORCA, nie dodatkowe treści asystenta; punkt jest pokryty, gdy odpowiedź wyraża tę samą "
    "myśl innymi słowami lub ogólniej, ale wciąż jednoznacznie. Zwróć WYŁĄCZNIE JSON: "
    '{"score": 0-5, "covered": ["punkty wzorca obecne w odpowiedzi"], '
    '"missing": ["punkty wzorca pominięte"], "order_ok": true|false, '
    '"errors": ["błędy lub zalecenia sprzeczne z wzorcem"], "comment": "1–2 zdania uzasadnienia"}'
)


def parse_verdict(raw: str) -> dict[str, Any]:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start : end + 1] if start != -1 and end > start else text)
    score = max(0.0, min(5.0, float(data.get("score", 0))))

    def strings(key: str) -> list[str]:
        return [str(v)[:300] for v in (data.get(key) or []) if str(v).strip()][:20]

    return {
        "score": score,
        "covered": strings("covered"),
        "missing": strings("missing"),
        "errors": strings("errors"),
        "order_ok": bool(data.get("order_ok", True)),
        "comment": str(data.get("comment", ""))[:1000],
    }


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def ask_assistant(question: str, user_id: int) -> dict[str, Any]:
    """Pytanie przez prawdziwy graf RAG czatu (bez kontekstu pacjenta i bez zapisu rozmowy)."""
    from .graph import rag_graph  # import lokalny: graf ładuje modele przy imporcie

    answer: list[str] = []
    sources: list[dict[str, Any]] = []
    tokens = 0
    state = {"user_id": user_id, "question": question, "history": [], "patient_context": None}
    async for chunk in rag_graph.astream(state, stream_mode="custom"):
        kind = chunk.get("type")
        if kind == "token":
            answer.append(chunk["text"])
        elif kind == "sources":
            sources = chunk["sources"]
        elif kind == "usage":
            tokens = int(chunk.get("total_tokens", 0))
    return {"answer": "".join(answer), "sources": sources, "tokens": tokens}


async def judge(item: GoldsetItem, answer: str, user_id: int) -> tuple[dict[str, Any], int]:
    completion = await llm.chat_complete(
        [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Pytanie lekarza:\n{question_prompt(item)}\n\n"
                    f"Odpowiedź wzorcowa:\n{item.reference_answer}\n\n"
                    f"Odpowiedź asystenta:\n{answer or '(brak odpowiedzi)'}"
                ),
            },
        ],
        user_id=user_id,
        operation="goldset_judge",
        temperature=0.0,
        max_tokens=700,
    )
    return parse_verdict(completion.text), completion.usage.total_tokens


async def similarity(answer: str, reference: str, user_id: int) -> float:
    if not answer.strip() or not reference.strip():
        return 0.0
    vectors, _ = await llm.embed(
        [answer[:8000], reference[:8000]], user_id=user_id, operation="goldset_similarity"
    )
    return round(cosine(vectors[0], vectors[1]), 4)


def settings_snapshot() -> dict[str, Any]:
    return {
        "chat_model": settings.vllm_chat_model,
        "embedding_model": settings.vllm_embedding_model,
        "reranker": settings.reranker_model,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_n": settings.rerank_top_n,
        "rerank_min_score": settings.rerank_min_score,
    }


_active: dict[int, asyncio.Task] = {}


def is_running(run_id: int) -> bool:
    task = _active.get(run_id)
    return task is not None and not task.done()


def any_running() -> bool:
    return any(not task.done() for task in _active.values())


async def _evaluate(run_id: int, item: GoldsetItem, user_id: int) -> GoldsetResult:
    result = GoldsetResult(
        run_id=run_id, item_id=item.id, title=item.title, question=question_prompt(item)
    )
    started = time.monotonic()
    try:
        reply = await ask_assistant(result.question, user_id)
        result.latency_ms = int((time.monotonic() - started) * 1000)
        result.answer = reply["answer"]
        result.sources = reply["sources"]
        result.tokens = reply["tokens"]
        verdict, judge_tokens = await judge(item, reply["answer"], user_id)
        result.score = verdict["score"]
        result.verdict = verdict
        result.judge_tokens = judge_tokens
        result.similarity = await similarity(reply["answer"], item.reference_answer, user_id)
        result.status = "ok"
    except Exception as exc:  # pojedyncze pytanie nie przerywa całego testu
        logger.exception("Goldset: błąd pytania %s", item.id)
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"[:500]
        result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
    return result


async def _run(run_id: int, item_ids: list[int], user_id: int) -> None:
    try:
        for item_id in item_ids:
            async with session_factory() as session:
                item = await session.get(GoldsetItem, item_id)
            if item is None:
                continue
            result = await _evaluate(run_id, item, user_id)
            async with session_factory() as session:
                session.add(result)
                run = await session.get(GoldsetRun, run_id)
                if run is not None:
                    run.done += 1
                    session.add(run)
                await session.commit()
        await _finish(run_id, "done")
    except asyncio.CancelledError:
        await _finish(run_id, "cancelled")
        raise
    except Exception:
        logger.exception("Goldset: przebieg %s przerwany", run_id)
        await _finish(run_id, "failed")


async def _finish(run_id: int, status: str) -> None:
    async with session_factory() as session:
        run = await session.get(GoldsetRun, run_id)
        if run is None:
            return
        results = (
            await session.exec(select(GoldsetResult).where(GoldsetResult.run_id == run_id))
        ).all()
        ok = [r for r in results if r.status == "ok"]
        run.status = status
        run.finished_at = utcnow()
        run.avg_score = round(sum(r.score for r in ok) / len(ok), 3) if ok else None
        run.avg_similarity = round(sum(r.similarity for r in ok) / len(ok), 4) if ok else None
        run.avg_latency_ms = int(sum(r.latency_ms for r in ok) / len(ok)) if ok else None
        run.total_tokens = sum(r.tokens + r.judge_tokens for r in results)
        run.errors = len(results) - len(ok)
        session.add(run)
        await session.commit()


async def start_run(user_id: int, item_ids: list[int] | None = None, note: str = "") -> GoldsetRun:
    async with session_factory() as session:
        query = select(GoldsetItem.id).order_by(col(GoldsetItem.position), col(GoldsetItem.id))
        ids = [i for i in (await session.exec(query)).all() if i is not None]
        if item_ids:
            wanted = set(item_ids)
            ids = [i for i in ids if i in wanted]
        run = GoldsetRun(
            started_by=user_id, total=len(ids), settings=settings_snapshot(), note=note.strip()
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
    task = asyncio.create_task(_run(run.id, ids, user_id))  # type: ignore[arg-type]
    _active[run.id] = task  # type: ignore[index]
    return run


def cancel_run(run_id: int) -> bool:
    task = _active.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True
