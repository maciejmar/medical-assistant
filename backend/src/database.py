from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings


class Role(StrEnum):
    DOCTOR = "ROLE_DOCTOR"
    ADMIN = "ROLE_ADMIN"
    PATIENT = "ROLE_PATIENT"


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


class PatientAccount(SQLModel, table=True):
    """Powiązanie karty pacjenta (należącej do lekarza) z kontem użytkownika o roli pacjenta."""

    __tablename__ = "patient_accounts"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), unique=True, nullable=False)
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    )
    created_at: datetime = _ts()


class Recommendation(SQLModel, table=True):
    """Zalecenia terapeutyczne widoczne dla pacjenta w jego panelu."""

    __tablename__ = "patient_recommendations"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    title: str = Field(max_length=200)
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = _ts(index=True)
    updated_at: datetime = _ts()


class PatientNotification(SQLModel, table=True):
    __tablename__ = "patient_notifications"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    recipient: str = Field(max_length=254)
    subject: str = Field(max_length=200)
    body: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(max_length=20)
    error: str | None = Field(default=None, max_length=500)
    created_at: datetime = _ts(index=True)


class InterviewTemplate(SQLModel, table=True):
    """Szablon pytań wywiadu (jeden wiersz, id=1), edytowany przez administratora.
    Brak wiersza = domyślne pytania z src.api.interview.DEFAULT_QUESTIONS."""

    __tablename__ = "interview_templates"

    id: int | None = Field(default=None, primary_key=True)
    questions: list = Field(sa_column=Column(JSON, nullable=False))
    updated_by: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("users.id"), nullable=True)
    )
    updated_at: datetime = _ts()


class PatientInterview(SQLModel, table=True):
    """Stan wywiadu pacjenta. `approved_items` to migawka [{question, answer}] z chwili
    zatwierdzenia – tylko ona trafia do kontekstu LLM (kolejne poprawki dopiero po ponownym
    zatwierdzeniu)."""

    __tablename__ = "patient_interviews"

    patient_id: int = Field(sa_column=Column(Integer, ForeignKey("patients.id"), primary_key=True))
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    status: str = Field(default="draft", max_length=20)
    approved_items: list | None = Field(default=None, sa_column=Column(JSON))
    approved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = _ts()
    updated_at: datetime = _ts()


class InterviewItem(SQLModel, table=True):
    """Pytanie wywiadu z odpowiedzią (wpisaną przez lekarza lub z transkrypcji nagrania)."""

    __tablename__ = "patient_interview_items"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    position: int = Field(default=0)
    question: str = Field(sa_column=Column(Text, nullable=False))
    answer: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = _ts()
    updated_at: datetime = _ts()


class InterviewAudio(SQLModel, table=True):
    """Nagranie odpowiedzi pacjenta na pytanie wywiadu (osobna tabela, żeby lista pytań nie
    ładowała danych binarnych)."""

    __tablename__ = "patient_interview_audio"

    item_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patient_interview_items.id"), primary_key=True)
    )
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    content_type: str = Field(max_length=100)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    size: int = Field(default=0)
    created_at: datetime = _ts()


class PatientPlan(SQLModel, table=True):
    """Ustawienia planu działania pacjenta (brak wiersza = plan nie trafia do kontekstu LLM)."""

    __tablename__ = "patient_plans"

    patient_id: int = Field(sa_column=Column(Integer, ForeignKey("patients.id"), primary_key=True))
    include_in_context: bool = Field(default=False)
    updated_at: datetime = _ts()


class PlanStep(SQLModel, table=True):
    """Krok planu działania: status `planned` | `completed` | `suspended` | `infeasible`."""

    __tablename__ = "patient_plan_steps"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    position: int = Field(default=0)
    title: str = Field(max_length=200)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default="planned", max_length=20)
    created_at: datetime = _ts()
    updated_at: datetime = _ts()


