
from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AppointmentCreate(BaseModel):
    doctor_id: int = Field(gt=0)
    appointment_date: date
    slot_time: time
    reason: str | None = Field(default=None, max_length=2000)


class AppointmentResponse(BaseModel):
    id: int
    appointment_number: str
    patient_id: int
    doctor_id: int
    appointment_date: date
    slot_time: time
    token_number: int
    reason: str | None
    status: str
    consultation_fee: Decimal
    reschedule_count: int

    model_config = ConfigDict(from_attributes=True)
