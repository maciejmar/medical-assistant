"""Wywiad pacjenta: pytania z szablonu (edytuje administrator) i własne pytania lekarza,
odpowiedzi wpisywane ręcznie lub nagrywane w gabinecie (zapis audio + transkrypcja Whisper).

Formularze: „interview” (uniwersalny wywiad i badanie – domyślny) oraz „ankyloglossia” (karta
badania – diagnoza ankyloglosji). Każdy ma własny szablon, pytania, status i zatwierdzenie;
endpointy przyjmują parametr `?form=` (domyślnie „interview”). Pytania formularzy innych niż
domyślny są oznaczone w tabeli patient_interview_item_forms, a ich stan trzyma
patient_interview_forms (wywiad domyślny – jak dotąd patient_interviews).

Do kontekstu LLM trafia wyłącznie ostatnia ZATWIERDZONA wersja każdego formularza (migawka
approved_items); anonimizację imion, PESEL-u, telefonu i adresu robi src.llm.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from sqlmodel import col, delete, select

from ..auth import CurrentAdmin, CurrentDoctor, SessionDep
from ..database import (
    InterviewAudio,
    InterviewItem,
    InterviewItemForm,
    InterviewTemplate,
    PatientInterview,
    PatientInterviewForm,
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
HINT_SEPARATOR = " | "
SRC_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = SRC_DIR / "interview_template.txt"

Form = Literal["interview", "ankyloglossia"]
DEFAULT_FORM: Form = "interview"


@dataclass(frozen=True)
class FormSpec:
    label: str  # nagłówek sekcji w kontekście LLM
    template_id: int  # wiersz w interview_templates
    template_file: Path


FORMS: dict[str, FormSpec] = {
    "interview": FormSpec("Uniwersalny wywiad i badanie logopedyczne", 1, TEMPLATE_FILE),
    "ankyloglossia": FormSpec(
        "Karta badania – diagnoza ankyloglosji", 2, SRC_DIR / "ankyloglossia_template.txt"
    ),
}

FormQuery = Annotated[Form, Query(description="Formularz: interview | ankyloglossia")]


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


def question_title(question: str) -> str:
    """Sam tytuł pytania – bez podpowiedzi „ | Co oceniamy: …” i flag („@pozycje”)."""
    return question.split(HINT_SEPARATOR, 1)[0].strip()


DEFAULTS: dict[str, list[str]] = {
    form: load_default_questions(spec.template_file) for form, spec in FORMS.items()
}
DEFAULT_QUESTIONS: list[str] = DEFAULTS[DEFAULT_FORM]


def _clean_questions(questions: list[str]) -> list[str]:
    cleaned = [" ".join(q.split()) for q in questions]
    return [q[:2000] for q in cleaned if q]


async def template_questions(
    session: SessionDep, form: str = DEFAULT_FORM
) -> tuple[list[str], InterviewTemplate | None]:
    row = await session.get(InterviewTemplate, FORMS[form].template_id)
    if row is None:
        return list(DEFAULTS[form]), None
    return [str(q) for q in row.questions], row


@router.get("/admin/interview-template", response_model=InterviewTemplateOut)
async def get_template(
    session: SessionDep, admin: CurrentAdmin, form: FormQuery = DEFAULT_FORM
) -> InterviewTemplateOut:
    questions, row = await template_questions(session, form)
    return InterviewTemplateOut(
        questions=questions, is_default=row is None, updated_at=row.updated_at if row else None
    )


@router.put("/admin/interview-template", response_model=InterviewTemplateOut)
async def save_template(
    body: InterviewTemplateIn,
    session: SessionDep,
    admin: CurrentAdmin,
    form: FormQuery = DEFAULT_FORM,
) -> InterviewTemplateOut:
    """Zmiana szablonu dotyczy wywiadów zakładanych później – istniejące zostają bez zmian."""
    questions = _clean_questions(body.questions)
    template_id = FORMS[form].template_id
    row = await session.get(InterviewTemplate, template_id)
    if row is None:
        row = InterviewTemplate(id=template_id, questions=questions)
    row.questions = questions
    row.updated_by = admin.id
    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return InterviewTemplateOut(questions=questions, is_default=False, updated_at=row.updated_at)


@router.delete("/admin/interview-template", response_model=InterviewTemplateOut)
async def reset_template(
    session: SessionDep, admin: CurrentAdmin, form: FormQuery = DEFAULT_FORM
) -> InterviewTemplateOut:
    """Przywraca domyślny zestaw pytań (z pliku szablonu formularza)."""
    template_id = FORMS[form].template_id
    await session.exec(delete(InterviewTemplate).where(col(InterviewTemplate.id) == template_id))
    await session.commit()
    return InterviewTemplateOut(questions=list(DEFAULTS[form]), is_default=True, updated_at=None)


def _tagged_ids(patient_id: int, form: str | None = None):
    query = select(InterviewItemForm.item_id).where(InterviewItemForm.patient_id == patient_id)
    if form is not None:
        query = query.where(InterviewItemForm.form == form)
    return query


async def _items(session: SessionDep, patient_id: int, form: str) -> list[InterviewItem]:
    query = select(InterviewItem).where(InterviewItem.patient_id == patient_id)
    if form == DEFAULT_FORM:
        query = query.where(col(InterviewItem.id).not_in(_tagged_ids(patient_id)))
    else:
        query = query.where(col(InterviewItem.id).in_(_tagged_ids(patient_id, form)))
    rows = await session.exec(query.order_by(col(InterviewItem.position), col(InterviewItem.id)))
    return list(rows.all())


async def _item_form(session: SessionDep, item: InterviewItem) -> str:
    tag = await session.get(InterviewItemForm, item.id)
    return tag.form if tag else DEFAULT_FORM


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


async def _add_items(
    session: SessionDep, patient_id: int, form: str, questions: list[str], start: int = 0
) -> list[InterviewItem]:
    items = [
        InterviewItem(patient_id=patient_id, position=start + offset, question=question)
        for offset, question in enumerate(questions)
    ]
    session.add_all(items)
    if form != DEFAULT_FORM:
        await session.flush()  # ID pytań potrzebne do oznaczenia formularza
        session.add_all(
            InterviewItemForm(item_id=i.id, patient_id=patient_id, form=form)  # type: ignore[arg-type]
            for i in items
        )
    return items


InterviewState = PatientInterview | PatientInterviewForm


async def _interview(
    session: SessionDep, patient_id: int, doctor: User, form: str = DEFAULT_FORM
) -> InterviewState:
    """Zwraca stan formularza; przy pierwszym otwarciu zakłada go z bieżącego szablonu."""
    if form == DEFAULT_FORM:
        interview: InterviewState | None = await session.get(PatientInterview, patient_id)
    else:
        interview = await session.get(PatientInterviewForm, (patient_id, form))
    if interview is not None:
        return interview
    questions, _ = await template_questions(session, form)
    if form == DEFAULT_FORM:
        interview = PatientInterview(patient_id=patient_id, user_id=doctor.id)  # type: ignore[arg-type]
    else:
        interview = PatientInterviewForm(patient_id=patient_id, form=form, user_id=doctor.id)  # type: ignore[arg-type]
    session.add(interview)
    await _add_items(session, patient_id, form, questions)
    await session.commit()
    await session.refresh(interview)
    return interview


async def _out(session: SessionDep, interview: InterviewState, form: str) -> InterviewOut:
    items = await _items(session, interview.patient_id, form)
    audio_ids = await _audio_ids(session, interview.patient_id)
    return InterviewOut(
        status=interview.status,
        approved_at=interview.approved_at,
        updated_at=interview.updated_at,
        items=[_item_out(i, audio_ids) for i in items],
    )


def _touch(interview: InterviewState, items: list[InterviewItem]) -> None:
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
    patient_id: int, session: SessionDep, doctor: CurrentDoctor, form: FormQuery = DEFAULT_FORM
) -> InterviewOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    return await _out(session, interview, form)


async def _apply(
    session: SessionDep, interview: InterviewState, body: InterviewSaveIn, form: str
) -> list[InterviewItem]:
    items = {i.id: i for i in await _items(session, interview.patient_id, form)}
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
    patient_id: int,
    body: InterviewSaveIn,
    session: SessionDep,
    doctor: CurrentDoctor,
    form: FormQuery = DEFAULT_FORM,
) -> InterviewOut:
    """Zapis roboczy (bez zatwierdzenia – asystent nadal widzi poprzednią zatwierdzoną wersję)."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    items = await _apply(session, interview, body, form)
    _touch(interview, items)
    session.add(interview)
    await session.commit()
    return await _out(session, interview, form)


