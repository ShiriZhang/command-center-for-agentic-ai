from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserRegister, UserLogin, UserResponse, TokenResponse
from ..auth import hash_password, verify_password, create_access_token, get_current_user

# Group all authentication routes under /api/auth prefix
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    POST /api/auth/register (Public endpoint)
    Registers a new user account, encrypts password with bcrypt, and stores in database.
    
    Security & Validation:
    - Rejects duplicate username or email with HTTP 400 Bad Request.
    - Serializes through UserResponse to guarantee Rule 1 (no password hash returned).
    - Returns HTTP 201 Created on success (REST standard for newly created resources).
    """
    # Check 1: Duplicate username check
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is already registered"
        )

    # Check 2: Duplicate email check
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered"
        )

    # Encrypt password using 12-round bcrypt slow hashing
    hashed_pwd = hash_password(user_data.password)

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_pwd
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    POST /api/auth/login (Public endpoint)
    Authenticates username and password, then issues a signed JWT Bearer token.
    
    OWASP Security Standard:
    Returns identical "Invalid username or password" for both unknown usernames
    and wrong passwords to prevent user enumeration attacks.
    """
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Issue signed JWT token embedding user ID in 'sub' claim
    access_token = create_access_token(data={"sub": str(user.id), "username": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """
    GET /api/auth/me (Protected endpoint)
    Returns the profile of the currently logged-in user.
    
    Rule 1 Compliance: Response filtered through UserResponse (no hash).
    Rule 2 Compliance: Missing, bad, or expired token raises HTTP 401 via get_current_user.
    """
    return current_user
