"""Katalog ćwiczeń: wyodrębnianie ćwiczeń/technik z dokumentów bazy wiedzy i dopasowanie nazw.

Dlaczego osobny katalog: RAG tnie tekst na fragmenty ~1500 znaków, więc opis ćwiczenia bywa
rozcięty (nagłówek w jednym fragmencie, opis w następnym), a reranker słabo radzi sobie z polskimi
nazwami ćwiczeń. Szablony z zamkniętą listą ćwiczeń potrzebują pełnych, dokładnych opisów –
dlatego każde ćwiczenie trafia do jednego rekordu `kb_exercises`.

Wyodrębnianie (jednorazowe, uruchamiane przez administratora): tekst dokumentu dzielony jest na
zachodzące na siebie okna, model zwraca ćwiczenia w JSON (z poprawą oczywistych błędów OCR, bez
dopisywania treści), duplikaty z zakładek okien są scalane (pełny opis wygrywa z uciętym).
Rekordy oznaczone przez administratora jako sprawdzone nie są nadpisywane.
"""

import asyncio
import difflib
import json
import logging
import re
import unicodedata
from typing import Any

from sqlmodel import col, delete, select

from . import llm
from .database import KbDocument, KbExercise, KbPrivateDocument, session_factory, utcnow

logger = logging.getLogger(__name__)

WINDOW_CHARS = 6000
WINDOW_OVERLAP = 1500
MATCH_THRESHOLD = 0.86

# Znaczniki katalogu ćwiczeń w tekście (także z typowymi błędami OCR, np. „OTRZEBNE”).
_MARKERS = re.compile(
    r"OPIS\s+TECHNIKI|OPIS\s+[ĆC]WICZENIA|P?OTRZEBNE\s+NARZ|SPOS[ÓO]B\s+WYKONANIA|\bCEL\s*:",
    re.IGNORECASE,
)
_PAGE = re.compile(r"#\s*Strona\s+(\d+)", re.IGNORECASE)

EXTRACT_SYSTEM = (
    "Wyodrębniasz katalog ćwiczeń i technik terapeutycznych z fragmentu materiału logopedycznego. "
    "Tekst pochodzi z OCR skanu i może zawierać błędy rozpoznawania (ucięte, zlepione lub "
    "przekręcone słowa, brakujące litery). Zasady: (1) uwzględnij tylko ćwiczenia/techniki, które "
    "we fragmencie mają nazwę oraz cel lub opis wykonania; (2) nazwa bez numeru i bez cudzysłowów, "
    "w brzmieniu z tekstu; (3) popraw wyłącznie oczywiste błędy OCR – NIE dodawaj informacji spoza "
    "fragmentu, nie uzupełniaj kroków ani parametrów z własnej wiedzy; (4) opis przepisz wiernie "
    "(możesz go uporządkować w zdania lub punkty); (5) page = numer z najbliższego wcześniejszego "
    "znacznika „# Strona N” (null, jeśli brak); (6) complete = false, gdy opis urywa się na końcu "
    'fragmentu albo ćwiczenie zaczyna się przed jego początkiem; (7) brakujące pole = "". '
    'Zwróć WYŁĄCZNIE JSON: {"exercises": [{"number": "22", "name": "...", "page": 126, '
    '"goal": "...", "tools": "...", "description": "...", "complete": true}]}. '
    'Gdy we fragmencie nie ma ćwiczeń: {"exercises": []}.'
)


