"""
Authentication routes: register, login, refresh, logout, me.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.organization import Organization
from schemas.auth import (
    UserRegister, UserLogin, Token, UserResponse,
    OrganizationResponse, UserUpdate,
)
from core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)
from config import DEFAULT_ORG_NAME


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_or_create_default_org(db: Session) -> Organization:
    org = db.query(Organization).filter(Organization.name == DEFAULT_ORG_NAME).first()
    if not org:
        org = Organization(name=DEFAULT_ORG_NAME)
        db.add(org)
        db.commit()
        db.refresh(org)
    return org


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """Register a new user. Creates organization if name is new."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Determine organization
    if payload.organization_name:
        org = db.query(Organization).filter(
            Organization.name == payload.organization_name
        ).first()
        if not org:
            org = Organization(name=payload.organization_name)
            db.add(org)
            db.flush()
    else:
        org = _get_or_create_default_org(db)

    role = "analyst"

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        organization_id=org.id,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token, expires_in = create_access_token(user)
    refresh_token = create_refresh_token(user)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Login with email + password. Returns JWT tokens."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    user.last_login = datetime.utcnow()
    db.commit()

    access_token, expires_in = create_access_token(user)
    refresh_token = create_refresh_token(user)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=Token)
def refresh(refresh_token: str, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new access token."""
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
        )

    access_token, expires_in = create_access_token(user)
    new_refresh = create_refresh_token(user)

    return Token(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user)):
    """Logout (stateless JWT - client should discard token).
    For server-side invalidation, integrate with Redis denylist later.
    """
    return None


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return user


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me/organization", response_model=OrganizationResponse)
def get_my_org(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org
