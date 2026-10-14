from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user, require_roles
from app.auth.security import hash_password
from app.database import get_db
from app.models import Department, Doctor, User
from app.schemas.doctor import DoctorCreate as DoctorCreateSchema


class DoctorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)
    department_id: int = Field(gt=0)
    specialization: str = Field(min_length=2, max_length=150)
    qualification: str = Field(min_length=2, max_length=255)
    experience_years: int = Field(default=0, ge=0, le=70)
    consultation_fee: Decimal = Field(
        gt=0, max_digits=10, decimal_places=2
    )
    slot_duration_minutes: int = Field(default=15)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must contain exactly 10 digits")
        return value

    @field_validator("slot_duration_minutes")
    @classmethod
    def validate_slot_duration(cls, value: int) -> int:
        if value not in (10, 15, 20, 30):
            raise ValueError(
                "Slot duration must be 10, 15, 20, or 30 minutes"
            )
        return value


class DoctorUserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str

    model_config = ConfigDict(from_attributes=True)


class DoctorDepartmentResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class DoctorResponse(BaseModel):
    id: int
    user_id: int
    department_id: int
    specialization: str
    qualification: str
    experience_years: int
    consultation_fee: Decimal
    slot_duration_minutes: int
    is_active: bool
    user: DoctorUserResponse
    department: DoctorDepartmentResponse

    model_config = ConfigDict(from_attributes=True)


router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.post(
    "",
    response_model=DoctorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor(
    data: DoctorCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    email = str(data.email).strip().lower()

    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    department = db.query(Department).filter(
        Department.id == data.department_id,
        Department.is_active.is_(True),
    ).first()

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active department not found",
        )

    user = User(
        name=data.name.strip(),
        email=email,
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role="Doctor",
        is_active=True,
    )

    try:
        db.add(user)
        db.flush()

        doctor = Doctor(
            user_id=user.id,
            department_id=data.department_id,
            specialization=data.specialization.strip(),
            qualification=data.qualification.strip(),
            experience_years=data.experience_years,
            consultation_fee=data.consultation_fee,
            slot_duration_minutes=data.slot_duration_minutes,
            is_active=True,
        )

        db.add(doctor)
        db.commit()

        doctor = (
            db.query(Doctor)
            .options(
                joinedload(Doctor.user),
                joinedload(Doctor.department),
            )
            .filter(Doctor.id == doctor.id)
            .first()
        )

        return doctor

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A doctor with the supplied details already exists",
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.get("", response_model=list[DoctorResponse])
def list_doctors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    department_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Doctor)
        .options(
            joinedload(Doctor.user),
            joinedload(Doctor.department),
        )
        .join(Doctor.user)
        .filter(
            Doctor.is_active.is_(True),
            User.is_active.is_(True),
            Doctor.department.has(Department.is_active.is_(True)),
        )
    )

    if department_id is not None:
        query = query.filter(Doctor.department_id == department_id)

    return (
        query.order_by(Doctor.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    doctor = (
        db.query(Doctor)
        .options(
            joinedload(Doctor.user),
            joinedload(Doctor.department),
        )
        .filter(Doctor.id == doctor_id)
        .first()
    )

    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    return doctor


@router.patch("/{doctor_id}/deactivate")
def deactivate_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id
    ).first()

    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    doctor.is_active = False

    user = db.query(User).filter(
        User.id == doctor.user_id
    ).first()

    if user is not None:
        user.is_active = False

    db.commit()

    return {
        "message": "Doctor deactivated successfully",
        "doctor_id": doctor_id,
    }
