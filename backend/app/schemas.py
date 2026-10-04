import json
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, AliasChoices, field_validator


# -------------------------------------------------------------
# 1. Request Payloads (Input DTOs sent from client to server)
# Pydantic validates data types, length constraints, and formats.
# -------------------------------------------------------------

class UserRegister(BaseModel):
    """
    Payload for POST /api/auth/register.
    Enforces minimum sanity checks on user registration input.
    """
    username: str = Field(..., min_length=3, max_length=50, description="Unique account username")
    email: str = Field(..., min_length=5, max_length=255, description="User email address")
    password: str = Field(..., min_length=6, description="Plaintext password to be hashed by backend")

class UserLogin(BaseModel):
    """
    Payload for POST /api/auth/login.
    Contains credentials to authenticate and issue JWT.
    """
    username: str
    password: str

class UserUpdate(BaseModel):
    """
    Payload for PATCH /api/users/:id.
    Allows partial updates: changing email, password, or both.
    """
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    password: Optional[str] = Field(None, min_length=6)

# -------------------------------------------------------------
# 2. Response Payloads (Output DTOs sent from server to client)
# -------------------------------------------------------------

class UserResponse(BaseModel):
    """
    Public representation of a user profile.
    
    CRITICAL SECURITY ENFORCEMENT (Rule 1):
    This schema deliberately OMITs 'password' and 'hashed_password'.
    FastAPI uses this response model to serialize ORM objects into JSON,
    physically guaranteeing that password hashes are NEVER exposed.
    """
    id: int
    username: str
    email: str
    created_at: datetime

    # Enables reading data directly from SQLAlchemy ORM models
    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    """
    Response schema for POST /api/auth/login.
    Conforms to OAuth2 Bearer Token standard (RFC 6750).
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class HealthResponse(BaseModel):
    """
    Response schema for GET /healthz.
    Course requirement: returns { "status": "ok" }
    """
    status: str = "ok"


# -------------------------------------------------------------
# 3. Agentic Tracker Schemas (Task 5.2)
# -------------------------------------------------------------

class TrackerArticleItem(BaseModel):
    """
    Audit log of an article fetch operation during a tracker execution.
    Captures network metrics, SSRF guardrail status, and payload size.
    """
    id: Optional[int] = None
    url: str
    title: Optional[str] = None
    status: str = "fetched"  # "fetched", "rejected", "error"
    byte_size: int = 0
    fetch_time_ms: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TrackerDevelopmentItem(BaseModel):
    """
    Canonical job development item synthesized in the Top K report.
    Guarantees strict source provenance and multi-run differential status badges.
    """
    id: Optional[int] = None
    rank: int = 1
    title: str = "AI/ML Role"
    company: str = "Company"
    primary_url: str = Field(
        default="",
        validation_alias=AliasChoices("primary_url", "url"),
        description="Verified canonical source URL"
    )
    supporting_sources: Optional[List[str]] = Field(default_factory=list)
    location: Optional[str] = "Remote / Hybrid"
    compensation: Optional[str] = None
    qualifications_summary: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("qualifications_summary", "snippet")
    )
    recrawl_status: str = "New since last run"  # "New since last run", "Still in top K", "Dropped"
    fingerprint: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("supporting_sources", mode="before")
    @classmethod
    def parse_supporting_sources(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
                return [str(parsed)]
            except Exception:
                return [v]
        return []


class TrackerRunCreate(BaseModel):
    """
    Payload for POST /api/tracker/runs.
    Accepts run telemetry, discovered canonical jobs, and fetch audit logs.
    """
    user_id: Optional[int] = None
    run_number: int = 1
    topic: str = "Top 10 newest entry-level and new grad AI/ML engineering roles"
    target_k: int = 10
    status: str = "complete"  # "complete", "partial", "error"
    step_count: int = 0
    fetch_count: int = 0
    tokens_spent: int = 0
    report_path: Optional[str] = None
    trace_path: Optional[str] = None
    jobs: Optional[List[TrackerDevelopmentItem]] = None
    developments: Optional[List[TrackerDevelopmentItem]] = None
    articles: Optional[List[TrackerArticleItem]] = None


class TrackerRunResponse(BaseModel):
    """
    Response schema for a single tracker run execution.
    """
    id: int
    user_id: int
    run_number: int
    topic: str
    target_k: int
    status: str
    step_count: int
    fetch_count: int
    tokens_spent: int
    report_path: Optional[str] = None
    trace_path: Optional[str] = None
    created_at: datetime
    developments: List[TrackerDevelopmentItem] = []
    articles: List[TrackerArticleItem] = []

    model_config = ConfigDict(from_attributes=True)


class TrackerTriggerRequest(BaseModel):
    """
    Request payload for triggering an autonomous tracker run asynchronously.
    """
    reset: bool = False
    steps_override: Optional[int] = None


class TrackerTriggerResponse(BaseModel):
    """
    Response schema for POST /api/tracker/trigger.
    """
    status: str = "triggered"
    message: str
    run_number: Optional[int] = None
    run_id: Optional[int] = None


class TrackerHistorySummary(BaseModel):
    """
    Response schema for GET /api/tracker/history.
    Aggregates telemetry and historical execution runs for the authenticated user.
    """
    total_runs: int
    last_run_number: int = 0
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    total_steps: int = 0
    total_fetches: int = 0
    total_tokens: int = 0
    runs: List[TrackerRunResponse] = []

