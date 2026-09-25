from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

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
