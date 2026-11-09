"""Wywiad pacjenta: pytania z szablonu (edytuje administrator) i własne pytania lekarza,
odpowiedzi wpisywane ręcznie lub nagrywane w gabinecie (zapis audio + transkrypcja Whisper).

Do kontekstu LLM trafia wyłącznie ostatnia ZATWIERDZONA wersja wywiadu (migawka w
patient_interviews.approved_items); anonimizację imion, PESEL-u, telefonu i adresu robi src.llm.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlmodel import col, delete, func, select

from ..auth import CurrentAdmin, CurrentDoctor, SessionDep
from ..database import (
    InterviewAudio,
    InterviewItem,
    InterviewTemplate,
    PatientInterview,
    User,
    utcnow,
)
from ..stt import TranscriptionError, transcribe_audio
from .audio import read_audio_upload
from .patients import get_owned_patient
from .schemas import (
    InterviewItemOut,
    InterviewOut,
    InterviewQuestionIn,
    InterviewRecordingOut,
    InterviewSaveIn,
    InterviewTemplateIn,
    InterviewTemplateOut,
)

router = APIRouter(tags=["interview"])

SECTION_PREFIX = "## "
TEMPLATE_FILE = Path(__file__).resolve().parent.parent / "interview_template.txt"


def load_default_questions(path: Path = TEMPLATE_FILE) -> list[str]:
    """Domyślny szablon z pliku tekstowego: jedno pytanie w wierszu, „## ” = nagłówek sekcji,
    „# ” = komentarz, puste wiersze pomijane."""
    questions = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = " ".join(raw.split())
        if not line or (line.startswith("# ") and not line.startswith(SECTION_PREFIX)):
            continue
        questions.append(line)
    return questions


def is_section(question: str) -> bool:
    return question.startswith(SECTION_PREFIX)


DEFAULT_QUESTIONS: list[str] = load_default_questions()

_TEMPLATE_ID = 1


def _clean_questions(questions: list[str]) -> list[str]:
    cleaned = [" ".join(q.split()) for q in questions]
    return [q[:2000] for q in cleaned if q]


async def template_questions(session: SessionDep) -> tuple[list[str], InterviewTemplate | None]:
    row = await session.get(InterviewTemplate, _TEMPLATE_ID)
    if row is None:
        return list(DEFAULT_QUESTIONS), None
    return [str(q) for q in row.questions], row


@router.get("/admin/interview-template", response_model=InterviewTemplateOut)
async def get_template(session: SessionDep, admin: CurrentAdmin) -> InterviewTemplateOut:
    questions, row = await template_questions(session)
    return InterviewTemplateOut(
        questions=questions, is_default=row is None, updated_at=row.updated_at if row else None
    )


@router.put("/admin/interview-template", response_model=InterviewTemplateOut)
async def save_template(
    body: InterviewTemplateIn, session: SessionDep, admin: CurrentAdmin
) -> InterviewTemplateOut:
    """Zmiana szablonu dotyczy wywiadów zakładanych później – istniejące zostają bez zmian."""
    questions = _clean_questions(body.questions)
    row = await session.get(InterviewTemplate, _TEMPLATE_ID)
    if row is None:
        row = InterviewTemplate(id=_TEMPLATE_ID, questions=questions)
    row.questions = questions
    row.updated_by = admin.id
    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return InterviewTemplateOut(questions=questions, is_default=False, updated_at=row.updated_at)


@router.delete("/admin/interview-template", response_model=InterviewTemplateOut)
async def reset_template(session: SessionDep, admin: CurrentAdmin) -> InterviewTemplateOut:
    """Przywraca domyślny zestaw pytań."""
    await session.exec(delete(InterviewTemplate).where(col(InterviewTemplate.id) == _TEMPLATE_ID))
    await session.commit()
    return InterviewTemplateOut(questions=list(DEFAULT_QUESTIONS), is_default=True, updated_at=None)


async def _items(session: SessionDep, patient_id: int) -> list[InterviewItem]:
    rows = await session.exec(
        select(InterviewItem)
        .where(InterviewItem.patient_id == patient_id)
        .order_by(col(InterviewItem.position), col(InterviewItem.id))
    )
    return list(rows.all())


async def _audio_ids(session: SessionDep, patient_id: int) -> set[int]:
    rows = await session.exec(
        select(InterviewAudio.item_id).where(InterviewAudio.patient_id == patient_id)
    )
    return set(rows.all())


def _item_out(item: InterviewItem, audio_ids: set[int]) -> InterviewItemOut:
    return InterviewItemOut(
        id=item.id,  # type: ignore[arg-type]
        position=item.position,
        question=item.question,
        answer=item.answer,
        has_audio=item.id in audio_ids,
        updated_at=item.updated_at,
    )


