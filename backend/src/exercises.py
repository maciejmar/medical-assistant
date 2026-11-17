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
from .database import (
    KbDocument,
    KbExercise,
    KbExerciseAlias,
    KbPrivateDocument,
    session_factory,
    utcnow,
)

logger = logging.getLogger(__name__)

# Mniejsze okna = mniej ćwiczeń na wywołanie; przy 6000 zn. model pomijał część krótkich
# ćwiczeń (luki w numeracji: „karuzela”, „huśtawka 2”, „niania”…).
WINDOW_CHARS = 3500
WINDOW_OVERLAP = 1000
MATCH_THRESHOLD = 0.8
_ORDINALS = {
    "pierwsza": "1",
    "pierwszy": "1",
    "druga": "2",
    "drugi": "2",
    "trzecia": "3",
    "trzeci": "3",
    "czwarta": "4",
    "czwarty": "4",
}

# Znaczniki katalogu ćwiczeń w tekście (także z typowymi błędami OCR, np. „OTRZEBNE”).
_MARKERS = re.compile(
    r"OPIS\s+TECHNIKI|OPIS\s+[ĆC]WICZENIA|P?OTRZEBNE\s+NARZ|SPOS[ÓO]B\s+WYKONANIA|\bCEL\s*:",
    re.IGNORECASE,
)
_PAGE = re.compile(r"#\s*Strona\s+(\d+)", re.IGNORECASE)

