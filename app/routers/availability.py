
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Doctor, DoctorLeave, DoctorSchedule

router = APIRouter(tags=["Doctor Availability"])


@router.get("/doctors/{doctor_id}/available-slots")
def get_available_slots(
    doctor_id: int,
    appointment_date: date = Query(...),
    db: Session = Depends(get_db),
):
    if appointment_date < date.today():
        raise HTTPException(
            status_code=400,
            detail="Appointment date cannot be in the past",
        )

    doctor = (
        db.query(Doctor)
        .filter(Doctor.id == doctor_id, Doctor.is_active.is_(True))
        .first()
    )

    if doctor is None:
        raise HTTPException(status_code=404, detail="Active doctor not found")

    leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.start_date <= appointment_date,
            DoctorLeave.end_date >= appointment_date,
        )
        .first()
    )

    if leave:
        return {
            "doctor_id": doctor_id,
            "appointment_date": appointment_date.isoformat(),
            "available_slots": [],
            "message": "Doctor is on leave",
        }

    day_name = appointment_date.strftime("%A")

    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == day_name,
        )
        .order_by(DoctorSchedule.start_time)
        .all()
    )

    if not schedules:
        return {
            "doctor_id": doctor_id,
            "appointment_date": appointment_date.isoformat(),
            "available_slots": [],
            "message": "No schedule configured for this day",
        }

    existing_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status.notin_(["Cancelled", "No-show"]),
        )
        .all()
    )

    booked_times = {appointment.slot_time for appointment in existing_appointments}
    duration = doctor.slot_duration_minutes
    available_slots = []

    for schedule in schedules:
        current = datetime.combine(appointment_date, schedule.start_time)
        end = datetime.combine(appointment_date, schedule.end_time)

        while current + timedelta(minutes=duration) <= end:
            slot_start = current.time()
            slot_end = (current + timedelta(minutes=duration)).time()

            overlaps_break = (
                schedule.break_start is not None
                and schedule.break_end is not None
                and slot_start < schedule.break_end
                and slot_end > schedule.break_start
            )

            already_booked = slot_start in booked_times

            if not overlaps_break and not already_booked:
                if (
                    appointment_date != date.today()
                    or slot_start > datetime.now().time()
                ):
                    available_slots.append({
                        "start_time": slot_start.strftime("%H:%M:%S"),
                        "end_time": slot_end.strftime("%H:%M:%S"),
                    })

            current += timedelta(minutes=duration)

    return {
        "doctor_id": doctor_id,
        "appointment_date": appointment_date.isoformat(),
        "available_slots": available_slots,
        "message": "Available slots retrieved successfully",
    }
