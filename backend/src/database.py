from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings


class Role(StrEnum):
    DOCTOR = "ROLE_DOCTOR"
    ADMIN = "ROLE_ADMIN"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts(index: bool = False):
    return Field(default_factory=utcnow, sa_type=DateTime(timezone=True), index=index)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=254)
    full_name: str = Field(max_length=200)
    hashed_password: str
    role: str = Field(default=Role.DOCTOR.value, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = _ts()


class Patient(SQLModel, table=True):
    __tablename__ = "patients"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    birth_date: date | None = Field(default=None)
    icd_code: str | None = Field(default=None, max_length=20)
    diagnosis: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = _ts()
    updated_at: datetime = _ts()


class PatientNote(SQLModel, table=True):
    __tablename__ = "patient_notes"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    content: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(default="typed", max_length=20)
    created_at: datetime = _ts(index=True)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    conversation_id: str = Field(index=True, max_length=36)
    patient_id: int | None = Field(default=None)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text, nullable=False))
    sources: list | None = Field(default=None, sa_column=Column(JSON))
    total_tokens: int = Field(default=0)
    created_at: datetime = _ts(index=True)


class TokenUsage(SQLModel, table=True):
    __tablename__ = "token_usage"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    )
    timestamp: datetime = _ts(index=True)
    model_name: str = Field(max_length=200, index=True)
    operation: str = Field(max_length=50, index=True)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)


engine = create_async_engine(settings.db_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
