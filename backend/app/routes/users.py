from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserResponse, UserUpdate
from ..auth import get_current_user, hash_password

# Group all user management endpoints under /api/users prefix
router = APIRouter(prefix="/api/users", tags=["Users"])

@router.get("/{user_id}", response_model=UserResponse)
def get_user_by_id(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    GET /api/users/:id (Protected endpoint)
    Retrieves profile information for the specified user ID.
    
    🎯 CRITICAL ENFORCEMENT - RULE 3 (Horizontal Authorization):
    If the requested :id does not match the authenticated user's ID,
    we consistently return HTTP 403 Forbidden.
    """
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot access another user's account"
        )
    return current_user

@router.patch("/{user_id}", response_model=UserResponse)
def update_user_by_id(
    user_id: int,
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    PATCH /api/users/:id (Protected endpoint)
    Updates email and/or password for the specified user ID.
    
    🎯 CRITICAL ENFORCEMENT - RULE 3:
    Cross-user update requests consistently return HTTP 403 Forbidden.
    """
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot modify another user's account"
        )

    # If updating email, check for conflicts with other accounts
    if update_data.email and update_data.email != current_user.email:
        existing = db.query(User).filter(User.email == update_data.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already in use by another account"
            )
        current_user.email = update_data.email

    # If updating password, hash with 12-round bcrypt before persisting
    if update_data.password:
        current_user.hashed_password = hash_password(update_data.password)

    db.commit()
    db.refresh(current_user)
    return current_user

@router.delete("/{user_id}")
def delete_user_by_id(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    DELETE /api/users/:id (Protected endpoint)
    Permanently deletes the specified user account.
    
    🎯 CRITICAL ENFORCEMENT - RULE 3:
    Cross-user deletion requests consistently return HTTP 403 Forbidden.
    """
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You cannot delete another user's account"
        )

    db.delete(current_user)
    db.commit()
    return {"status": "ok", "message": f"User {user_id} deleted successfully"}