def _snapshot(items: list[InterviewItem]) -> list[dict[str, str]]:
    return [{"question": i.question, "answer": i.answer} for i in items]


async def _interview(session: SessionDep, patient_id: int, doctor: User) -> PatientInterview:
    """Zwraca wywiad pacjenta; przy pierwszym otwarciu zakłada go z bieżącego szablonu."""
    interview = await session.get(PatientInterview, patient_id)
    if interview is not None:
        return interview
    questions, _ = await template_questions(session)
    interview = PatientInterview(patient_id=patient_id, user_id=doctor.id)  # type: ignore[arg-type]
    session.add(interview)
    for position, question in enumerate(questions):
        session.add(InterviewItem(patient_id=patient_id, position=position, question=question))
    await session.commit()
    await session.refresh(interview)
    return interview


async def _out(session: SessionDep, interview: PatientInterview) -> InterviewOut:
    items = await _items(session, interview.patient_id)
    audio_ids = await _audio_ids(session, interview.patient_id)
    return InterviewOut(
        status=interview.status,
        approved_at=interview.approved_at,
        updated_at=interview.updated_at,
        items=[_item_out(i, audio_ids) for i in items],
    )


def _touch(interview: PatientInterview, items: list[InterviewItem]) -> None:
    """Wywiad jest „zatwierdzony” tylko, gdy treść zgadza się z zatwierdzoną migawką."""
    interview.updated_at = utcnow()
    approved = interview.approved_items is not None and interview.approved_items == _snapshot(items)
    interview.status = "approved" if approved else "draft"


async def _owned_item(session: SessionDep, patient_id: int, item_id: int) -> InterviewItem:
    item = (
        await session.exec(
            select(InterviewItem).where(
                InterviewItem.id == item_id, InterviewItem.patient_id == patient_id
            )
        )
    ).first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono pytania wywiadu")
    return item


