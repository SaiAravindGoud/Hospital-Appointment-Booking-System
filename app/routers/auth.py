
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_user_id,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.database import get_db
from app.models import Patient, RefreshToken, User
from app.schemas.auth import (
    AdminCreateUser,
    LoginRequest,
    LogoutRequest,
    PatientRegister,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def issue_tokens(db: Session, user: User) -> dict:
    access_token = create_access_token(user.id, user.role)
    refresh_token, expires_at = create_refresh_token(user.id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
            revoked=False,
        )
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_patient(
    data: PatientRegister,
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == str(data.email)).first():
        raise HTTPException(
            status_code=409, detail="Email is already registered"
        )

    user = User(
        name=data.name,
        email=str(data.email),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role="Patient",
        is_active=True,
    )

    try:
        db.add(user)
        db.flush()
        db.add(Patient(user_id=user.id))
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Email is already registered"
        )


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(data.email)).first()

    if (
        user is None
        or not verify_password(data.password, user.hashed_password)
        or not user.is_active
    ):
        raise HTTPException(
            status_code=401, detail="Invalid email or password"
        )

    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(
    data: RefreshRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(data.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        user_id = get_token_user_id(payload)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=401, detail="Invalid or expired refresh token"
        )

    token_hash = hash_refresh_token(data.refresh_token)
    stored = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
        .with_for_update()
        .first()
    )

    if (
        stored is None
        or stored.expires_at <= datetime.utcnow()
    ):
        raise HTTPException(
            status_code=401, detail="Invalid or expired refresh token"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")

    # Rotate the refresh token: the previous one cannot be reused.
    stored.revoked = True
    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/logout")
def logout(
    data: LogoutRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(data.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        user_id = get_token_user_id(payload)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=401, detail="Invalid or expired refresh token"
        )

    stored = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash
            == hash_refresh_token(data.refresh_token),
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
        .first()
    )

    if stored is None or stored.expires_at <= datetime.utcnow():
        raise HTTPException(
            status_code=401, detail="Refresh token is revoked or expired"
        )

    stored.revoked = True
    db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post(
    "/admin/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_privileged_user(
    data: AdminCreateUser,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    if db.query(User).filter(User.email == str(data.email)).first():
        raise HTTPException(
            status_code=409, detail="Email is already registered"
        )

    user = User(
        name=data.name,
        email=str(data.email),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=data.role,
        is_active=True,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Email is already registered"
        )
