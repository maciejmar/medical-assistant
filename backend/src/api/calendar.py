"""Kalendarz pacjenta – jedna lista wydarzeń widoczna dla lekarza prowadzącego i dla pacjenta.

Lekarz: /patients/{id}/events (tylko własni pacjenci, pełna edycja).
Pacjent: /portal/events (tylko jego karta); może dodawać konsultacje u innych specjalistów
i inne wpisy oraz edytować/usuwać wyłącznie wpisy, które sam dodał.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, select

from ..auth import CurrentDoctor, CurrentPatient, SessionDep
from ..database import Patient, PatientAccount, PatientEvent, PlanStep, User, utcnow
from .patients import get_owned_patient
from .schemas import DoctorEventOut, EventIn, EventOut

router = APIRouter(tags=["calendar"])

PATIENT_EVENT_TYPES = {"consultation", "other"}
# Typy zajmujące czas lekarza – kolizje sprawdzane tylko między nimi (konsultacje pacjenta
# u innych specjalistów i etapy terapii nie zajmują czasu lekarza).
BLOCKING_TYPES = {"visit", "other"}
DEFAULT_DURATION = timedelta(minutes=45)
MAX_EVENTS = 1000


async def _linked_patient(session: SessionDep, user: User) -> Patient:
    patient = (
        await session.exec(
            select(Patient)
            .join(PatientAccount, col(PatientAccount.patient_id) == col(Patient.id))
            .where(PatientAccount.user_id == user.id)
        )
    ).first()
    if patient is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Konto nie jest jeszcze powiązane z kartą pacjenta"
        )
    return patient


def _can_edit(event: PatientEvent, user: User, as_patient: bool) -> bool:
    return not as_patient or (event.created_by_role == "patient" and event.created_by == user.id)


async def _list(
    session: SessionDep,
    patient_id: int,
    user: User,
    as_patient: bool,
    start: datetime | None,
    end: datetime | None,
) -> list[EventOut]:
    query = select(PatientEvent).where(PatientEvent.patient_id == patient_id)
    if start is not None:
        query = query.where(col(PatientEvent.starts_at) >= start)
    if end is not None:
        query = query.where(col(PatientEvent.starts_at) < end)
    rows = await session.exec(
        query.order_by(col(PatientEvent.starts_at), col(PatientEvent.id)).limit(MAX_EVENTS)
    )
    events = list(rows.all())
    step_ids = {e.plan_step_id for e in events if e.plan_step_id is not None}
    titles: dict[int, str] = {}
    if step_ids:
        steps = await session.exec(select(PlanStep).where(col(PlanStep.id).in_(step_ids)))
        titles = {s.id: s.title for s in steps.all() if s.id is not None}
    return [_out(e, user, as_patient, titles.get(e.plan_step_id or 0)) for e in events]


def _out(event: PatientEvent, user: User, as_patient: bool, step_title: str | None) -> EventOut:
    return EventOut(
        id=event.id,  # type: ignore[arg-type]
        type=event.type,  # type: ignore[arg-type]
        title=event.title,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        all_day=event.all_day,
        location=event.location,
        description=event.description,
        plan_step_id=event.plan_step_id,
        plan_step_title=step_title,
        created_by_role=event.created_by_role,
        editable=_can_edit(event, user, as_patient),
        updated_at=event.updated_at,
    )


async def _apply(
    session: SessionDep, event: PatientEvent, body: EventIn, patient_id: int, as_patient: bool
) -> str | None:
    """Waliduje i przepisuje pola; zwraca nazwę powiązanego kroku planu."""
    if body.ends_at is not None and body.ends_at < body.starts_at:
        raise HTTPException(422, "Koniec wydarzenia nie może być przed początkiem")
    if as_patient and body.type not in PATIENT_EVENT_TYPES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Pacjent może dodawać tylko konsultacje u specjalistów i inne wydarzenia",
        )
    step_title = None
    plan_step_id = None if as_patient else body.plan_step_id
    if plan_step_id is not None:
        step = (
            await session.exec(
                select(PlanStep).where(
                    PlanStep.id == plan_step_id, PlanStep.patient_id == patient_id
                )
            )
        ).first()
        if step is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono kroku planu")
        step_title = step.title
    event.type = body.type
    event.title = body.title.strip()
    event.starts_at = body.starts_at
    event.ends_at = body.ends_at
    event.all_day = body.all_day
    event.location = body.location.strip()
    event.description = body.description.strip()
    event.plan_step_id = plan_step_id
    event.updated_at = utcnow()
    return step_title


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _check_conflicts(
    session: SessionDep, doctor: User, body: EventIn, exclude_id: int | None
) -> None:
    """Termin zajęty innym wydarzeniem lekarza (dowolny jego pacjent) → 409 z listą kolizji,
    chyba że lekarz potwierdził zapis (`allow_overlap`)."""
    if body.allow_overlap or body.all_day or body.type not in BLOCKING_TYPES:
        return
    start = _utc(body.starts_at)
    end = _utc(body.ends_at) if body.ends_at else start + DEFAULT_DURATION
    rows = await session.exec(
        select(PatientEvent, Patient)
        .join(Patient, col(Patient.id) == col(PatientEvent.patient_id))
        .where(
            Patient.user_id == doctor.id,
            col(PatientEvent.type).in_(BLOCKING_TYPES),
            col(PatientEvent.all_day).is_(False),
            col(PatientEvent.starts_at) < end,
            col(PatientEvent.starts_at) > start - timedelta(days=1),
        )
    )
    conflicts = []
    for event, patient in rows.all():
        if event.id == exclude_id:
            continue
        other_start = _utc(event.starts_at)
        other_end = _utc(event.ends_at) if event.ends_at else other_start + DEFAULT_DURATION
        if other_start < end and other_end > start:
            conflicts.append(
                {
                    "id": event.id,
                    "title": event.title,
                    "patient_id": patient.id,
                    "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                    "starts_at": other_start.isoformat(),
                    "ends_at": other_end.isoformat(),
                }
            )
    if conflicts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "time_conflict",
                "message": "Ten termin jest już zajęty. Zmień termin tego wydarzenia.",
                "conflicts": conflicts,
            },
        )


async def _create(
    session: SessionDep, patient_id: int, body: EventIn, user: User, as_patient: bool
) -> EventOut:
    if not as_patient:
        await _check_conflicts(session, user, body, exclude_id=None)
    event = PatientEvent(
        patient_id=patient_id,
        type=body.type,
        title=body.title,
        starts_at=body.starts_at,
        created_by=user.id,
        created_by_role="patient" if as_patient else "doctor",
    )
    step_title = await _apply(session, event, body, patient_id, as_patient)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _out(event, user, as_patient, step_title)


async def _owned_event(
    session: SessionDep, patient_id: int, event_id: int, user: User, as_patient: bool
) -> PatientEvent:
    event = (
        await session.exec(
            select(PatientEvent).where(
                PatientEvent.id == event_id, PatientEvent.patient_id == patient_id
            )
        )
    ).first()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono wydarzenia")
    if not _can_edit(event, user, as_patient):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Wydarzenia dodane przez logopedę może zmienić tylko on"
        )
    return event


async def _update(
    session: SessionDep, patient_id: int, event_id: int, body: EventIn, user: User, as_patient: bool
) -> EventOut:
    event = await _owned_event(session, patient_id, event_id, user, as_patient)
    if not as_patient:
        await _check_conflicts(session, user, body, exclude_id=event.id)
    step_title = await _apply(session, event, body, patient_id, as_patient)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _out(event, user, as_patient, step_title)


async def _delete(
    session: SessionDep, patient_id: int, event_id: int, user: User, as_patient: bool
) -> Response:
    event = await _owned_event(session, patient_id, event_id, user, as_patient)
    await session.delete(event)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- lekarz ---------------------------------------------------------------------------------


@router.get("/patients/{patient_id}/events", response_model=list[EventOut])
async def doctor_events(
    patient_id: int,
    session: SessionDep,
    doctor: CurrentDoctor,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[EventOut]:
    patient = await get_owned_patient(session, patient_id, doctor)
    return await _list(session, patient.id, doctor, False, start, end)  # type: ignore[arg-type]


@router.post(
    "/patients/{patient_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED
)
async def doctor_create_event(
    patient_id: int, body: EventIn, session: SessionDep, doctor: CurrentDoctor
) -> EventOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    return await _create(session, patient.id, body, doctor, False)  # type: ignore[arg-type]


@router.put("/patients/{patient_id}/events/{event_id}", response_model=EventOut)
async def doctor_update_event(
    patient_id: int, event_id: int, body: EventIn, session: SessionDep, doctor: CurrentDoctor
) -> EventOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    return await _update(session, patient.id, event_id, body, doctor, False)  # type: ignore[arg-type]


@router.delete("/patients/{patient_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def doctor_delete_event(
    patient_id: int, event_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    return await _delete(session, patient.id, event_id, doctor, False)  # type: ignore[arg-type]


@router.get("/calendar/events", response_model=list[DoctorEventOut])
async def doctor_all_events(
    session: SessionDep,
    doctor: CurrentDoctor,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[DoctorEventOut]:
    """Zbiorczy kalendarz lekarza: wydarzenia wszystkich jego pacjentów w zakresie dat
    (tylko pacjenci tego lekarza – filtr po patients.user_id)."""
    query = (
        select(PatientEvent, Patient)
        .join(Patient, col(Patient.id) == col(PatientEvent.patient_id))
        .where(Patient.user_id == doctor.id)
    )
    if start is not None:
        query = query.where(col(PatientEvent.starts_at) >= start)
    if end is not None:
        query = query.where(col(PatientEvent.starts_at) < end)
    rows = (
        await session.exec(
            query.order_by(col(PatientEvent.starts_at), col(PatientEvent.id)).limit(MAX_EVENTS)
        )
    ).all()
    step_ids = {e.plan_step_id for e, _ in rows if e.plan_step_id is not None}
    titles: dict[int, str] = {}
    if step_ids:
        steps = await session.exec(select(PlanStep).where(col(PlanStep.id).in_(step_ids)))
        titles = {s.id: s.title for s in steps.all() if s.id is not None}
    return [
        DoctorEventOut(
            **_out(event, doctor, False, titles.get(event.plan_step_id or 0)).model_dump(),
            patient_id=patient.id,  # type: ignore[arg-type]
            patient_name=f"{patient.first_name} {patient.last_name}".strip(),
        )
        for event, patient in rows
    ]


# --- pacjent --------------------------------------------------------------------------------


@router.get("/portal/events", response_model=list[EventOut])
async def patient_events(
    session: SessionDep,
    user: CurrentPatient,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[EventOut]:
    patient = await _linked_patient(session, user)
    return await _list(session, patient.id, user, True, start, end)  # type: ignore[arg-type]


@router.post("/portal/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def patient_create_event(
    body: EventIn, session: SessionDep, user: CurrentPatient
) -> EventOut:
    patient = await _linked_patient(session, user)
    return await _create(session, patient.id, body, user, True)  # type: ignore[arg-type]


@router.put("/portal/events/{event_id}", response_model=EventOut)
async def patient_update_event(
    event_id: int, body: EventIn, session: SessionDep, user: CurrentPatient
) -> EventOut:
    patient = await _linked_patient(session, user)
    return await _update(session, patient.id, event_id, body, user, True)  # type: ignore[arg-type]


@router.delete("/portal/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patient_delete_event(
    event_id: int, session: SessionDep, user: CurrentPatient
) -> Response:
    patient = await _linked_patient(session, user)
    return await _delete(session, patient.id, event_id, user, True)  # type: ignore[arg-type]
