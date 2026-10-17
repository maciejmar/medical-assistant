"""Panel administratora: metryki zużycia, zarządzanie kontami i podgląd komunikacji z LLM.

Administrator nie ma dostępu do kart pacjentów ani notatek innych lekarzy. Widzi natomiast
pełną treść żądań wysyłanych do LLM i odpowiedzi (tabela llm_calls) – kontekst pacjenta
trafia tam w postaci zanonimizowanej (bez imienia i nazwiska).
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select

from ..auth import CurrentAdmin, SessionDep, hash_password
from ..database import (
    ChatMessage,
    LlmCall,
    Patient,
    PatientAccount,
    Role,
    TokenUsage,
    User,
    utcnow,
)
from ..vector_store import vector_store
from .patients import purge_patients
from .schemas import (
    LlmCallDetail,
    LlmCallPage,
    LlmCallSummary,
    SystemStatsOut,
    UsageBucket,
    UsageByDay,
    UsageByModel,
    UsageByOperation,
    UsageByUser,
    UsageOut,
    UserCreateIn,
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
    return int((await session.exec(statement)).one())


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
        patient_accounts=await _count(
            session, select(func.count(col(User.id))).where(User.role == Role.PATIENT.value)
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


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateIn, session: SessionDep, admin: CurrentAdmin) -> User:
    email = body.email.lower()
    if (await session.exec(select(User).where(User.email == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Konto z tym adresem e-mail już istnieje")
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        hashed_password=await hash_password(body.password),
        role=body.role,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Konto z tym adresem e-mail już istnieje"
        ) from None
    await session.refresh(user)
    return user


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
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.password is not None:
        user.hashed_password = await hash_password(body.password)
    if body.role is not None and body.role != user.role:
        if user.role == Role.PATIENT.value:
            await session.exec(delete(PatientAccount).where(col(PatientAccount.user_id) == user.id))
        user.role = body.role
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    user = await _get_other_user(session, admin, user_id)
    patient_ids = (await session.exec(select(Patient.id).where(Patient.user_id == user.id))).all()
    await purge_patients(session, [pid for pid in patient_ids if pid is not None])
    await session.exec(delete(PatientAccount).where(col(PatientAccount.user_id) == user.id))
    await session.exec(delete(ChatMessage).where(col(ChatMessage.user_id) == user.id))
    await session.exec(
        update(TokenUsage).where(col(TokenUsage.user_id) == user.id).values(user_id=None)
    )
    await session.exec(update(LlmCall).where(col(LlmCall.user_id) == user.id).values(user_id=None))
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _preview(request: list | dict) -> str:
    """Ostatnia wiadomość użytkownika (czat) albo pierwszy tekst (embedding) – do listy."""
    text = ""
    if isinstance(request, list):
        users = [m for m in request if isinstance(m, dict) and m.get("role") == "user"]
        if users:
            text = str(users[-1].get("content", ""))
    elif isinstance(request, dict):
        inputs = request.get("input") or []
        if inputs:
            text = str(inputs[0])
    return " ".join(text.split())[:200]


def _summary(call: LlmCall, email: str | None) -> dict:
    return {
        "id": call.id,
        "timestamp": call.timestamp,
        "user_id": call.user_id,
        "user_email": email,
        "operation": call.operation,
        "model_name": call.model_name,
        "status": call.status,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
        "total_tokens": call.total_tokens,
        "duration_ms": call.duration_ms,
        "preview": _preview(call.request),
    }


@router.get("/llm-calls", response_model=LlmCallPage)
async def list_llm_calls(
    session: SessionDep,
    admin: CurrentAdmin,
    operation: str | None = None,
    user_id: int | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LlmCallPage:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conditions = []
    if operation:
        conditions.append(col(LlmCall.operation) == operation)
    if user_id is not None:
        conditions.append(col(LlmCall.user_id) == user_id)
    if status_filter:
        conditions.append(col(LlmCall.status) == status_filter)

    total = await _count(session, select(func.count(col(LlmCall.id))).where(*conditions))
    rows = await session.exec(
        select(LlmCall, User.email)
        .join(User, col(User.id) == col(LlmCall.user_id), isouter=True)
        .where(*conditions)
        .order_by(col(LlmCall.timestamp).desc(), col(LlmCall.id).desc())
        .offset(offset)
        .limit(limit)
    )
    return LlmCallPage(
        total=total,
        items=[LlmCallSummary(**_summary(call, email)) for call, email in rows.all()],
    )


@router.get("/llm-calls/{call_id}", response_model=LlmCallDetail)
async def get_llm_call(call_id: int, session: SessionDep, admin: CurrentAdmin) -> LlmCallDetail:
    row = (
        await session.exec(
            select(LlmCall, User.email)
            .join(User, col(User.id) == col(LlmCall.user_id), isouter=True)
            .where(LlmCall.id == call_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono wywołania")
    call, email = row
    return LlmCallDetail(
        **_summary(call, email), request=call.request, response=call.response, error=call.error
    )