@router.post("/patients/{patient_id}/interview/approve", response_model=InterviewOut)
async def approve_interview(
    patient_id: int,
    body: InterviewSaveIn,
    session: SessionDep,
    doctor: CurrentDoctor,
    form: FormQuery = DEFAULT_FORM,
) -> InterviewOut:
    """Zapisuje poprawki i zatwierdza formularz – od teraz ta wersja trafia do kontekstu LLM."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    items = await _apply(session, interview, body, form)
    now = utcnow()
    interview.approved_items = _snapshot(items)
    interview.approved_at = now
    interview.updated_at = now
    interview.status = "approved"
    session.add(interview)
    await session.commit()
    return await _out(session, interview, form)


@router.post(
    "/patients/{patient_id}/interview/items",
    response_model=InterviewItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_question(
    patient_id: int,
    body: InterviewQuestionIn,
    session: SessionDep,
    doctor: CurrentDoctor,
    form: FormQuery = DEFAULT_FORM,
) -> InterviewItemOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    positions = [i.position for i in await _items(session, interview.patient_id, form)]
    (item,) = await _add_items(
        session,
        interview.patient_id,
        form,
        [body.question.strip()],
        start=max(positions, default=-1) + 1,
    )
    interview.status = "draft"
    interview.updated_at = utcnow()
    session.add(interview)
    await session.commit()
    await session.refresh(item)
    return _item_out(item, set())


async def _delete_items(session: SessionDep, item_ids: list[int]) -> None:
    if not item_ids:
        return
    await session.exec(delete(InterviewAudio).where(col(InterviewAudio.item_id).in_(item_ids)))
    await session.exec(
        delete(InterviewItemForm).where(col(InterviewItemForm.item_id).in_(item_ids))
    )
    await session.exec(delete(InterviewItem).where(col(InterviewItem.id).in_(item_ids)))


@router.post("/patients/{patient_id}/interview/reset", response_model=InterviewOut)
async def reset_interview(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor, form: FormQuery = DEFAULT_FORM
) -> InterviewOut:
    """Zastępuje pytania formularza (wraz z odpowiedziami i nagraniami) aktualnym szablonem.
    Zatwierdzona wersja w kontekście asystenta zostaje do czasu ponownego zatwierdzenia."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    old = await _items(session, interview.patient_id, form)
    await _delete_items(session, [i.id for i in old])  # type: ignore[misc]
    questions, _ = await template_questions(session, form)
    await _add_items(session, interview.patient_id, form, questions)
    interview.status = "draft"
    interview.updated_at = utcnow()
    session.add(interview)
    await session.commit()
    return await _out(session, interview, form)