@router.get("/patients/{patient_id}/interview", response_model=InterviewOut)
async def get_interview(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> InterviewOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    return await _out(session, interview)


async def _apply(
    session: SessionDep, interview: PatientInterview, body: InterviewSaveIn
) -> list[InterviewItem]:
    items = {i.id: i for i in await _items(session, interview.patient_id)}
    unknown = [entry.id for entry in body.items if entry.id not in items]
    if unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono pytania wywiadu")
    now = utcnow()
    for position, entry in enumerate(body.items):
        item = items[entry.id]
        question, answer = entry.question.strip(), entry.answer.strip()
        if (item.question, item.answer, item.position) != (question, answer, position):
            item.question, item.answer, item.position = question, answer, position
            item.updated_at = now
            session.add(item)
    return sorted(items.values(), key=lambda i: (i.position, i.id or 0))


@router.put("/patients/{patient_id}/interview", response_model=InterviewOut)
async def save_interview(
    patient_id: int, body: InterviewSaveIn, session: SessionDep, doctor: CurrentDoctor
) -> InterviewOut:
    """Zapis roboczy (bez zatwierdzenia – asystent nadal widzi poprzednią zatwierdzoną wersję)."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    items = await _apply(session, interview, body)
    _touch(interview, items)
    session.add(interview)
    await session.commit()
    return await _out(session, interview)


@router.post("/patients/{patient_id}/interview/approve", response_model=InterviewOut)
async def approve_interview(
    patient_id: int, body: InterviewSaveIn, session: SessionDep, doctor: CurrentDoctor
) -> InterviewOut:
    """Zapisuje poprawki i zatwierdza wywiad – od teraz ta wersja trafia do kontekstu LLM."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    items = await _apply(session, interview, body)
    now = utcnow()
    interview.approved_items = _snapshot(items)
    interview.approved_at = now
    interview.updated_at = now
    interview.status = "approved"
    session.add(interview)
    await session.commit()
    return await _out(session, interview)


@router.post(
    "/patients/{patient_id}/interview/items",
    response_model=InterviewItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_question(
    patient_id: int, body: InterviewQuestionIn, session: SessionDep, doctor: CurrentDoctor
) -> InterviewItemOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    last = (
        await session.exec(
            select(func.max(InterviewItem.position)).where(
                InterviewItem.patient_id == interview.patient_id
            )
        )
    ).one()
    item = InterviewItem(
        patient_id=interview.patient_id,
        position=(last if last is not None else -1) + 1,
        question=body.question.strip(),
    )
    session.add(item)
    interview.status = "draft"
    interview.updated_at = utcnow()
    session.add(interview)
    await session.commit()
    await session.refresh(item)
    return _item_out(item, set())


@router.post("/patients/{patient_id}/interview/reset", response_model=InterviewOut)
async def reset_interview(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> InterviewOut:
    """Zastępuje pytania (wraz z odpowiedziami i nagraniami) aktualnym szablonem.
    Zatwierdzona wersja w kontekście asystenta zostaje do czasu ponownego zatwierdzenia."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    await session.exec(
        delete(InterviewAudio).where(col(InterviewAudio.patient_id) == interview.patient_id)
    )
    await session.exec(
        delete(InterviewItem).where(col(InterviewItem.patient_id) == interview.patient_id)
    )
    questions, _ = await template_questions(session)
    for position, question in enumerate(questions):
        session.add(
            InterviewItem(patient_id=interview.patient_id, position=position, question=question)
        )
    interview.status = "draft"
    interview.updated_at = utcnow()
    session.add(interview)
    await session.commit()
    return await _out(session, interview)


@router.delete(
    "/patients/{patient_id}/interview/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(
    patient_id: int, item_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor)  # type: ignore[arg-type]
    item = await _owned_item(session, interview.patient_id, item_id)
    await session.exec(delete(InterviewAudio).where(col(InterviewAudio.item_id) == item.id))
    await session.delete(item)
    await session.flush()
    _touch(interview, await _items(session, interview.patient_id))
    session.add(interview)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/patients/{patient_id}/interview/items/{item_id}/audio",
    response_model=InterviewRecordingOut,
)
async def upload_recording(
    patient_id: int,
    item_id: int,
    session: SessionDep,
    doctor: CurrentDoctor,
    audio: Annotated[UploadFile, File(description="Nagranie odpowiedzi pacjenta")],
) -> InterviewRecordingOut:
    """Zapisuje nagranie odpowiedzi (zastępuje poprzednie) i zwraca jego transkrypcję.
    Odpowiedź tekstowa NIE jest nadpisywana – lekarz wstawia/poprawia transkrypcję w formularzu.
    Nagranie zostaje zapisane także wtedy, gdy transkrypcja się nie powiedzie."""
    patient = await get_owned_patient(session, patient_id, doctor)
    item = await _owned_item(session, patient.id, item_id)  # type: ignore[arg-type]
    data, filename, content_type = await read_audio_upload(audio)

    await session.exec(delete(InterviewAudio).where(col(InterviewAudio.item_id) == item.id))
    session.add(
        InterviewAudio(
            item_id=item.id,  # type: ignore[arg-type]
            patient_id=item.patient_id,
            content_type=content_type,
            data=data,
            size=len(data),
        )
    )
    item.updated_at = utcnow()
    session.add(item)
    await session.commit()
    await session.refresh(item)

    transcript: str | None = None
    error: str | None = None
    try:
        transcript = await transcribe_audio(
            data,
            filename=filename,
            content_type=content_type,
            language="pl",
            user_id=doctor.id,  # type: ignore[arg-type]
        )
    except TranscriptionError as exc:
        error = str(exc)
    return InterviewRecordingOut(
        item=_item_out(item, {item.id}),  # type: ignore[arg-type]
        transcript=transcript,
        error=error,
    )


@router.get("/patients/{patient_id}/interview/items/{item_id}/audio")
async def get_recording(
    patient_id: int, item_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    item = await _owned_item(session, patient.id, item_id)  # type: ignore[arg-type]
    recording = await session.get(InterviewAudio, item.id)
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak nagrania dla tego pytania")
    return Response(
        content=recording.data,
        media_type=recording.content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/patients/{patient_id}/interview/items/{item_id}/audio",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recording(
    patient_id: int, item_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    item = await _owned_item(session, patient.id, item_id)  # type: ignore[arg-type]
    await session.exec(delete(InterviewAudio).where(col(InterviewAudio.item_id) == item.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def approved_interview(session: SessionDep, patient_id: int) -> list[dict[str, str]]:
    """Zatwierdzone pary pytanie–odpowiedź (tylko z odpowiedzią) do kontekstu LLM.

    Nagłówki sekcji („## …”) zostają tylko wtedy, gdy w sekcji jest choć jedna odpowiedź –
    zwracane jako {"section": tytuł}, żeby model widział strukturę formularza.
    """
    interview = await session.get(PatientInterview, patient_id)
    if interview is None or not interview.approved_items:
        return []
    result: list[dict[str, str]] = []
    pending_section: str | None = None
    for entry in interview.approved_items:
        question = str(entry.get("question", ""))
        answer = str(entry.get("answer", "")).strip()
        if is_section(question):
            pending_section = question[len(SECTION_PREFIX) :].strip()
            continue
        if not answer:
            continue
        if pending_section is not None:
            result.append({"section": pending_section})
            pending_section = None
        result.append({"question": question, "answer": answer})
    return result
