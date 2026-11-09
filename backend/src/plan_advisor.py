"""Propozycja następnego kroku planu działania (LLM + baza wiedzy RAG).

Kontekst: dane pacjenta, zatwierdzony wywiad, wszystkie dotychczasowe kroki planu (ze statusami)
i ostatnie notatki z sesji. Fragmenty bazy wiedzy wyszukiwane jak w czacie (hybrydowo + reranker).
Model zwraca JEDEN krok: uzupełnienie diagnostyki albo kolejny etap terapii – lekarz decyduje,
czy go użyć. Anonimizacja (imiona, PESEL, telefon, adres) jak w każdym wywołaniu – w src.llm.
"""

import json
import logging
import re
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from . import llm
from .database import Patient, PatientNote, PlanStep, User
from .vector_store import reranker, vector_store

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "planned": "zaplanowany",
    "completed": "zakończony",
    "suspended": "zawieszony",
    "infeasible": "niewykonalny",
}
KINDS = {"diagnostics", "therapy"}
RECENT_NOTES = 5
NOTE_CHARS = 800

SYSTEM = (
    "Jesteś doświadczonym logopedą-konsultantem wspierającym lekarza prowadzącego. Na "
    "podstawie kontekstu pacjenta (dane, wywiad, dotychczasowy plan działania ze statusami "
    "kroków, notatki z sesji) oraz fragmentów bazy wiedzy zaproponuj JEDEN najbardziej "
    "uzasadniony następny krok planu. Najpierw oceń, czy brakuje informacji lub badań (np. "
    "słuch, konsultacja laryngologiczna, ortodontyczna, neurologiczna, ocena wędzidełka, "
    "diagnoza integracji sensorycznej) – jeśli tak, zaproponuj uzupełnienie diagnostyki; w "
    "przeciwnym razie zaproponuj kolejny etap terapii, który logicznie wynika z kroków "
    "zakończonych i nie powtarza kroków już zaplanowanych. Uwzględnij kroki zawieszone i "
    "niewykonalne (nie proponuj ich ponownie bez zmiany podejścia). Opieraj się na "
    "fragmentach bazy wiedzy i wskazuj je numerami [n]; nie zmyślaj faktów. Pisz po polsku,"
    " językiem zawodowym, konkretnie (cel, ćwiczenia lub badania, częstotliwość, kryterium "
    "zakończenia). Dane osobowe są zanonimizowane – znaczniki typu [IMIĘ PACJENTA] traktuj "
    "jak zwykłe odniesienia. Zwróć WYŁĄCZNIE obiekt JSON bez komentarzy i bez bloku kodu: "
    '{"kind": "diagnostics" | "therapy", "title": "krótka nazwa kroku (do 80 znaków)", '
    '"description": "opis kroku (3–8 zdań lub punktów)", '
    '"rationale": "dlaczego teraz – odniesienie do kontekstu pacjenta (1–3 zdania)", '
    '"sources": [numery wykorzystanych fragmentów]}'
)


def plan_lines(steps: list[PlanStep]) -> list[str]:
    lines = []
    for number, step in enumerate(steps, start=1):
        lines.append(
            f"{number}. {step.title} – status: {STATUS_LABELS.get(step.status, step.status)}"
        )
        if step.description:
            lines.append(f"   {step.description}")
    return lines


def search_query(patient: Patient, steps: list[PlanStep]) -> str:
    """Zapytanie do bazy wiedzy: rozpoznanie, ICD i bieżący etap terapii."""
    parts = ["terapia logopedyczna kolejny etap postępowanie"]
    parts += [p for p in (patient.diagnosis, patient.icd_code) if p]
    active = [s.title for s in steps if s.status in {"planned", "completed"}][-3:]
    parts += active
    if patient.description:
        parts.append(patient.description[:300])
    return " ".join(parts)


def parse_suggestion(raw: str, sources_count: int) -> dict[str, Any]:
    """Wyciąga JSON z odpowiedzi modelu (toleruje blok ```json i tekst wokół)."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    title = str(data.get("title", "")).strip()[:200]
    if not title:
        raise ValueError("Brak nazwy kroku w odpowiedzi modelu")
    kind = str(data.get("kind", "therapy")).strip().lower()
    sources = []
    for value in data.get("sources") or []:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= sources_count and index not in sources:
            sources.append(index)
    return {
        "kind": kind if kind in KINDS else "therapy",
        "title": title,
        "description": str(data.get("description", "")).strip()[:5000],
        "rationale": str(data.get("rationale", "")).strip()[:2000],
        "sources": sources,
    }


async def suggest_next_step(
    session: AsyncSession, patient: Patient, doctor: User, patient_context: str
) -> dict[str, Any]:
    steps = list(
        (
            await session.exec(
                select(PlanStep)
                .where(PlanStep.patient_id == patient.id)
                .order_by(col(PlanStep.position), col(PlanStep.id))
            )
        ).all()
    )
    notes = list(
        (
            await session.exec(
                select(PatientNote)
                .where(PatientNote.patient_id == patient.id, PatientNote.user_id == doctor.id)
                .order_by(col(PatientNote.created_at).desc())
                .limit(RECENT_NOTES)
            )
        ).all()
    )

    query = search_query(patient, steps)
    vectors, _ = await llm.embed([query], user_id=doctor.id, operation="embedding_query")
    candidates = await vector_store.hybrid_search(
        query, vectors[0], filters=None, user_id=doctor.id
    )
    documents = await reranker.rerank(query, candidates)

    parts = []
    if documents:
        parts.append(
            "Fragmenty bazy wiedzy:\n"
            + "\n\n".join(
                f"[{i}] {d['title']}\n{d['text']}" for i, d in enumerate(documents, start=1)
            )
        )
    else:
        parts.append("Fragmenty bazy wiedzy: brak trafień – zaznacz, że propozycja nie ma źródeł.")
    parts.append("Kontekst pacjenta (zanonimizowany):\n" + (patient_context or "(brak danych)"))
    parts.append(
        "Dotychczasowy plan działania:\n" + ("\n".join(plan_lines(steps)) or "(plan jest pusty)")
    )
    if notes:
        parts.append(
            "Ostatnie notatki z sesji (od najnowszej):\n"
            + "\n".join(f"- {n.created_at:%d.%m.%Y}: {n.content[:NOTE_CHARS]}" for n in notes)
        )
    parts.append("Zaproponuj następny krok planu działania (JSON).")

    completion = await llm.chat_complete(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}],
        user_id=doctor.id,
        operation="plan_suggestion",
        temperature=0.3,
        max_tokens=900,
    )
    suggestion = parse_suggestion(completion.text, len(documents))
    suggestion["sources"] = [
        {
            "index": i,
            "title": documents[i - 1]["title"],
            "snippet": documents[i - 1]["text"][:240],
        }
        for i in suggestion["sources"]
    ]
    suggestion["grounded"] = bool(documents)
    return suggestion
