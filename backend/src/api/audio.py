from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from ..auth import CurrentDoctor
from ..config import settings
from ..stt import TranscriptionError, transcribe_audio
from .schemas import TranscriptionOut

router = APIRouter(prefix="/audio", tags=["audio"])

ALLOWED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".mpeg",
    ".mpga",
    ".m4a",
    ".mp4",
    ".webm",
    ".ogg",
    ".oga",
    ".flac",
}


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    doctor: CurrentDoctor,
    audio: Annotated[UploadFile, File(description="Plik audio (wav, mp3, webm, ogg, m4a…)")],
    language: Annotated[str, Form(pattern=r"^[a-z]{2}$")] = "pl",
) -> TranscriptionOut:
    filename = PurePath(audio.filename or "recording.webm").name
    extension = PurePath(filename).suffix.lower()
    content_type = (audio.content_type or "").split(";")[0]
    if extension not in ALLOWED_EXTENSIONS and not content_type.startswith(
        ("audio/", "video/webm")
    ):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Nieobsługiwany format audio")

    data = await audio.read(settings.max_audio_bytes + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plik audio jest pusty")
    if len(data) > settings.max_audio_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Plik audio jest zbyt duży")

    try:
        text = await transcribe_audio(
            data,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            language=language,
            user_id=doctor.id,  # type: ignore[arg-type]
        )
    except TranscriptionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return TranscriptionOut(text=text)
