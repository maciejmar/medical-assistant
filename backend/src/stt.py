"""Integracja z zewnętrznym API Whisper (endpoint zgodny z OpenAI /audio/transcriptions)."""

import logging

import httpx

from .config import settings
from .llm import Usage, track_usage

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    pass


async def transcribe_audio(
    data: bytes,
    *,
    filename: str,
    content_type: str,
    language: str,
    user_id: int,
) -> str:
    headers = {}
    if settings.whisper_api_key:
        headers["Authorization"] = f"Bearer {settings.whisper_api_key}"

    try:
        async with httpx.AsyncClient(timeout=settings.whisper_timeout_seconds) as http:
            response = await http.post(
                settings.whisper_api_url,
                headers=headers,
                files={"file": (filename, data, content_type)},
                data={
                    "model": settings.whisper_model,
                    "language": language,
                    "response_format": "json",
                    "temperature": "0",
                },
            )
    except httpx.HTTPError as exc:
        logger.exception("Błąd połączenia z API Whisper")
        raise TranscriptionError("Usługa transkrypcji jest niedostępna") from exc

    if response.status_code >= 400:
        logger.error("Whisper zwrócił %s: %s", response.status_code, response.text[:300])
        raise TranscriptionError("Usługa transkrypcji odrzuciła plik audio")

    try:
        payload = response.json()
        text = str(payload["text"]).strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise TranscriptionError("Nieprawidłowa odpowiedź usługi transkrypcji") from exc

    raw_usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = Usage()
    if isinstance(raw_usage, dict):
        prompt = int(raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens") or 0)
        completion = int(raw_usage.get("completion_tokens") or raw_usage.get("output_tokens") or 0)
        total = int(raw_usage.get("total_tokens") or 0) or prompt + completion
        usage = Usage(prompt, completion, total)
    track_usage(user_id, settings.whisper_model, "stt_transcription", usage)
    return text
