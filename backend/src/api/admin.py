"""Panel administratora: wyłącznie zanonimizowane metryki zużycia i zarządzanie kontami.

Administrator nie ma dostępu do pacjentów, notatek ani treści czatów – żaden z endpointów
nie odpytuje tabel patients, patient_notes ani nie zwraca pól content z chat_history.
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, update
from sqlmodel import col, delete, select

from ..auth import CurrentAdmin, SessionDep
from ..database import ChatMessage, Patient, PatientNote, Role, TokenUsage, User, utcnow
from ..vector_store import vector_store
from .schemas import (
    SystemStatsOut,
    UsageBucket,
    UsageByDay,
    UsageByModel,
    UsageByOperation,
    UsageByUser,
    UsageOut,
    UserOut,
    UserPatch,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _sums():
    return (
        func.coalesce(func.sum(col(TokenUsage.prompt_tokens)), 0),
        func.coalesce(func.sum(col(TokenUsage.completion_tokens)), 0),
        func.coalesce(func.sum(col(TokenUsage.total_tokens)), 0),
        func.count(col(TokenUsage.id)),
    )


def _bucket(prompt, completion, total, requests) -> dict[str, int]:
    return {
        "prompt_tokens": int(prompt),
        "completion_tokens": int(completion),
        "total_tokens": int(total),
        "requests": int(requests),
    }


@router.get("/usage", response_model=UsageOut)
async def usage(session: SessionDep, admin: CurrentAdmin, days: int = 30) -> UsageOut:
    days = max(1, min(days, 365))
    since = utcnow() - timedelta(days=days)
    in_range = col(TokenUsage.timestamp) >= since

    total_row = (await session.exec(select(*_sums()).where(in_range))).one()

    day_col = func.date(col(TokenUsage.timestamp))
    by_day_rows = await session.exec(
        select(day_col, *_sums()).where(in_range).group_by(day_col).order_by(day_col)
    )
    by_user_rows = await session.exec(
        select(col(TokenUsage.user_id), *_sums())
        .where(in_range)
        .group_by(col(TokenUsage.user_id))
        .order_by(func.sum(col(TokenUsage.total_tokens)).desc())
    )
    by_model_rows = await session.exec(
        select(col(TokenUsage.model_name), *_sums())
        .where(in_range)
        .group_by(col(TokenUsage.model_name))
        .order_by(func.sum(col(TokenUsage.total_tokens)).desc())
    )
    by_operation_rows = await session.exec(
        select(col(TokenUsage.operation), *_sums())
        .where(in_range)
        .group_by(col(TokenUsage.operation))
        .order_by(func.sum(col(TokenUsage.total_tokens)).desc())
    )

    return UsageOut(
        days=days,
        totals=UsageBucket(**_bucket(*total_row)),
        by_day=[UsageByDay(date=str(r[0]), **_bucket(*r[1:])) for r in by_day_rows.all()],
        by_user=[
            UsageByUser(
                user_id=r[0],
                label=f"Użytkownik #{r[0]}" if r[0] is not None else "System (seeding)",
                **_bucket(*r[1:]),
            )
            for r in by_user_rows.all()
        ],
        by_model=[UsageByModel(model_name=r[0], **_bucket(*r[1:])) for r in by_model_rows.all()],
        by_operation=[
            UsageByOperation(operation=r[0], **_bucket(*r[1:])) for r in by_operation_rows.all()
        ],
    )


async def _count(session: SessionDep, statement) -> int:
    return int((await session.exec(statement)).scalar_one())


@router.get("/stats", response_model=SystemStatsOut)
async def stats(session: SessionDep, admin: CurrentAdmin) -> SystemStatsOut:
    try:
        kb_documents: int | None = await vector_store.count()
    except Exception:
        kb_documents = None
    return SystemStatsOut(
        users_total=await _count(session, select(func.count(col(User.id)))),
        users_active=await _count(
            session, select(func.count(col(User.id))).where(col(User.is_active).is_(True))
        ),
        doctors=await _count(
            session, select(func.count(col(User.id))).where(User.role == Role.DOCTOR.value)
        ),
        admins=await _count(
            session, select(func.count(col(User.id))).where(User.role == Role.ADMIN.value)
        ),
        patients_total=await _count(session, select(func.count(col(Patient.id)))),
        conversations_total=await _count(
            session, select(func.count(func.distinct(col(ChatMessage.conversation_id))))
        ),
        knowledge_base_documents=kb_documents,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(session: SessionDep, admin: CurrentAdmin) -> list[User]:
    return list((await session.exec(select(User).order_by(col(User.id)))).all())


async def _get_other_user(session: SessionDep, admin: User, user_id: int) -> User:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nie można zmienić własnego konta")
    user = (await session.exec(select(User).where(User.id == user_id))).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono użytkownika")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, body: UserPatch, session: SessionDep, admin: CurrentAdmin
) -> User:
    user = await _get_other_user(session, admin, user_id)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    user = await _get_other_user(session, admin, user_id)
    await session.exec(delete(PatientNote).where(col(PatientNote.user_id) == user.id))
    await session.exec(delete(Patient).where(col(Patient.user_id) == user.id))
    await session.exec(delete(ChatMessage).where(col(ChatMessage.user_id) == user.id))
    await session.exec(
        update(TokenUsage).where(col(TokenUsage.user_id) == user.id).values(user_id=None)
    )
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
