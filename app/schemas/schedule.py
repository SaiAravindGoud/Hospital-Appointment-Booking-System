
from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleCreate(BaseModel):
    day_of_week: str
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        days = {
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        }

        if self.day_of_week not in days:
            raise ValueError("Use a full weekday name, e.g. Monday")

        if self.start_time >= self.end_time:
            raise ValueError("Start time must be before end time")

        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("Provide both break start and break end")

        if self.break_start is not None:
            if not (
                self.start_time < self.break_start
                < self.break_end < self.end_time
            ):
                raise ValueError("Break must fall within the schedule")

        return self


class ScheduleResponse(BaseModel):
    id: int
    doctor_id: int
    day_of_week: str
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None

    model_config = ConfigDict(from_attributes=True)


class DoctorLeaveCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class DoctorLeaveResponse(BaseModel):
    id: int
    doctor_id: int
    start_date: date
    end_date: date
    reason: str | None

    model_config = ConfigDict(from_attributes=True)