EXTRACT_SYSTEM = (
    "Wyodrębniasz katalog ćwiczeń i technik terapeutycznych z fragmentu materiału logopedycznego. "
    "Tekst pochodzi z OCR skanu i może zawierać błędy rozpoznawania (ucięte, zlepione lub "
    "przekręcone słowa, brakujące litery). Zasady: (1) wypisz WSZYSTKIE ćwiczenia/techniki, które "
    "we fragmencie mają nazwę oraz cel lub opis wykonania – także bardzo krótkie i kolejne "
    "o podobnych nazwach (np. „Huśtawka” i „Huśtawka 2” to dwa ćwiczenia); nie pomijaj żadnego "
    "numeru z kolejnej numeracji; (2) nazwa bez numeru i bez cudzysłowów, "
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
    """Klucz dopasowania: małe litery, bez diakrytyków, cudzysłowów i interpunkcji;
    liczebniki porządkowe jako cyfry („wersja druga” = „wersja 2”)."""
    text = unicodedata.normalize("NFKD", name.lower().replace("ł", "l"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_ORDINALS.get(t, t) for t in re.sub(r"[^a-z0-9]+", " ", text).split())


def clean_name(name: str) -> str:
    """Porządkuje nazwę z OCR/modelu: bez cudzysłowów, bez powtórzeń „Pompka. Pompka”."""
    name = re.sub(r"[„”\"“«»]", "", name).strip(" '.")
    repeated = re.match(r"^(.{3,}?)\.\s+(.+)$", name)
    if repeated and repeated.group(2).lower().startswith(repeated.group(1).lower()):
        name = repeated.group(2)
    return " ".join(name.split())


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
        name = clean_name(str(item.get("name") or ""))
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


async def delete_document_exercises(session, document_ids: list[int]) -> None:
    """Usuwa ćwiczenia (i ich aliasy) dokumentów – przed usunięciem samych dokumentów."""
    ids = select(KbExercise.id).where(col(KbExercise.document_id).in_(document_ids))
    await session.exec(delete(KbExerciseAlias).where(col(KbExerciseAlias.exercise_id).in_(ids)))
    await session.exec(delete(KbExercise).where(col(KbExercise.document_id).in_(document_ids)))


async def save_document_exercises(document_id: int, items: list[dict[str, Any]]) -> int:
    """Zastępuje niesprawdzone ćwiczenia dokumentu; sprawdzone i te z aliasami zostają."""
    async with session_factory() as session:
        with_alias = select(KbExerciseAlias.exercise_id)
        protected = (col(KbExercise.verified).is_(True)) | (col(KbExercise.id).in_(with_alias))
        kept_keys = (
            await session.exec(
                select(KbExercise.key).where(KbExercise.document_id == document_id, protected)
            )
        ).all()
        await session.exec(
            delete(KbExercise).where(col(KbExercise.document_id) == document_id, ~protected)
        )
        kept = set(kept_keys)
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


SHORT_VARIANT_FACTOR = 0.95
_DESCRIPTION_WORDS = 4  # dopisek po „ – ” od tylu słów to opis, a nie część nazwy


def _candidates(name: str) -> list[tuple[str, float]]:
    """(wariant nazwy, mnożnik oceny). Pełna nazwa zawsze; sama nazwa bez dopisku tylko wtedy,
    gdy dopisek wygląda na opis („„glonojad” – zassanie języka jak najdłużej…”). Krótkie
    dopiski („ćwiczenia oporowe – czubek języka”, „„grot” na boki”) są częścią nazwy – inaczej
    trafiałyby w ogólne „Ćwiczenia oporowe” / „Grot”."""
    options = [(name, 1.0)]
    quoted = re.match(r"^\s*[„\"“]([^”\"“]+)[”\"“](.*)$", name)
    if quoted and len(normalize_name(quoted.group(2)).split()) >= _DESCRIPTION_WORDS:
        options.append((quoted.group(1), SHORT_VARIANT_FACTOR))
    for sep in (" – ", " - ", " (", ": "):
        head, found, rest = name.partition(sep)
        if found and len(normalize_name(rest).split()) >= _DESCRIPTION_WORDS:
            options.append((head, SHORT_VARIANT_FACTOR))
    return [(o, f) for o, f in options if normalize_name(o)]


def _stems(key: str) -> set[str]:
    # 5 pierwszych liter: „horyzontalnym” = „horyzontalnie”, „oporem” = „oporowe” itp.
    return {token[:5] for token in key.split()}


def name_similarity(a: str, b: str) -> float:
    """Podobieństwo kluczy: średnia z podobieństwa znaków i wspólnych słów. Obie miary muszą
    być wysokie, więc nazwa z dodatkowymi słowami („stymulacja punktowa zewnętrzna mięśni
    żwaczy”) nie trafia w krótszą, inną („stymulacja punktowa zewnętrzna”). Różne numery
    („huśtawka 2” ≠ „huśtawka”) obniżają ocenę."""
    if a == b:
        return 1.0
    chars = difflib.SequenceMatcher(None, a, b).ratio()
    sa, sb = _stems(a), _stems(b)
    words = len(sa & sb) / max(len(sa), len(sb))
    score = (chars + words) / 2
    if {t for t in a.split() if t.isdigit()} != {t for t in b.split() if t.isdigit()}:
        score *= 0.6
    return score


def best_match(name: str, keys: list[str]) -> tuple[str | None, float]:
    best_key, best_score = None, 0.0
    for option, factor in _candidates(name):
        key = normalize_name(option)
        for candidate in keys:
            score = name_similarity(key, candidate) * factor
            if score > best_score:
                best_key, best_score = candidate, score
    if best_score < MATCH_THRESHOLD:
        return None, 0.0
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


async def aliases_by_exercise(session, exercise_ids: list[int]) -> dict[int, list[KbExerciseAlias]]:
    rows = await session.exec(
        select(KbExerciseAlias)
        .where(col(KbExerciseAlias.exercise_id).in_(exercise_ids))
        .order_by(col(KbExerciseAlias.id))
    )
    result: dict[int, list[KbExerciseAlias]] = {}
    for alias in rows.all():
        result.setdefault(alias.exercise_id, []).append(alias)
    return result


async def match_names(
    session, names: list[str], user_id: int | None = None
) -> list[dict[str, Any]]:
    """Alias przypisany przez administratora ma pierwszeństwo (ocena 1,0), potem nazwy."""
    exercises = await visible_exercises(session, user_id)
    by_id = {e.id: e for e in exercises}
    by_key: dict[str, KbExercise] = {}
    for exercise in exercises:  # sprawdzone mają pierwszeństwo przy tej samej nazwie
        if exercise.key not in by_key or (exercise.verified and not by_key[exercise.key].verified):
            by_key[exercise.key] = exercise
    alias_rows = await aliases_by_exercise(session, list(by_id))  # type: ignore[arg-type]
    by_alias = {a.key: by_id[a.exercise_id] for rows in alias_rows.values() for a in rows}
    keys = list(by_key)
    results = []
    for name in names:
        alias_hit = by_alias.get(normalize_name(name))
        if alias_hit is not None:
            results.append({"name": name, "exercise": alias_hit, "score": 1.0, "alias": True})
            continue
        key, score = best_match(name, keys)
        exercise = by_key.get(key) if key else None
        results.append({"name": name, "exercise": exercise, "score": score, "alias": False})
    return results


async def assign_alias(session, exercise: KbExercise, name: str) -> KbExerciseAlias:
    """Przypisuje nazwę do ćwiczenia (przenosi, jeśli była przypisana gdzie indziej);
    ćwiczenie staje się sprawdzone – ponowne wyodrębnianie go nie usunie."""
    key = normalize_name(name)
    alias = (await session.exec(select(KbExerciseAlias).where(KbExerciseAlias.key == key))).first()
    if alias is None:
        alias = KbExerciseAlias(exercise_id=exercise.id, alias=name.strip()[:300], key=key)  # type: ignore[arg-type]
    else:
        alias.exercise_id, alias.alias = exercise.id, name.strip()[:300]  # type: ignore[assignment]
    exercise.verified = True
    exercise.updated_at = utcnow()
    session.add(alias)
    session.add(exercise)
    await session.commit()
    await session.refresh(alias)
    return alias


def touch(exercise: KbExercise) -> None:
    exercise.key = normalize_name(exercise.name)
    exercise.updated_at = utcnow()
