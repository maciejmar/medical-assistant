from fastapi import APIRouter

from . import (
    admin,
    audio,
    auth,
    billing,
    calendar,
    chat,
    interview,
    knowledge,
    patient_portal,
    patients,
    plan,
    plan_suggest,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(patients.router)
api_router.include_router(patient_portal.router)
api_router.include_router(interview.router)
api_router.include_router(plan.router)
api_router.include_router(plan_suggest.router)
api_router.include_router(calendar.router)
api_router.include_router(billing.router)
api_router.include_router(chat.router)
api_router.include_router(audio.router)
api_router.include_router(admin.router)
api_router.include_router(knowledge.router)
