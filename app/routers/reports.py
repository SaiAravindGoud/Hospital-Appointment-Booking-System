
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models.entities import (
    Appointment,
    Department,
    Doctor,
    Patient,
    User,
)

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
    dependencies=[Depends(require_roles("Admin"))],
)


def validated_date_range(
    start_date: date | None,
    end_date: date | None,
):
    today = date.today()
    start = start_date or (today - timedelta(days=30))
    end = end_date or today

    if start > end:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )

    return start, end


def appointments_in_range(db: Session, start: date, end: date):
    return db.query(Appointment).filter(
        Appointment.appointment_date >= start,
        Appointment.appointment_date <= end,
    )


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = date.today()

    appointments = (
        db.query(Appointment)
        .filter(Appointment.appointment_date == today)
        .all()
    )

    completed = [
        appointment
        for appointment in appointments
        if appointment.status == "Completed"
    ]

    return {
        "date": today,
        "total_appointments": len(appointments),
        "checked_in": sum(
            appointment.status == "Checked-In"
            for appointment in appointments
        ),
        "completed": len(completed),
        "cancelled": sum(
            appointment.status == "Cancelled"
            for appointment in appointments
        ),
        "no_shows": sum(
            appointment.status == "No-Show"
            for appointment in appointments
        ),
        "consultation_revenue": sum(
            (appointment.consultation_fee or 0)
            for appointment in completed
        ),
    }


@router.get("/doctor-performance")
def doctor_performance(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    start, end = validated_date_range(start_date, end_date)

    doctors = db.query(Doctor).all()
    appointments = appointments_in_range(db, start, end).all()

    results = []

    for doctor in doctors:
        doctor_appointments = [
            appointment
            for appointment in appointments
            if appointment.doctor_id == doctor.id
        ]

        completed = [
            appointment
            for appointment in doctor_appointments
            if appointment.status == "Completed"
        ]

        no_shows = sum(
            appointment.status == "No-Show"
            for appointment in doctor_appointments
        )

        user = db.query(User).filter(User.id == doctor.user_id).first()

        results.append({
            "doctor_id": doctor.id,
            "doctor_name": user.name if user else None,
            "department_id": doctor.department_id,
            "appointment_count": len(doctor_appointments),
            "completed_consultations": len(completed),
            "no_show_count": no_shows,
            "no_show_percentage": round(
                no_shows / len(doctor_appointments) * 100, 2
            ) if doctor_appointments else 0.0,
            "revenue": sum(
                (appointment.consultation_fee or 0)
                for appointment in completed
            ),
        })

    return {
        "start_date": start,
        "end_date": end,
        "doctors": results,
    }


@router.get("/department-summary")
def department_summary(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    start, end = validated_date_range(start_date, end_date)
    appointments = appointments_in_range(db, start, end).all()
    departments = db.query(Department).order_by(Department.name).all()

    results = []

    for department in departments:
        doctor_ids = {
            doctor.id
            for doctor in db.query(Doctor.id)
            .filter(Doctor.department_id == department.id)
            .all()
        }

        count = sum(
            appointment.doctor_id in doctor_ids
            for appointment in appointments
        )

        results.append({
            "department_id": department.id,
            "department_name": department.name,
            "appointment_count": count,
        })

    return {
        "start_date": start,
        "end_date": end,
        "departments": results,
    }


@router.get("/peak-hours")
def peak_hours(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    start, end = validated_date_range(start_date, end_date)
    appointments = appointments_in_range(db, start, end).all()

    counts = {}

    for appointment in appointments:
        hour = appointment.slot_time.hour
        counts[hour] = counts.get(hour, 0) + 1

    hours = [
        {
            "hour": hour,
            "time_range": f"{hour:02d}:00-{hour:02d}:59",
            "appointment_count": counts[hour],
        }
        for hour in sorted(counts)
    ]

    return {
        "start_date": start,
        "end_date": end,
        "peak_hours": sorted(
            hours,
            key=lambda item: item["appointment_count"],
            reverse=True,
        ),
    }


@router.get("/frequent-no-shows")
def frequent_no_shows(
    db: Session = Depends(get_db),
):
    today = date.today()
    start_date = today - timedelta(days=90)

    rows = (
        db.query(
            Patient.id.label("patient_id"),
            User.name.label("patient_name"),
            User.email.label("patient_email"),
            Appointment.id.label("appointment_id"),
        )
        .join(User, User.id == Patient.user_id)
        .join(Appointment, Appointment.patient_id == Patient.id)
        .filter(
            Appointment.status == "No-Show",
            Appointment.appointment_date >= start_date,
            Appointment.appointment_date <= today,
        )
        .all()
    )

    counts = {}

    for row in rows:
        patient_id = row.patient_id

        if patient_id not in counts:
            counts[patient_id] = {
                "patient_id": patient_id,
                "patient_name": row.patient_name,
                "patient_email": row.patient_email,
                "no_show_count": 0,
            }

        counts[patient_id]["no_show_count"] += 1

    frequent = [
        item for item in counts.values()
        if item["no_show_count"] >= 3
    ]

    frequent.sort(
        key=lambda item: item["no_show_count"],
        reverse=True,
    )

    return {
        "start_date": start_date,
        "end_date": today,
        "minimum_no_shows": 3,
        "patients": frequent,
    }
