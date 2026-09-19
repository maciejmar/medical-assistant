from fastapi import APIRouter

from . import admin, audio, auth, chat, patients

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(patients.router)
api_router.include_router(chat.router)
api_router.include_router(audio.router)
api_router.include_router(admin.router)
