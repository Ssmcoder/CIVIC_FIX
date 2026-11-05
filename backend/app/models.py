"""SQLAlchemy models for CivicFix 360.

Mirrors supabase/migrations/0001_init.sql. Uses SQLite-compatible geometry
(latitude/longitude columns) so the same schema works locally and can be
ported to PostGIS for production.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- reference

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category_map: Mapped[str] = mapped_column(Text, default="{}")  # JSON: category -> dept id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String(20))  # state|district|municipality|ward
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    # Geo bounds (simple, works on SQLite and PostGIS via migration)
    min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geom_wkt: Mapped[str | None] = mapped_column(Text, nullable=True)  # PostGIS polygon WKT


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(160), unique=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(30), default="ward_admin")
    # state_admin|district_admin|municipal_admin|ward_admin|super_admin
    jurisdiction_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SlaRule(Base):
    __tablename__ = "sla_rules"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    category: Mapped[str] = mapped_column(String(40))          # or "*"
    priority_band: Mapped[str] = mapped_column(String(20))     # critical|high|medium|low
    deadline_hours: Mapped[int] = mapped_column(Integer)
    escalation_hours: Mapped[int] = mapped_column(Integer, default=24)


class PriorityConfig(Base):
    __tablename__ = "priority_config"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")


class MlModel(Base):
    __tablename__ = "ml_models"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(String(300))
    metrics: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FaqDocument(Base):
    __tablename__ = "faq_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(String(120), default="")
    tags: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- core flow

class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    public_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # CFX-2026-00142
    tracking_token_hash: Mapped[str] = mapped_column(String(128), unique=True)

    description: Mapped[str] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en")
    source: Mapped[str] = mapped_column(String(20), default="form")  # form|chat|voice|qr|api

    # classification
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    issue_type: Mapped[str] = mapped_column(String(80), default="")
    ai_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    # location
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    landmark_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    location_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    ward_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    municipality_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)

    # priority & SLA (deterministic)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    severity_score: Mapped[float] = mapped_column(Float, default=50.0)
    safety_risk: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_band: Mapped[str] = mapped_column(String(20), default="medium")
    priority_factors: Mapped[str] = mapped_column(Text, default="{}")  # JSON explanation
    priority_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    department_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("departments.id"), nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    # received|under_review|inspection_scheduled|in_progress|resolved|awaiting_verification|reopened|closed
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("incidents.id"), nullable=True)

    # trust/spam signals (never suppress complaints)
    trust_flags: Mapped[str] = mapped_column(Text, default="[]")

    # optional contact (private)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    evidence: Mapped[list["Evidence"]] = relationship(back_populates="complaint", cascade="all, delete-orphan")
    status_history: Mapped[list["StatusHistory"]] = relationship(back_populates="complaint", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str] = mapped_column(String(32), ForeignKey("complaints.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="photo")  # photo|video|audio|document
    file_path: Mapped[str] = mapped_column(String(400))
    original_name: Mapped[str] = mapped_column(String(200), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(Text, default="")
    is_resolution: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    complaint: Mapped[Complaint] = relationship(back_populates="evidence")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    ward_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jurisdictions.id"), nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("departments.id"), nullable=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_band: Mapped[str] = mapped_column(String(20), default="medium")
    priority_factors: Mapped[str] = mapped_column(Text, default="{}")
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    # open|in_progress|awaiting_verification|resolved|closed|reopened
    citizens_affected: Mapped[int] = mapped_column(Integer, default=1)
    first_reported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    reports: Mapped[list["IncidentReport"]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class IncidentReport(Base):
    __tablename__ = "incident_reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.id"), index=True)
    complaint_id: Mapped[str] = mapped_column(String(32), ForeignKey("complaints.id"), unique=True)
    match_text_sim: Mapped[float] = mapped_column(Float, default=0.0)
    match_geo_dist_m: Mapped[float] = mapped_column(Float, default=0.0)
    match_evidence: Mapped[str] = mapped_column(Text, default="{}")  # JSON explanation
    link_type: Mapped[str] = mapped_column(String(20), default="auto")  # auto|reviewed|manual|citizen_confirmed|citizen_denied
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    incident: Mapped[Incident] = relationship(back_populates="reports")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str] = mapped_column(String(32), ForeignKey("complaints.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("incidents.id"), nullable=True)
    department_id: Mapped[str] = mapped_column(String(32), ForeignKey("departments.id"))
    assigned_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SlaRecord(Base):
    __tablename__ = "sla_records"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str] = mapped_column(String(32), ForeignKey("complaints.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("incidents.id"), nullable=True)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    breached: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StatusHistory(Base):
    __tablename__ = "status_history"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str] = mapped_column(String(32), ForeignKey("complaints.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("incidents.id"), nullable=True)
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30))
    actor_type: Mapped[str] = mapped_column(String(20), default="system")  # system|admin|citizen|ai
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    complaint: Mapped[Complaint] = relationship(back_populates="status_history")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("complaints.id"), nullable=True)
    admin_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))  # new_complaint|sla_breach|escalation|assignment|status_update
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    admin_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    ip_hash: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(Text, default="{}")  # JSON dialogue state
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user|assistant|system
    content: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1|-1
    scope: Mapped[str] = mapped_column(String(20), default="civic")  # civic|out_of_scope|unclear
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    session: Mapped[ChatSession] = relationship(back_populates="messages")


class MlFeedback(Base):
    __tablename__ = "ml_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    complaint_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chat_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))  # category_correction|dup_accept|dup_reject|citizen_override|citizen_confirm|citizen_deny|chat_feedback
    input_text: Mapped[str] = mapped_column(Text, default="")
    input_features: Mapped[str] = mapped_column(Text, default="{}")
    predicted_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confirmed_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