class PatientEvent(SQLModel, table=True):
    """Wydarzenie w kalendarzu pacjenta – wspólne dla lekarza prowadzącego i pacjenta.

    type: `visit` | `consultation` | `stage_start` | `stage_end` | `other`.
    created_by/created_by_role – autor (bez klucza obcego, żeby usunięcie konta pacjenta nie
    blokowało usuwania; pacjent może edytować tylko własne wpisy).
    """

    __tablename__ = "patient_events"

    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(
        sa_column=Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    )
    type: str = Field(max_length=20)
    title: str = Field(max_length=200)
    starts_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)
    ends_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    all_day: bool = Field(default=False)
    location: str = Field(default="", max_length=300)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    plan_step_id: int | None = Field(default=None)
    created_by: int | None = Field(default=None)
    created_by_role: str = Field(default="doctor", max_length=20)
    created_at: datetime = _ts()
    updated_at: datetime = _ts()


class LlmCall(SQLModel, table=True):
    """Pełny zapis żądania wysłanego do LLM i otrzymanej odpowiedzi (wgląd dla administratora)."""

    __tablename__ = "llm_calls"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    )
    timestamp: datetime = _ts(index=True)
    model_name: str = Field(max_length=200)
    operation: str = Field(max_length=50, index=True)
    request: list | dict = Field(sa_column=Column(JSON, nullable=False))
    response: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default="ok", max_length=20)
    error: str | None = Field(default=None, max_length=1000)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    duration_ms: int = Field(default=0)


class KbDocument(SQLModel, table=True):
    """Plik wgrany przez administratora do bazy wiedzy. Tekst jest przechowywany, żeby można
    było odtworzyć indeks Qdrant (np. po zmianie modelu embeddingów)."""

    __tablename__ = "kb_documents"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=300)
    filename: str = Field(max_length=300)
    category: str = Field(max_length=30)
    audience: str = Field(max_length=20)
    icd10: str = Field(default="", max_length=50)
    icd11: str = Field(default="", max_length=50)
    tags: str = Field(default="", max_length=500)
    text: str = Field(sa_column=Column(Text, nullable=False))
    chunks: int = Field(default=0)
    status: str = Field(default="pending", max_length=20)
    error: str | None = Field(default=None, max_length=1000)
    uploaded_by: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("users.id"), nullable=True)
    )
    # Import z katalogu: ścieżka względna pliku/grupy zdjęć i suma kontrolna treści źródłowej –
    # pozwalają pominąć niezmienione materiały przy kolejnym imporcie.
    source_path: str | None = Field(default=None, max_length=500, index=True)
    content_hash: str = Field(default="", max_length=64)
    pages: int = Field(default=0)
    created_at: datetime = _ts(index=True)
    indexed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class KbPrivateDocument(SQLModel, table=True):
    """Dokument bazy wiedzy widoczny tylko dla właściciela (brak wpisu = wiedza wspólna).
    Osobna tabela zamiast kolumny w kb_documents – bez migracji istniejącej tabeli."""

    __tablename__ = "kb_private_documents"

    document_id: int = Field(
        sa_column=Column(Integer, ForeignKey("kb_documents.id"), primary_key=True)
    )
    owner_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    created_at: datetime = _ts()


class OcrCacheEntry(SQLModel, table=True):
    """Pamięć podręczna OCR per silnik: (SHA-256 obrazu, klucz silnika z parametrami).
    Pozwala porównywać i przełączać silniki bez utraty wcześniejszych odczytów."""

    __tablename__ = "kb_ocr_results"

    sha256: str = Field(primary_key=True, max_length=64)
    engine: str = Field(primary_key=True, max_length=120)
    text: str = Field(sa_column=Column(Text, nullable=False))
    confidence: float = Field(default=0.0)
    created_at: datetime = _ts()


class OcrPage(SQLModel, table=True):
    """Pierwotna pamięć podręczna OCR (tylko Tesseract, przed wprowadzeniem wyboru silnika) –
    odczytywana jako wyniki silnika o kluczu LEGACY_TESSERACT_KEY."""

    __tablename__ = "kb_ocr_pages"

    sha256: str = Field(primary_key=True, max_length=64)
    text: str = Field(sa_column=Column(Text, nullable=False))
    confidence: float = Field(default=0.0)
    created_at: datetime = _ts()


engine = create_async_engine(settings.db_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
