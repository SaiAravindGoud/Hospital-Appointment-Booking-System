
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class PatientRegister(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must contain exactly 10 digits")
        return value


class AdminCreateUser(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)
    role: Literal["Admin", "Doctor"]

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError("Phone number must contain exactly 10 digits")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800
