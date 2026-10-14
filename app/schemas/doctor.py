from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class DoctorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)
    department_id: int = Field(gt=0)
    specialization: str = Field(min_length=2, max_length=150)
    qualification: str = Field(min_length=2, max_length=255)
    experience_years: int = Field(default=0, ge=0, le=70)
    consultation_fee: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
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

    model_config = ConfigDict(from_attributes=True)