@router.delete(
    "/patients/{patient_id}/interview/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(
    patient_id: int, item_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    item = await _owned_item(session, patient.id, item_id)  # type: ignore[arg-type]
    form = await _item_form(session, item)
    interview = await _interview(session, patient.id, doctor, form)  # type: ignore[arg-type]
    await _delete_items(session, [item.id])  # type: ignore[list-item]
    await session.flush()
    _touch(interview, await _items(session, interview.patient_id, form))
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


def approved_entries(approved_items: list | None) -> list[dict[str, str]]:
    """Zatwierdzone pary pytanie–odpowiedź (tylko z odpowiedzią); pytanie skrócone do tytułu.

    Nagłówki sekcji („## …”) zostają tylko wtedy, gdy w sekcji jest choć jedna odpowiedź –
    zwracane jako {"section": tytuł}, żeby model widział strukturę formularza.
    """
    result: list[dict[str, str]] = []
    pending_section: str | None = None
    for entry in approved_items or []:
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
        result.append({"question": question_title(question), "answer": answer})
    return result


async def approved_interview(session: SessionDep, patient_id: int) -> list[dict[str, str]]:
    """Zatwierdzone formularze pacjenta do kontekstu LLM: wywiad uniwersalny, a po nim każdy
    dodatkowy formularz z odpowiedziami (poprzedzony sekcją z nazwą formularza)."""
    interview = await session.get(PatientInterview, patient_id)
    result = approved_entries(interview.approved_items if interview else None)
    for form, spec in FORMS.items():
        if form == DEFAULT_FORM:
            continue
        state = await session.get(PatientInterviewForm, (patient_id, form))
        entries = approved_entries(state.approved_items if state else None)
        if entries:
            if entries[0].get("section"):
                entries[0] = {"section": f"{spec.label} – {entries[0]['section']}"}
            else:
                entries.insert(0, {"section": spec.label})
            result.extend(entries)
    return result
