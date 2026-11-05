"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------- citizen side

class ComplaintCreate(BaseModel):
    description: str = Field(min_length=3, max_length=5000)
    lat: float | None = None
    lon: float | None = None
    landmark_text: str | None = None
    manual_location_confirmed: bool = False
    language: str = "en"
    source: str = "form"
    transcript: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    anonymous: bool = False
    category_override: str | None = None


class EvidenceUpload(BaseModel):
    kind: str = "photo"
    caption: str = ""


class TrackResponse(BaseModel):
    public_id: str
    status: str
    category: str
    category_label: str
    issue_type: str
    priority_band: str
    priority_score: float
    priority_factors: dict[str, Any]
    sla_deadline: datetime | None
    sla_breached: bool
    department: str | None
    location: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    status_history: list[dict[str, Any]]
    incident: dict[str, Any] | None = None
    review_reason: str | None = None
    citizens_affected: int | None = None
    resolution_evidence: list[dict[str, Any]] = []
    can_verify: bool = False


class NearbyIncident(BaseModel):
    incident_id: str
    title: str
    category: str
    distance_m: float | None
    citizens_affected: int
    priority_band: str
    status: str
    lat: float | None
    lon: float | None


class SupportRequest(BaseModel):
    token: str  # tracking token of supporting complaint, optional


class VerifyRequest(BaseModel):
    token: str
    confirmed: bool = True
    note: str = ""


# ------------------------------------------------------------- chat

class ChatSessionCreate(BaseModel):
    ip: str | None = None


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    audio_transcript: str | None = None
    image_data_url: str | None = None


class ChatFeedbackIn(BaseModel):
    message_id: str
    score: int  # 1 or -1


# ------------------------------------------------------------- admin

class AdminLogin(BaseModel):
    username: str
    password: str


class AdminCreate(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""
    role: str = "ward_admin"
    jurisdiction_id: str | None = None


class ComplaintPatch(BaseModel):
    status: str | None = None
    priority_override_score: float | None = None
    override_reason: str | None = None
    category: str | None = None
    note: str = ""


class AssignRequest(BaseModel):
    department_id: str
    note: str = ""


class ResolveRequest(BaseModel):
    note: str = ""
    evidence_ids: list[str] = []


class CategoryCorrect(BaseModel):
    category: str
