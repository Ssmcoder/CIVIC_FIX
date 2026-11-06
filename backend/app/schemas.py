"""Pydantic schemas — strict validation, extra=forbid everywhere (CF-14)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Strict = ConfigDict(extra="forbid")

Phone = Annotated[str, Field(pattern=r"^\+?[1-9]\d{7,14}$")]
Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]


# ------------------------------------------------------------- citizen side

class ComplaintCreate(BaseModel):
    model_config = Strict
    description: str = Field(min_length=3, max_length=2000)
    lat: Lat | None = None
    lon: Lon | None = None
    landmark_text: str | None = Field(default=None, max_length=300)
    manual_location_confirmed: bool = False
    language: str = Field(default="en", max_length=20)
    source: Literal["form", "chat", "voice", "qr", "api"] = "form"
    transcript: str | None = Field(default=None, max_length=5000)
    contact_phone: Phone | None = None
    contact_email: str | None = Field(default=None, max_length=160)
    anonymous: bool = False
    category_override: str | None = Field(default=None, max_length=40)

    @field_validator("contact_email")
    @classmethod
    def _email(cls, v):
        if v is None:
            return v
        from pydantic import EmailStr, TypeAdapter
        return str(TypeAdapter(EmailStr).validate_python(v))


class VerifyRequest(BaseModel):
    model_config = Strict
    action: Literal["confirm", "reject"]
    reason: str | None = Field(default=None, max_length=500)
    token: str = Field(min_length=10, max_length=200)


class SupportRequest(BaseModel):
    model_config = Strict
    token: str = Field(min_length=10, max_length=200)


# ------------------------------------------------------------- chat

class ChatSessionCreate(BaseModel):
    model_config = Strict


class ChatMessageIn(BaseModel):
    model_config = Strict
    content: str = Field(default="", max_length=4000)
    audio_transcript: str | None = Field(default=None, max_length=5000)
    # image_data_url removed in favour of multipart upload (CF-14)


class ChatActionIn(BaseModel):
    """Discriminated union for chat session actions (CF-14)."""
    model_config = Strict
    action: Literal["set_location", "confirm_location_candidate", "set_category",
                    "submit_intake", "cancel_intake", "set_contact"]
    lat: Lat | None = None
    lon: Lon | None = None
    name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=40)
    phone: Phone | None = None
    email: str | None = None
    anonymous: bool | None = None


class ChatFeedbackIn(BaseModel):
    model_config = Strict
    message_id: str = Field(min_length=8, max_length=64)
    score: Literal[1, -1]


# ------------------------------------------------------------- admin

class AdminLogin(BaseModel):
    model_config = Strict
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=12)


class AdminCreate(BaseModel):
    model_config = Strict
    email: str = Field(max_length=160)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(default="", max_length=160)
    role: Literal["super_admin", "state_admin", "district_admin",
                  "municipal_admin", "ward_admin"] = "ward_admin"
    jurisdiction_id: str | None = Field(default=None, max_length=64)


class ChangePassword(BaseModel):
    model_config = Strict
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class ComplaintPatch(BaseModel):
    model_config = Strict
    status: str | None = None
    priority_override_score: float | None = Field(default=None, ge=0, le=100)
    override_reason: str | None = Field(default=None, max_length=1000)
    category: str | None = None
    close_reason: str | None = Field(default=None, max_length=1000)
    note: str = Field(default="", max_length=1000)


class AssignRequest(BaseModel):
    model_config = Strict
    department_id: str = Field(min_length=8, max_length=64)
    note: str = Field(default="", max_length=1000)


class ResolveRequest(BaseModel):
    model_config = Strict
    note: str = Field(default="", max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class CategoryCorrect(BaseModel):
    model_config = Strict
    category: str = Field(max_length=40)


class MfaConfirm(BaseModel):
    model_config = Strict
    code: str = Field(min_length=6, max_length=8)


class MfaDisable(BaseModel):
    model_config = Strict
    password: str = Field(max_length=256)
    totp_code: str = Field(min_length=6, max_length=8)


class MfaLoginBackup(BaseModel):
    model_config = Strict
    backup_code: str = Field(min_length=8, max_length=16)
