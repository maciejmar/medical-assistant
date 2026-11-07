"""Plan działania pacjenta: uporządkowana lista kroków z opisem i statusem.

Plan trafia do kontekstu LLM tylko, gdy lekarz włączy `include_in_context` dla danego pacjenta.
"""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, func, select

from ..auth import CurrentDoctor, SessionDep
from ..database import PatientPlan, PlanStep, utcnow
from .patients import get_owned_patient
from .schemas import PlanOrderIn, PlanOut, PlanSettingsIn, PlanStepIn, PlanStepOut

router = APIRouter(tags=["plan"])

STATUS_LABELS = {
    "planned": "zaplanowany",
    "completed": "zakończony",
    "suspended": "zawieszony",
    "infeasible": "niewykonalny",
}


async def _steps(session: SessionDep, patient_id: int) -> list[PlanStep]:
    rows = await session.exec(
        select(PlanStep)
        .where(PlanStep.patient_id == patient_id)
        .order_by(col(PlanStep.position), col(PlanStep.id))
    )
    return list(rows.all())


async def _owned_step(session: SessionDep, patient_id: int, step_id: int) -> PlanStep:
    step = (
        await session.exec(
            select(PlanStep).where(PlanStep.id == step_id, PlanStep.patient_id == patient_id)
        )
    ).first()
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono kroku planu")
    return step


@router.get("/patients/{patient_id}/plan", response_model=PlanOut)
async def get_plan(patient_id: int, session: SessionDep, doctor: CurrentDoctor) -> PlanOut:
    patient = await get_owned_patient(session, patient_id, doctor)
    settings = await session.get(PatientPlan, patient.id)
    steps = await _steps(session, patient.id)  # type: ignore[arg-type]
    return PlanOut(
        include_in_context=bool(settings and settings.include_in_context),
        steps=[PlanStepOut.model_validate(s) for s in steps],
    )


@router.put("/patients/{patient_id}/plan/settings", response_model=PlanSettingsIn)
async def save_settings(
    patient_id: int, body: PlanSettingsIn, session: SessionDep, doctor: CurrentDoctor
) -> PlanSettingsIn:
    patient = await get_owned_patient(session, patient_id, doctor)
    settings = await session.get(PatientPlan, patient.id) or PatientPlan(
        patient_id=patient.id  # type: ignore[arg-type]
    )
    settings.include_in_context = body.include_in_context
    settings.updated_at = utcnow()
    session.add(settings)
    await session.commit()
    return PlanSettingsIn(include_in_context=settings.include_in_context)


@router.post(
    "/patients/{patient_id}/plan/steps",
    response_model=PlanStepOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_step(
    patient_id: int, body: PlanStepIn, session: SessionDep, doctor: CurrentDoctor
) -> PlanStep:
    """Nowy krok trafia na koniec planu."""
    patient = await get_owned_patient(session, patient_id, doctor)
    last = (
        await session.exec(
            select(func.max(PlanStep.position)).where(PlanStep.patient_id == patient.id)
        )
    ).one()
    step = PlanStep(
        patient_id=patient.id,  # type: ignore[arg-type]
        position=(last if last is not None else -1) + 1,
        title=body.title.strip(),
        description=body.description.strip(),
        status=body.status,
    )
    session.add(step)
    await session.commit()
    await session.refresh(step)
    return step


@router.put("/patients/{patient_id}/plan/steps/{step_id}", response_model=PlanStepOut)
async def update_step(
    patient_id: int, step_id: int, body: PlanStepIn, session: SessionDep, doctor: CurrentDoctor
) -> PlanStep:
    patient = await get_owned_patient(session, patient_id, doctor)
    step = await _owned_step(session, patient.id, step_id)  # type: ignore[arg-type]
    step.title = body.title.strip()
    step.description = body.description.strip()
    step.status = body.status
    step.updated_at = utcnow()
    session.add(step)
    await session.commit()
    await session.refresh(step)
    return step


@router.delete(
    "/patients/{patient_id}/plan/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_step(
    patient_id: int, step_id: int, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    patient = await get_owned_patient(session, patient_id, doctor)
    step = await _owned_step(session, patient.id, step_id)  # type: ignore[arg-type]
    await session.delete(step)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/patients/{patient_id}/plan/order", response_model=list[PlanStepOut])
async def reorder_steps(
    patient_id: int, body: PlanOrderIn, session: SessionDep, doctor: CurrentDoctor
) -> list[PlanStep]:
    """Nowa kolejność kroków – lista musi zawierać dokładnie wszystkie kroki planu."""
    patient = await get_owned_patient(session, patient_id, doctor)
    steps = {s.id: s for s in await _steps(session, patient.id)}  # type: ignore[arg-type]
    if sorted(body.step_ids) != sorted(steps):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lista kroków nie zgadza się z planem")
    for position, step_id in enumerate(body.step_ids):
        steps[step_id].position = position
        session.add(steps[step_id])
    await session.commit()
    return await _steps(session, patient.id)  # type: ignore[arg-type]


async def plan_for_context(session: SessionDep, patient_id: int) -> list[dict[str, str]]:
    """Kroki planu do kontekstu LLM – pusta lista, gdy lekarz nie włączył tej opcji."""
    settings = await session.get(PatientPlan, patient_id)
    if settings is None or not settings.include_in_context:
        return []
    return [
        {
            "title": s.title,
            "status": STATUS_LABELS.get(s.status, s.status),
            "description": s.description,
        }
        for s in await _steps(session, patient_id)
    ]
