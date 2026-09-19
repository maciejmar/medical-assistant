"""Czat RAG ze strumieniowaniem Server-Sent Events (tokeny, źródła, licznik zużycia)."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlmodel import col, delete, select

from ..auth import CurrentDoctor, SessionDep
from ..config import settings
from ..database import ChatMessage, Patient, User, session_factory
from ..graph import rag_graph
from .schemas import ChatIn, ChatMessageOut, ConversationOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def describe_patient(patient: Patient) -> str:
    """Kontekst przekazywany do zewnętrznego LLM – bez imienia i nazwiska pacjenta."""
    lines = []
    if patient.birth_date:
        today = date.today()
        age = today.year - patient.birth_date.year
        age -= (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)
        lines.append(f"Wiek: {age} lat")
    if patient.icd_code:
        lines.append(f"Kod ICD: {patient.icd_code}")
    if patient.diagnosis:
        lines.append(f"Rozpoznanie: {patient.diagnosis}")
    if patient.description:
        lines.append(f"Opis: {patient.description[:800]}")
    return "\n".join(lines)


async def _owned_conversation_messages(
    session: SessionDep, user: User, conversation_id: str
) -> list[ChatMessage]:
    rows = await session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.user_id == user.id)
        .order_by(col(ChatMessage.created_at), col(ChatMessage.id))
    )
    return list(rows.all())


async def _save_message(**fields: Any) -> None:
    async with session_factory() as session:
        session.add(ChatMessage(**fields))
        await session.commit()


@router.post("")
async def chat(body: ChatIn, session: SessionDep, doctor: CurrentDoctor) -> StreamingResponse:
    patient_context: str | None = None
    if body.patient_id is not None:
        patient = (
            await session.exec(
                select(Patient).where(Patient.id == body.patient_id, Patient.user_id == doctor.id)
            )
        ).first()
        if patient is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono pacjenta")
        patient_context = describe_patient(patient) or None

    conversation_id = body.conversation_id or str(uuid.uuid4())
    previous = await _owned_conversation_messages(session, doctor, conversation_id)
    if body.conversation_id and not previous:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono rozmowy")
    history = [{"role": m.role, "content": m.content} for m in previous[-settings.history_window :]]

    user_id: int = doctor.id  # type: ignore[assignment]
    await _save_message(
        user_id=user_id,
        conversation_id=conversation_id,
        patient_id=body.patient_id,
        role="user",
        content=body.message,
    )

    initial_state = {
        "user_id": user_id,
        "question": body.message,
        "history": history,
        "patient_context": patient_context,
    }

    async def event_stream() -> AsyncIterator[str]:
        yield sse("meta", {"type": "meta", "conversation_id": conversation_id})
        answer: list[str] = []
        sources: list[dict[str, Any]] = []
        total_tokens = 0
        try:
            async for chunk in rag_graph.astream(initial_state, stream_mode="custom"):
                kind = chunk.get("type")
                if kind == "token":
                    answer.append(chunk["text"])
                elif kind == "sources":
                    sources = chunk["sources"]
                elif kind == "usage":
                    total_tokens = int(chunk.get("total_tokens", 0))
                yield sse(kind, chunk)
        except Exception:
            logger.exception("Błąd przetwarzania czatu RAG")
            yield sse(
                "error", {"type": "error", "message": "Nie udało się wygenerować odpowiedzi."}
            )
            return

        await _save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            patient_id=body.patient_id,
            role="assistant",
            content="".join(answer),
            sources=sources,
            total_tokens=total_tokens,
        )
        yield sse("done", {"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    session: SessionDep, doctor: CurrentDoctor, limit: int = 30
) -> list[ConversationOut]:
    limit = max(1, min(limit, 100))
    grouped = await session.exec(
        select(
            ChatMessage.conversation_id,
            func.count(col(ChatMessage.id)),
            func.max(col(ChatMessage.created_at)),
        )
        .where(ChatMessage.user_id == doctor.id)
        .group_by(col(ChatMessage.conversation_id))
        .order_by(func.max(col(ChatMessage.created_at)).desc())
        .limit(limit)
    )
    result: list[ConversationOut] = []
    for conversation_id, count, updated_at in grouped.all():
        first = (
            await session.exec(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.user_id == doctor.id,
                    ChatMessage.role == "user",
                )
                .order_by(col(ChatMessage.created_at), col(ChatMessage.id))
                .limit(1)
            )
        ).first()
        title = (first.content[:60] if first else "Rozmowa").strip()
        result.append(
            ConversationOut(
                conversation_id=conversation_id,
                title=title,
                message_count=count,
                updated_at=updated_at,
            )
        )
    return result


@router.get("/conversations/{conversation_id}", response_model=list[ChatMessageOut])
async def get_conversation(
    conversation_id: str, session: SessionDep, doctor: CurrentDoctor
) -> list[ChatMessage]:
    messages = await _owned_conversation_messages(session, doctor, conversation_id)
    if not messages:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono rozmowy")
    return messages


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str, session: SessionDep, doctor: CurrentDoctor
) -> Response:
    await session.exec(
        delete(ChatMessage).where(
            col(ChatMessage.conversation_id) == conversation_id,
            col(ChatMessage.user_id) == doctor.id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
