"""CRUD pacjentów. Każde zapytanie SQL jest filtrowane po user_id zalogowanego lekarza."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, delete, select

from ..auth import CurrentDoctor, SessionDep
from ..database import Patient, PatientNote, utcnow
from .schemas import NoteIn, NoteOut, PatientIn, PatientOut, RecentNoteOut

router = APIRouter(prefix="/patients", tags=["patients"])


async def get_owned_patient(session: SessionDep, patient_id: int, doctor: CurrentDoctor) -> Patient:
    patient = (
        await session.exec(
            select(Patient).where(Patient.id == patient_id, Patient.user_id == doctor.id)
        )
    ).first()
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono pacjenta")
    return patient


@router.get("", response_model=list[PatientOut])
async def list_patients(session: SessionDep, doctor: CurrentDoctor) -> list[Patient]:
    result = await session.exec(
        select(Patient)
        .where(Patient.user_id == doctor.id)
        .order_by(col(Patient.last_name), col(Patient.first_name))
    )
    return list(result.all())


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(body: PatientIn, session: SessionDep, doctor: CurrentDoctor) -> Patient:
    patient = Patient(**body.model_dump(), user_id=doctor.id)
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


@router.get("/notes/recent", response_model=list[RecentNoteOut])
async def recent_notes(
    session: SessionDep, doctor: CurrentDoctor, limit: int = 8
) -> list[RecentNoteOut]:
    limit = max(1, min(limit, 30))
    rows = await session.exec(
        select(PatientNote, Patient)
        .join(Patient, col(Patient.id) == col(PatientNote.patient_id))
        .where(PatientNote.user_id == doctor.id, Patient.user_id == doctor.id)
        .order_by(col(PatientNote.created_at).desc())
        .limit(limit)
    )
    return [
        RecentNoteOut(
            note_id=note.id,  # type: ignore[arg-type]
            patient_id=patient.id,  # type: ignore[arg-type]
            patient_name=f"{patient.first_name} {patient.last_name}",
            snippet=note.content[:160],
            source=note.source,
            created_at=note.created_at,
        )
        for note, patient in rows.all()
    ]


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: int, session: SessionDep, doctor: CurrentDoctor) -> Patient:
    return await get_owned_patient(session, patient_id, doctor)


@router.put("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: int, body: PatientIn, session: SessionDep, doctor: CurrentDoctor
) -> Patient:
    patient = await get_owned_patient(session, patient_id, doctor)
    for field, value in body.model_dump().items():
        setattr(patient, field, value)
    patient.updated_at = utcnow()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(patient_id: int, session: SessionDep, doctor: CurrentDoctor) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    await session.exec(
        delete(PatientNote).where(
            col(PatientNote.patient_id) == patient.id, col(PatientNote.user_id) == doctor.id
        )
    )
    await session.delete(patient)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{patient_id}/notes", response_model=list[NoteOut])
async def list_notes(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> list[PatientNote]:
    patient = await get_owned_patient(session, patient_id, doctor)
    result = await session.exec(
        select(PatientNote)
        .where(PatientNote.patient_id == patient.id, PatientNote.user_id == doctor.id)
        .order_by(col(PatientNote.created_at).desc())
    )
    return list(result.all())


@router.post("/{patient_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    patient_id: int, body: NoteIn, session: SessionDep, doctor: CurrentDoctor
) -> PatientNote:
    patient = await get_owned_patient(session, patient_id, doctor)
    note = PatientNote(
        user_id=doctor.id,  # type: ignore[arg-type]
        patient_id=patient.id,  # type: ignore[arg-type]
        content=body.content.strip(),
        source=body.source,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@router.delete("/{patient_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    patient_id: int, note_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    note = (
        await session.exec(
            select(PatientNote).where(
                PatientNote.id == note_id,
                PatientNote.patient_id == patient.id,
                PatientNote.user_id == doctor.id,
            )
        )
    ).first()
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono notatki")
    await session.delete(note)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
