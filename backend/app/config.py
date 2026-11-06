"""Centralised settings — every security-relevant value comes from env.

Production mode refuses insecure defaults (CF-02, CF-19, CF-22).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("civicfix.config")

INSECURE_JWT_DEFAULT = "dev-secret-change-me"
INSECURE_TRACKING_DEFAULT = "tracking-dev-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- environment ---
    environment: str = "development"  # development | staging | production
    enable_docs: bool = False
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- database / storage ---
    database_url: str = "sqlite+aiosqlite:///./civicfix.db"
    redis_url: str = ""  # optional; rate limiter falls back to memory outside prod
    media_dir: str = "./media"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_images_per_complaint: int = 5
    clamav_host: str = ""
    clamav_port: int = 3310

    # --- secrets (CF-02) ---
    secret_key: str = INSECURE_JWT_DEFAULT
    jwt_issuer: str = "civicfix"
    jwt_audience: str = "civicfix-admin"
    access_token_expire_minutes: int = 15
    refresh_token_idle_hours: int = 8
    refresh_token_absolute_days: int = 7
    # ordered "kid:secret" list; first entry is current
    tracking_hash_keys: str = "v1:tracking-dev-secret"
    ip_hash_key: str = "ip-hash-dev-secret"
    fernet_key: str = ""  # encrypts TOTP secrets at rest; required for MFA in prod

    # --- rate limits (CF-07) ---
    rl_login_ip_per_min: int = 10
    rl_login_user_per_min: int = 5
    rl_submit_per_hour: int = 5
    rl_evidence_per_hour: int = 20
    rl_track_per_min: int = 10
    rl_chat_session_per_hour: int = 10
    rl_chat_ip_per_min: int = 30
    rl_nearby_per_min: int = 30
    rl_global_per_min: int = 120

    # --- trusted proxy (CF-18) ---
    trusted_proxy_count: int = 0
    forwarded_allow_ips: str = ""

    # --- chatbot / LLM ---
    llm_provider: str = "ollama"  # ollama | openai | rule
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- ML ---
    ml_model_dir: str = "../ml/models"
    ml_model_manifest: str = ""  # path to SHA-256 manifest (CF-12)
    embedding_backend: str = "auto"
    enable_ml_retrain: bool = False
    classify_review_threshold: float = 0.55
    dedup_auto_link_threshold: float = 0.82
    dedup_review_threshold: float = 0.62
    dedup_max_distance_m: float = 300.0
    dedup_time_window_days: int = 30

    # --- location / privacy (CF-06) ---
    default_lat: float = 20.2986
    default_lon: float = 85.8245
    nearby_default_radius_m: int = 500
    nearby_max_radius_m: int = 2000
    nearby_max_limit: int = 50

    # --- MFA policy ---
    mfa_required_roles: str = "super_admin,state_admin,district_admin,municipal_admin"
    mfa_required_for_ward: bool = False

    # --- password policy ---
    password_min_length: int = 12
    password_max_length: int = 128

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def media_path(self) -> str:
        import os
        p = os.path.abspath(self.media_dir)
        os.makedirs(p, exist_ok=True)
        return p

    @property
    def tracking_keys(self) -> list[tuple[str, str]]:
        """Parsed [(kid, secret), ...] in order; first is current."""
        out = []
        for part in self.tracking_hash_keys.split(","):
            part = part.strip()
            if ":" in part:
                kid, sec = part.split(":", 1)
                out.append((kid.strip(), sec.strip()))
        return out or [("v1", self.tracking_hash_keys)]

    @property
    def current_tracking_kid(self) -> str:
        return self.tracking_keys[0][0]

    @property
    def mfa_roles(self) -> set[str]:
        roles = {r.strip() for r in self.mfa_required_roles.split(",") if r.strip()}
        if self.mfa_required_for_ward:
            roles.add("ward_admin")
        return roles

    def validate_security(self) -> None:
        """Fail fast on insecure config in production; warn loudly otherwise."""
        problems = []
        if self.secret_key == INSECURE_JWT_DEFAULT or len(self.secret_key.encode()) < 32:
            problems.append("SECRET_KEY is default or < 32 bytes")
        kids = self.tracking_keys
        if any(sec == INSECURE_TRACKING_DEFAULT for _, sec in kids):
            problems.append("TRACKING_HASH_KEYS contains the default key")
        if self.secret_key in {sec for _, sec in kids}:
            problems.append("SECRET_KEY equals a tracking-hash key")
        if self.ip_hash_key == "ip-hash-dev-secret":
            problems.append("IP_HASH_KEY is default")
        if not self.fernet_key:
            problems.append("FERNET_KEY unset (required to encrypt TOTP secrets)")
        if self.is_production and self.cors_origins and "localhost" in self.cors_origins:
            problems.append("CORS_ORIGINS contains localhost in production")
        if problems:
            msg = "Insecure configuration: " + "; ".join(problems)
            if self.is_production:
                raise RuntimeError(msg)
            log.warning("SECURITY WARNING (non-production): %s", msg)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_security()
    return s
