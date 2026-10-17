"""Konto pacjenta: powiązanie z kartą, zalecenia, powiadomienia e-mail i panel pacjenta.

Endpointy /patients/{id}/... są dostępne dla lekarza-właściciela karty (filtrowanie po user_id).
Endpoint /portal/me zwraca pacjentowi wyłącznie dane jego własnej karty – bez notatek lekarza.
"""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, delete, select

from .. import mailer
from ..auth import CurrentDoctor, CurrentPatient, SessionDep, hash_password
from ..config import settings
from ..database import (
    Patient,
    PatientAccount,
    PatientNotification,
    Recommendation,
    Role,
    User,
    utcnow,
)
from .patients import get_owned_patient
from .schemas import (
    NotificationIn,
    NotificationOut,
    PatientAccountIn,
    PatientAccountOut,
    PatientPortalOut,
    RecommendationIn,
    RecommendationOut,
)

router = APIRouter(tags=["patient-portal"])


async def _linked_user(session: SessionDep, patient_id: int) -> User | None:
    row = (
        await session.exec(
            select(User)
            .join(PatientAccount, col(PatientAccount.user_id) == col(User.id))
            .where(PatientAccount.patient_id == patient_id)
        )
    ).first()
    return row


def _account_out(user: User) -> PatientAccountOut:
    return PatientAccountOut(
        user_id=user.id,  # type: ignore[arg-type]
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@router.get("/patients/{patient_id}/account", response_model=PatientAccountOut | None)
async def get_account(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> PatientAccountOut | None:
    patient = await get_owned_patient(session, patient_id, doctor)
    user = await _linked_user(session, patient.id)  # type: ignore[arg-type]
    return _account_out(user) if user else None


@router.put("/patients/{patient_id}/account", response_model=PatientAccountOut)
async def link_account(
    patient_id: int, body: PatientAccountIn, session: SessionDep, doctor: CurrentDoctor
) -> PatientAccountOut:
    """Wiąże kartę z istniejącym kontem pacjenta albo zakłada nowe konto (wymaga hasła)."""
    patient = await get_owned_patient(session, patient_id, doctor)
    email = body.email.lower()
    user = (await session.exec(select(User).where(User.email == email))).first()

    if user is None:
        if not body.password:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Podaj hasło początkowe dla nowego konta pacjenta"
            )
        user = User(
            email=email,
            full_name=(body.full_name or f"{patient.first_name} {patient.last_name}").strip(),
            hashed_password=await hash_password(body.password),
            role=Role.PATIENT.value,
        )
        session.add(user)
        await session.flush()
    else:
        if user.role != Role.PATIENT.value:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Konto z tym adresem e-mail nie jest kontem pacjenta"
            )
        other = (
            await session.exec(
                select(PatientAccount).where(
                    PatientAccount.user_id == user.id, PatientAccount.patient_id != patient.id
                )
            )
        ).first()
        if other is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "To konto jest już powiązane z inną kartą pacjenta"
            )

    await session.exec(delete(PatientAccount).where(col(PatientAccount.patient_id) == patient.id))
    session.add(PatientAccount(patient_id=patient.id, user_id=user.id))  # type: ignore[arg-type]
    await session.commit()
    await session.refresh(user)
    return _account_out(user)