def normalize_name(name: str) -> str:
    """Klucz dopasowania: małe litery, bez diakrytyków, cudzysłowów i interpunkcji."""
    text = unicodedata.normalize("NFKD", name.lower().replace("ł", "l"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def marker_count(text: str) -> int:
    return len(_MARKERS.findall(text or ""))


def windows(text: str, size: int = WINDOW_CHARS, overlap: int = WINDOW_OVERLAP) -> list[str]:
    """Zachodzące okna tekstu; cięcie w miarę możliwości na końcu wiersza."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            newline = text.rfind("\n", start + size // 2, end)
            end = newline if newline > start else end
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return parts


def _page_before(window: str) -> str:
    """Kontekst strony dla okna zaczynającego się w środku strony."""
    match = _PAGE.search(window)
    return "" if match and match.start() < 50 else "(okno zaczyna się w środku strony)\n"


def parse_extraction(raw: str) -> list[dict[str, Any]]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    items = data.get("exercises") if isinstance(data, dict) else None
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().strip("„”\"'«» ").strip()
        description = str(item.get("description") or "").strip()
        goal = str(item.get("goal") or "").strip()
        if not name or not normalize_name(name) or not (description or goal):
            continue
        page = item.get("page")
        result.append(
            {
                "number": str(item.get("number") or "").strip()[:20],
                "name": name[:300],
                "page": int(page) if isinstance(page, int | float) or str(page).isdigit() else None,
                "goal": goal,
                "tools": str(item.get("tools") or "").strip(),
                "description": description,
                "complete": bool(item.get("complete", True)),
            }
        )
    return result


def merge_exercises(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scala duplikaty z zakładek okien: pełny opis przed uciętym, potem dłuższy."""
    best: dict[str, dict[str, Any]] = {}
    for item in found:
        key = normalize_name(item["name"])
        current = best.get(key)
        rank = (item["complete"], len(item["description"]) + len(item["goal"]))
        if current is None or rank > (
            current["complete"],
            len(current["description"]) + len(current["goal"]),
        ):
            best[key] = {**item, "page": item["page"] or (current or {}).get("page")}
    return list(best.values())


# --- zadanie w tle (jedno naraz) ---

_job: dict[str, Any] | None = None
_task: asyncio.Task | None = None


def job_status() -> dict[str, Any] | None:
    return dict(_job) if _job else None


def is_running() -> bool:
    return _task is not None and not _task.done()


PARALLEL_WINDOWS = 4


async def _extract_window(doc: KbDocument, window: str, user_id: int) -> list[dict[str, Any]]:
    if marker_count(window) == 0:  # okno bez znaczników katalogu – bez wywołania modelu
        _job["done_windows"] += 1  # type: ignore[index]
        return []
    completion = await llm.chat_complete(
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": f"Dokument: {doc.title}\n{_page_before(window)}\n{window}"},
        ],
        user_id=user_id,
        operation="exercise_extraction",
        temperature=0.0,
        max_tokens=4000,
    )
    _job["done_windows"] += 1  # type: ignore[index]
    _job["tokens"] += completion.usage.total_tokens  # type: ignore[index]
    return parse_extraction(completion.text)


async def _extract_document(doc: KbDocument, user_id: int) -> list[dict[str, Any]]:
    limit = asyncio.Semaphore(PARALLEL_WINDOWS)

    async def guarded(window: str) -> list[dict[str, Any]]:
        async with limit:
            return await _extract_window(doc, window, user_id)

    batches = await asyncio.gather(*(guarded(w) for w in windows(doc.text)))
    return merge_exercises([item for batch in batches for item in batch])


async def save_document_exercises(document_id: int, items: list[dict[str, Any]]) -> int:
    """Zastępuje niesprawdzone ćwiczenia dokumentu; sprawdzone zostają nietknięte."""
    async with session_factory() as session:
        verified = (
            await session.exec(
                select(KbExercise.key).where(
                    KbExercise.document_id == document_id, col(KbExercise.verified).is_(True)
                )
            )
        ).all()
        await session.exec(
            delete(KbExercise).where(
                col(KbExercise.document_id) == document_id, col(KbExercise.verified).is_(False)
            )
        )
        kept = set(verified)
        added = 0
        for item in items:
            key = normalize_name(item["name"])
            if key in kept:
                continue
            kept.add(key)
            session.add(KbExercise(document_id=document_id, key=key, **item))
            added += 1
        await session.commit()
    return added


async def _run(document_ids: list[int], user_id: int) -> None:
    assert _job is not None
    try:
        for document_id in document_ids:
            async with session_factory() as session:
                doc = await session.get(KbDocument, document_id)
            if doc is None:
                continue
            _job["current"] = doc.title
            items = await _extract_document(doc, user_id)
            _job["found"] += await save_document_exercises(document_id, items)
        _job["status"] = "done"
    except asyncio.CancelledError:
        _job["status"] = "cancelled"
        raise
    except Exception as exc:
        logger.exception("Katalog ćwiczeń: wyodrębnianie przerwane")
        _job["status"] = "failed"
        _job["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        _job["current"] = ""
        _job["finished_at"] = utcnow().isoformat()


async def start_extraction(document_ids: list[int], user_id: int) -> dict[str, Any]:
    global _job, _task
    async with session_factory() as session:
        docs = (
            await session.exec(select(KbDocument).where(col(KbDocument.id).in_(document_ids)))
        ).all()
    total = sum(len(windows(d.text)) for d in docs)
    _job = {
        "status": "running",
        "document_ids": [d.id for d in docs],
        "total_windows": total,
        "done_windows": 0,
        "found": 0,
        "tokens": 0,
        "current": "",
        "error": None,
        "started_at": utcnow().isoformat(),
        "finished_at": None,
    }
    _task = asyncio.create_task(_run([d.id for d in docs], user_id))  # type: ignore[misc]
    return dict(_job)


def cancel_extraction() -> bool:
    if not is_running():
        return False
    _task.cancel()  # type: ignore[union-attr]
    return True


# --- dopasowanie nazw ---

_BULLET = re.compile(r"^\s*(?:[•\-–*·]|\d+[.)])\s*")


def names_from_text(text: str) -> list[str]:
    """Nazwy z wklejonej listy (punktory, numeracja, przecinki na końcu wierszy są pomijane)."""
    names = []
    for line in text.splitlines():
        name = _BULLET.sub("", line).strip().rstrip(",.;").strip()
        if name and not name.isupper() and not name.endswith(":"):
            names.append(name)
    return names


def _candidates(name: str) -> list[str]:
    """Pełna nazwa, a dla „„glonojad” – zassanie języka…” także sama część przed opisem."""
    options = [name]
    quoted = re.match(r"^\s*[„\"“]([^”\"“]+)[”\"“]", name)
    if quoted:
        options.append(quoted.group(1))
    for sep in (" – ", " - ", " (", ": "):
        if sep in name:
            options.append(name.split(sep, 1)[0])
    return [o for o in options if normalize_name(o)]


def best_match(name: str, keys: list[str]) -> tuple[str | None, float]:
    best_key, best_score = None, 0.0
    for option in _candidates(name):
        key = normalize_name(option)
        if key in keys:
            return key, 1.0
        for close in difflib.get_close_matches(key, keys, n=1, cutoff=MATCH_THRESHOLD):
            score = difflib.SequenceMatcher(None, key, close).ratio()
            if score > best_score:
                best_key, best_score = close, score
    return best_key, round(best_score, 3)


async def visible_exercises(session, user_id: int | None = None) -> list[KbExercise]:
    """user_id=None (administrator) – wszystkie; inaczej wspólne + prywatne tego użytkownika."""
    query = select(KbExercise)
    if user_id is not None:
        others_private = select(KbPrivateDocument.document_id).where(
            KbPrivateDocument.owner_id != user_id
        )
        query = query.where(col(KbExercise.document_id).not_in(others_private))
    return list((await session.exec(query.order_by(col(KbExercise.id)))).all())


async def match_names(
    session, names: list[str], user_id: int | None = None
) -> list[dict[str, Any]]:
    exercises = await visible_exercises(session, user_id)
    by_key: dict[str, KbExercise] = {}
    for exercise in exercises:  # sprawdzone mają pierwszeństwo przy tej samej nazwie
        if exercise.key not in by_key or (exercise.verified and not by_key[exercise.key].verified):
            by_key[exercise.key] = exercise
    keys = list(by_key)
    results = []
    for name in names:
        key, score = best_match(name, keys)
        results.append({"name": name, "exercise": by_key.get(key) if key else None, "score": score})
    return results


def touch(exercise: KbExercise) -> None:
    exercise.key = normalize_name(exercise.name)
    exercise.updated_at = utcnow()
