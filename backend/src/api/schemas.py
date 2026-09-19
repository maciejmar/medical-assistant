from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class ConversationOut(BaseModel):
    conversation_id: str
    title: str
    message_count: int
    updated_at: datetime


class TranscriptionOut(BaseModel):
    text: str


class UserPatch(BaseModel):
    is_active: bool | None = None
    role: Literal["ROLE_DOCTOR", "ROLE_ADMIN"] | None = None


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
    patients_total: int
    conversations_total: int
    knowledge_base_documents: int | None
