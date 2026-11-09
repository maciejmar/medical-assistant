"""Propozycja następnego kroku planu działania – osobny moduł (korzysta z kontekstu pacjenta
z api.chat, który sam importuje api.plan)."""

import json
import logging

from fastapi import APIRouter, HTTPException, status

from .. import plan_advisor
from ..auth import CurrentDoctor, SessionDep
from .chat import describe_patient
from .interview import approved_interview
from .patients import get_owned_patient
from .schemas import PlanSuggestionOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plan"])


@router.post("/patients/{patient_id}/plan/suggest", response_model=PlanSuggestionOut)
async def suggest_step(patient_id: int, session: SessionDep, doctor: CurrentDoctor) -> dict:
    """Jeden proponowany krok (diagnostyka albo etap terapii) – nic nie zapisuje."""
    patient = await get_owned_patient(session, patient_id, doctor)
    interview = await approved_interview(session, patient.id)  # type: ignore[arg-type]
    context = describe_patient(patient, interview)
    try:
        return await plan_advisor.suggest_next_step(session, patient, doctor, context)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Nieczytelna propozycja kroku od modelu: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Asystent zwrócił nieczytelną propozycję – spróbuj ponownie",
        ) from exc
    except Exception as exc:
        logger.exception("Nie udało się przygotować propozycji kroku")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Nie udało się przygotować propozycji – spróbuj za chwilę"
        ) from exc