@router.delete("/patients/{patient_id}/account", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(patient_id: int, session: SessionDep, doctor: CurrentDoctor) -> Response:
    """Odłącza konto od karty (samo konto pozostaje – usuwa je administrator)."""
    patient = await get_owned_patient(session, patient_id, doctor)
    await session.exec(delete(PatientAccount).where(col(PatientAccount.patient_id) == patient.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/patients/{patient_id}/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> list[Recommendation]:
    patient = await get_owned_patient(session, patient_id, doctor)
    rows = await session.exec(
        select(Recommendation)
        .where(Recommendation.patient_id == patient.id, Recommendation.user_id == doctor.id)
        .order_by(col(Recommendation.created_at).desc())
    )
    return list(rows.all())


async def _send_notification(
    session: SessionDep, patient: Patient, doctor: User, subject: str, body: str
) -> PatientNotification:
    account = await _linked_user(session, patient.id)  # type: ignore[arg-type]
    if account is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pacjent nie ma powiązanego konta")

    text = (
        f"{body}\n\n—\n{doctor.full_name}\n"
        f"Szczegóły w Twoim panelu pacjenta: {settings.app_public_url}"
    )
    notification = PatientNotification(
        user_id=doctor.id,  # type: ignore[arg-type]
        patient_id=patient.id,  # type: ignore[arg-type]
        recipient=account.email,
        subject=subject,
        body=body,
        status="sent",
    )
    try:
        await mailer.send_email(account.email, subject, text)
    except Exception as exc:
        notification.status = "failed"
        notification.error = str(exc)[:500] or type(exc).__name__
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


@router.post(
    "/patients/{patient_id}/recommendations",
    response_model=RecommendationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_recommendation(
    patient_id: int, body: RecommendationIn, session: SessionDep, doctor: CurrentDoctor
) -> Recommendation:
    patient = await get_owned_patient(session, patient_id, doctor)
    recommendation = Recommendation(
        user_id=doctor.id,  # type: ignore[arg-type]
        patient_id=patient.id,  # type: ignore[arg-type]
        title=body.title.strip(),
        content=body.content.strip(),
    )
    session.add(recommendation)
    await session.commit()
    await session.refresh(recommendation)
    if body.notify and await _linked_user(session, patient.id):  # type: ignore[arg-type]
        await _send_notification(
            session, patient, doctor, f"Nowe zalecenie: {recommendation.title}", body.content
        )
        await session.refresh(recommendation)
    return recommendation


async def _owned_recommendation(
    session: SessionDep, patient: Patient, doctor: User, recommendation_id: int
) -> Recommendation:
    recommendation = (
        await session.exec(
            select(Recommendation).where(
                Recommendation.id == recommendation_id,
                Recommendation.patient_id == patient.id,
                Recommendation.user_id == doctor.id,
            )
        )
    ).first()
    if recommendation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono zalecenia")
    return recommendation


@router.put(
    "/patients/{patient_id}/recommendations/{recommendation_id}",
    response_model=RecommendationOut,
)
async def update_recommendation(
    patient_id: int,
    recommendation_id: int,
    body: RecommendationIn,
    session: SessionDep,
    doctor: CurrentDoctor,
) -> Recommendation:
    patient = await get_owned_patient(session, patient_id, doctor)
    recommendation = await _owned_recommendation(session, patient, doctor, recommendation_id)
    recommendation.title = body.title.strip()
    recommendation.content = body.content.strip()
    recommendation.updated_at = utcnow()
    session.add(recommendation)
    await session.commit()
    await session.refresh(recommendation)
    if body.notify and await _linked_user(session, patient.id):  # type: ignore[arg-type]
        await _send_notification(
            session,
            patient,
            doctor,
            f"Zaktualizowane zalecenie: {recommendation.title}",
            recommendation.content,
        )
        await session.refresh(recommendation)
    return recommendation


@router.delete(
    "/patients/{patient_id}/recommendations/{recommendation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recommendation(
    patient_id: int, recommendation_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    recommendation = await _owned_recommendation(session, patient, doctor, recommendation_id)
    await session.delete(recommendation)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/patients/{patient_id}/notifications", response_model=list[NotificationOut])
async def list_notifications(
    patient_id: int, session: SessionDep, doctor: CurrentDoctor
) -> list[PatientNotification]:
    patient = await get_owned_patient(session, patient_id, doctor)
    rows = await session.exec(
        select(PatientNotification)
        .where(
            PatientNotification.patient_id == patient.id,
            PatientNotification.user_id == doctor.id,
        )
        .order_by(col(PatientNotification.created_at).desc())
    )
    return list(rows.all())


@router.post(
    "/patients/{patient_id}/notifications",
    response_model=NotificationOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_notification(
    patient_id: int, body: NotificationIn, session: SessionDep, doctor: CurrentDoctor
) -> PatientNotification:
    patient = await get_owned_patient(session, patient_id, doctor)
    return await _send_notification(
        session, patient, doctor, body.subject.strip(), body.body.strip()
    )


@router.get("/portal/me", response_model=PatientPortalOut)
async def portal(session: SessionDep, user: CurrentPatient) -> PatientPortalOut:
    row = (
        await session.exec(
            select(Patient, User)
            .join(PatientAccount, col(PatientAccount.patient_id) == col(Patient.id))
            .join(User, col(User.id) == col(Patient.user_id))
            .where(PatientAccount.user_id == user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Konto nie jest jeszcze powiązane z kartą pacjenta"
        )
    patient, doctor = row
    recommendations = await session.exec(
        select(Recommendation)
        .where(Recommendation.patient_id == patient.id)
        .order_by(col(Recommendation.created_at).desc())
    )
    notifications = await session.exec(
        select(PatientNotification)
        .where(PatientNotification.patient_id == patient.id)
        .order_by(col(PatientNotification.created_at).desc())
        .limit(50)
    )
    return PatientPortalOut(
        first_name=patient.first_name,
        last_name=patient.last_name,
        birth_date=patient.birth_date,
        icd_code=patient.icd_code,
        diagnosis=patient.diagnosis,
        doctor_name=doctor.full_name,
        doctor_email=doctor.email,
        recommendations=[RecommendationOut.model_validate(r) for r in recommendations.all()],
        notifications=[NotificationOut.model_validate(n) for n in notifications.all()],
    )
