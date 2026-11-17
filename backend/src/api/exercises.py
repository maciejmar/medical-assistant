"""Katalog ćwiczeń (panel administratora): wyodrębnianie z bazy wiedzy, przegląd, edycja,
sprawdzanie listy nazw (np. z szablonu etapu terapii) względem katalogu."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func
from sqlmodel import col, select

from .. import exercises
from ..auth import CurrentAdmin, SessionDep
from ..database import KbDocument, KbExercise
from .schemas import (
    ExerciseCandidateOut,
    ExerciseIn,
    ExerciseMatchIn,
    ExerciseMatchOut,
    ExerciseOut,
    ExtractionIn,
    ExtractionStatusOut,
)

router = APIRouter(prefix="/admin/exercises", tags=["exercises"])


async def _titles(session: SessionDep) -> dict[int, str]:
    rows = await session.exec(select(KbDocument.id, KbDocument.title))
    return {doc_id: title for doc_id, title in rows.all() if doc_id is not None}


def _out(exercise: KbExercise, titles: dict[int, str]) -> ExerciseOut:
    out = ExerciseOut.model_validate(exercise)
    out.document_title = titles.get(exercise.document_id, "")
    return out


@router.get("/candidates", response_model=list[ExerciseCandidateOut])
async def candidates(session: SessionDep, admin: CurrentAdmin) -> list[ExerciseCandidateOut]:
    """Dokumenty, w których widać katalog ćwiczeń (znaczniki „CEL:”, „OPIS TECHNIKI”…),
    oraz te, z których już wyodrębniono ćwiczenia."""
    counts = dict(
        (
            await session.exec(
                select(KbExercise.document_id, func.count()).group_by(KbExercise.document_id)
            )
        ).all()
    )
    docs = (await session.exec(select(KbDocument.id, KbDocument.title, KbDocument.text))).all()
    result = []
    for doc_id, title, text in docs:
        markers = exercises.marker_count(text)
        if markers or counts.get(doc_id):
            result.append(
                ExerciseCandidateOut(
                    document_id=doc_id,  # type: ignore[arg-type]
                    title=title,
                    markers=markers,
                    exercises=counts.get(doc_id, 0),
                )
            )
    return sorted(result, key=lambda c: (-c.markers, c.title))


@router.get("/extract", response_model=ExtractionStatusOut | None)
async def extraction_status(admin: CurrentAdmin) -> dict | None:
    return exercises.job_status()


@router.post("/extract", response_model=ExtractionStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def extract(body: ExtractionIn, admin: CurrentAdmin) -> dict:
    """Wyodrębnianie w tle (postęp: GET /extract); koszt LLM – w kredytach administratora."""
    if exercises.is_running():
        raise HTTPException(status.HTTP_409_CONFLICT, "Wyodrębnianie jest już w toku")
    return await exercises.start_extraction(body.document_ids, admin.id)  # type: ignore[arg-type]


@router.post("/extract/cancel", response_model=ExtractionStatusOut)
async def cancel(admin: CurrentAdmin) -> dict:
    if not exercises.cancel_extraction():
        raise HTTPException(status.HTTP_409_CONFLICT, "Wyodrębnianie nie jest w toku")
    return exercises.job_status()  # type: ignore[return-value]


@router.get("", response_model=list[ExerciseOut])
async def list_exercises(
    session: SessionDep, admin: CurrentAdmin, document_id: int | None = None
) -> list[ExerciseOut]:
    query = select(KbExercise)
    if document_id is not None:
        query = query.where(KbExercise.document_id == document_id)
    rows = await session.exec(
        query.order_by(col(KbExercise.document_id), col(KbExercise.page), col(KbExercise.id))
    )
    titles = await _titles(session)
    return [_out(e, titles) for e in rows.all()]


@router.put("/{exercise_id}", response_model=ExerciseOut)
async def update_exercise(
    exercise_id: int, body: ExerciseIn, session: SessionDep, admin: CurrentAdmin
) -> ExerciseOut:
    exercise = await session.get(KbExercise, exercise_id)
    if exercise is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono ćwiczenia")
    for field, value in body.model_dump().items():
        setattr(exercise, field, value.strip() if isinstance(value, str) else value)
    exercises.touch(exercise)
    if not exercise.key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj nazwę ćwiczenia")
    session.add(exercise)
    await session.commit()
    await session.refresh(exercise)
    return _out(exercise, await _titles(session))


@router.delete("/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exercise(exercise_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    exercise = await session.get(KbExercise, exercise_id)
    if exercise is not None:
        await session.delete(exercise)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/match", response_model=list[ExerciseMatchOut])
async def match(
    body: ExerciseMatchIn, session: SessionDep, admin: CurrentAdmin
) -> list[ExerciseMatchOut]:
    """Sprawdza wklejoną listę nazw (np. bazę ćwiczeń etapu) – które mają opis w katalogu."""
    names = exercises.names_from_text(body.text)
    if not names:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nie znaleziono nazw na liście")
    titles = await _titles(session)
    return [
        ExerciseMatchOut(
            name=r["name"],
            score=r["score"],
            exercise=_out(r["exercise"], titles) if r["exercise"] else None,
        )
        for r in await exercises.match_names(session, names)
    ]
