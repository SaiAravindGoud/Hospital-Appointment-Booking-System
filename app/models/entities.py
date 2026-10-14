
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    phone: Mapped[str] = mapped_column(String(10), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="Patient")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    patient_profile: Mapped[Patient | None] = relationship(
        back_populates="user", uselist=False
    )
    doctor_profile: Mapped[Doctor | None] = relationship(
        back_populates="user", uselist=False
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(120), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctors: Mapped[list[Doctor]] = relationship(back_populates="department")


class Doctor(TimestampMixin, Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id"), nullable=False, index=True
    )
    specialization: Mapped[str] = mapped_column(String(150), nullable=False)
    qualification: Mapped[str] = mapped_column(String(255), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consultation_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="doctor_profile")
    department: Mapped[Department] = relationship(back_populates="doctors")
    schedules: Mapped[list[DoctorSchedule]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    leaves: Mapped[list[DoctorLeave]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="doctor"
    )


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="patient_profile")
    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="patient"
    )


class DoctorSchedule(TimestampMixin, Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"), nullable=False, index=True
    )
    day_of_week: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class DoctorLeave(TimestampMixin, Base):
    __tablename__ = "doctor_leaves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    doctor: Mapped[Doctor] = relationship(back_populates="leaves")


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("appointment_number", name="uq_appointment_number"),
        UniqueConstraint("active_slot_key", name="uq_active_slot_key"),
        UniqueConstraint(
            "active_patient_time_key", name="uq_active_patient_time_key"
        ),
        UniqueConstraint(
            "active_patient_doctor_day_key",
            name="uq_active_patient_doctor_day_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_number: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"), nullable=False, index=True
    )
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_time: Mapped[time] = mapped_column(Time, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default="Booked", nullable=False, index=True
    )
    consultation_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    reminder_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    reschedule_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # The booking service sets these keys for reserved appointments.
    # Clear the relevant key when a slot is released.
    active_slot_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    active_patient_time_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    active_patient_doctor_day_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    patient: Mapped[Patient] = relationship(back_populates="appointments")
    doctor: Mapped[Doctor] = relationship(back_populates="appointments")
    consultation: Mapped[Consultation | None] = relationship(
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    files: Mapped[list[UploadedFile]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )
    history: Mapped[list[AppointmentHistory]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )


class AppointmentHistory(TimestampMixin, Base):
    __tablename__ = "appointment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False, index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    appointment: Mapped[Appointment] = relationship(back_populates="history")


class Consultation(TimestampMixin, Base):
    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), unique=True, nullable=False
    )
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    prescription: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    appointment: Mapped[Appointment] = relationship(
        back_populates="consultation"
    )


class UploadedFile(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False, index=True
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    file_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    size_kb: Mapped[int] = mapped_column(Integer, nullable=False)

    appointment: Mapped[Appointment] = relationship(back_populates="files")
