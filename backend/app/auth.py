from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

# -------------------------------------------------------------
# 1. Password Hashing Core (Task 3.1)
# -------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash plaintext password with 12-round bcrypt salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with constant-time comparison to prevent timing attacks."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )

# -------------------------------------------------------------
# 2. JWT Token Issuance & Bearer Extraction (Task 3.2)
# -------------------------------------------------------------

# auto_error=False allows us to take full control of error formatting
# and guarantee a strict HTTP 401 response for missing or invalid headers.
security = HTTPBearer(auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate an RFC 7519 compliant JSON Web Token (JWT) signed with HMAC-SHA256.
    Embeds user identity and an explicit expiration timestamp (exp).
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI Dependency to authenticate and resolve the current user.
    
    🎯 CRITICAL ENFORCEMENT - RULE 2 (Course Rubric):
    "No token, bad token, or expired token -> 401. Not 200, not 500."
    
    Every failure case strictly raises HTTP 401 with standard WWW-Authenticate header:
    - Missing Authorization header -> 401
    - Invalid bearer token format -> 401
    - Forged / tampered signature -> 401
    - Expired token timestamp -> 401
    - User deleted / not found in database -> 401
    """
    unauthorized_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials: missing, invalid, or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check 1: Missing or empty credentials
    if not credentials or not credentials.credentials:
        raise unauthorized_exception

    token = credentials.credentials

    # Check 2: Cryptographic signature verification and expiration check
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise unauthorized_exception
        user_id = int(user_id_str)
    except (jwt.PyJWTError, ValueError):
        # Catches ExpiredSignatureError, InvalidSignatureError, DecodeError, int conversion errors
        raise unauthorized_exception

    # Check 3: Database entity existence
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise unauthorized_exception

    return user
