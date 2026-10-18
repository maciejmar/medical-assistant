from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

RoleName = Literal["ROLE_DOCTOR", "ROLE_ADMIN", "ROLE_PATIENT"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=72)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PatientIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    birth_date: date | None = None
    icd_code: str | None = Field(default=None, max_length=20)
    diagnosis: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)


class PatientOut(PatientIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    source: Literal["typed", "dictated"] = "typed"


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    content: str
    source: str
    created_at: datetime


class RecentNoteOut(BaseModel):
    note_id: int
    patient_id: int
    patient_name: str
    snippet: str
    source: str
    created_at: datetime


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=36)
    patient_id: int | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    sources: list | None
    total_tokens: int
    created_at: datetime


class PatientChatMessageOut(ChatMessageOut):
    conversation_id: str


class ConversationOut(BaseModel):
    conversation_id: str
    title: str
    message_count: int
    updated_at: datetime


class TranscriptionOut(BaseModel):
    text: str


class UserPatch(BaseModel):
    is_active: bool | None = None
    role: RoleName | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=72)


class UsageBucket(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    requests: int


class UsageByDay(UsageBucket):
    date: str


class UsageByUser(UsageBucket):
    user_id: int | None
    label: str


class UsageByModel(UsageBucket):
    model_name: str


class UsageByOperation(UsageBucket):
    operation: str


class UsageOut(BaseModel):
    days: int
    totals: UsageBucket
    by_day: list[UsageByDay]
    by_user: list[UsageByUser]
    by_model: list[UsageByModel]
    by_operation: list[UsageByOperation]


class SystemStatsOut(BaseModel):
    users_total: int
    users_active: int
    doctors: int
    admins: int
    patient_accounts: int
    patients_total: int
    conversations_total: int
    knowledge_base_documents: int | None


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=72)
    role: RoleName = "ROLE_DOCTOR"


class LlmCallSummary(BaseModel):
    id: int
    timestamp: datetime
    user_id: int | None
    user_email: str | None
    operation: str
    model_name: str
    status: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    preview: str


class LlmCallPage(BaseModel):
    total: int
    items: list[LlmCallSummary]


class LlmCallDetail(LlmCallSummary):
    request: list | dict
    response: str
    error: str | None


class PatientAccountIn(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=72)


class PatientAccountOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    is_active: bool


class RecommendationIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    notify: bool = False


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class NotificationIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    recipient: str
    subject: str
    body: str
    status: str
    error: str | None
    created_at: datetime


class PatientPortalOut(BaseModel):
    first_name: str
    last_name: str
    birth_date: date | None
    icd_code: str | None
    diagnosis: str | None
    doctor_name: str
    doctor_email: str
    recommendations: list[RecommendationOut]
    notifications: list[NotificationOut]


class KbDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    filename: str
    category: str
    audience: str
    icd10: str
    icd11: str
    tags: str
    chunks: int
    status: str
    error: str | None
    created_at: datetime
    indexed_at: datetime | None
    source_path: str | None
    pages: int
    characters: int
    preview: str


class KbDocumentPatch(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    category: Literal["disorder", "icd", "technique", "diagnostics"]
    audience: Literal["children", "adults", "all"]
    icd10: str = Field(default="", max_length=50)
    icd11: str = Field(default="", max_length=50)
    tags: str = Field(default="", max_length=500)


class KbImportRecentOut(BaseModel):
    path: str
    title: str
    status: Literal["created", "updated", "failed"]
    pages: int
    chunks: int
    error: str | None


class KbImportProgressOut(BaseModel):
    phase: Literal["idle", "scan", "ocr", "extract", "embed", "done"]
    fraction: float
    elapsed_seconds: int
    eta_seconds: int | None
    units_total: int
    units_done: int
    unchanged: int
    created: int
    updated: int
    failed: int
    unit_title: str
    unit_path: str
    unit_kind: str
    step_done: int
    step_total: int
    recent: list[KbImportRecentOut]


class KbImportStatusOut(BaseModel):
    source_dir: str
    source_available: bool
    running: bool
    started_at: datetime | None
    finished_at: datetime | None
    progress: KbImportProgressOut
    summary: str
    failed: list[str]
    error: str | None
    trigger: str
    auto_scan_seconds: int


class KbStoredFileOut(BaseModel):
    path: str
    changed: bool


class KnowledgeBaseOut(BaseModel):
    builtin_documents: int
    documents: list[KbDocumentOut]
